"""Actual audio measurements, not merely successful waveform scaffolding."""

import math
import shutil
import subprocess

import pytest

from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT, DEFAULT_WAVEFORM_LEVEL_FLOOR
from kinocut.engine_audio_waveform import audio_waveform

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")


def _fixture(tmp_path, expression, *, duration=3.0, audio_duration=None, offset=0):
    path = tmp_path / "waveform.mkv"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=black:s=16x16:r=10:d={duration}",
        "-itsoffset",
        str(offset),
        "-f",
        "lavfi",
        "-i",
        f"aevalsrc={expression}:s=8000:d={audio_duration or duration}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "ffv1",
        "-c:a",
        "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=DEFAULT_FFMPEG_TIMEOUT)
    return str(path)


def test_real_quiet_loud_and_silence_bins_are_time_aligned(tmp_path):
    path = _fixture(tmp_path, r"if(lt(t\,1)\,0.1\,if(lt(t\,2)\,0.01\,0))")
    result = audio_waveform(path, bins=12)
    assert result.synthetic is False
    assert len(result.peaks) == 12
    assert [peak["level"] for peak in result.peaks[:4]] == pytest.approx([-20] * 4, abs=0.1)
    assert [peak["level"] for peak in result.peaks[4:8]] == pytest.approx([-40] * 4, abs=0.1)
    assert [peak["level"] for peak in result.peaks[8:]] == [DEFAULT_WAVEFORM_LEVEL_FLOOR] * 4
    # RMS is mean *power*, not mean dB. The silent third remains in the denominator.
    assert result.mean_level == pytest.approx(10 * math.log10((0.1**2 + 0.01**2) / 3), abs=0.1)
    assert result.silence_regions == [{"start": 2.0, "end": 3.0}]
    assert result.peaks[0]["time"] == pytest.approx(0.12, abs=0.01)
    assert result.peaks[-1]["time"] == pytest.approx(2.88, abs=0.01)


def test_silent_audio_is_measured_and_json_levels_are_finite(tmp_path):
    result = audio_waveform(_fixture(tmp_path, "0"), bins=10)
    assert result.synthetic is False
    assert result.mean_level == DEFAULT_WAVEFORM_LEVEL_FLOOR
    assert result.min_level == result.max_level == DEFAULT_WAVEFORM_LEVEL_FLOOR
    assert result.silence_regions == [{"start": 0.0, "end": 3.0}]
    assert all(math.isfinite(peak["level"]) for peak in result.peaks)


def test_late_audio_stays_at_its_source_time(tmp_path):
    result = audio_waveform(_fixture(tmp_path, "0.1", duration=1.5, audio_duration=1.0, offset=0.5), bins=3)
    assert result.synthetic is False
    assert [peak["level"] for peak in result.peaks] == pytest.approx([DEFAULT_WAVEFORM_LEVEL_FLOOR, -20, -20], abs=0.1)
    assert result.silence_regions == [{"start": 0.0, "end": 0.5}]


def test_short_final_window_is_not_artificially_quieter(tmp_path):
    result = audio_waveform(_fixture(tmp_path, "0.1", duration=1.3), bins=3)
    assert result.synthetic is False
    assert len(result.peaks) == 3
    assert [peak["level"] for peak in result.peaks] == pytest.approx([-20] * 3, abs=0.1)
    assert result.mean_level == pytest.approx(-20, abs=0.1)


def test_waveform_command_skips_video_and_caps_measurement_frames(tmp_path, monkeypatch):
    from kinocut import engine_audio_waveform as waveform

    path = _fixture(tmp_path, "0.1")
    original = waveform._analyze_waveform
    commands = []

    def inspect(cmd, bins):
        commands.append(cmd)
        return original(cmd, bins)

    monkeypatch.setattr(waveform, "_analyze_waveform", inspect)
    result = waveform.audio_waveform(path, bins=1000)
    assert result.synthetic is False
    assert len(result.peaks) <= 1000
    assert "-vn" in commands[0]
    assert commands[0][commands[0].index("-map") + 1] == "0:a:0"
    assert commands[0][commands[0].index("-frames:a") + 1] == "1000"


def test_opposite_phase_stereo_is_not_mistaken_for_silence(tmp_path):
    result = audio_waveform(_fixture(tmp_path, "0.1|-0.1"), bins=3)
    assert result.synthetic is False
    assert result.mean_level == pytest.approx(-20, abs=0.1)
    assert result.silence_regions == []
