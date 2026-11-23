"""Real-media regressions for the governed audio bed (roast audit C-04, C-05, C-31).

``loudnorm`` without a trailing resample shipped a 96 kHz AAC file whatever the
source rate was. Duration verification ran *after* the atomic publish and then
deleted the output on failure, destroying whatever consented file it had just
replaced. ``loop=True`` with a zero crossfade quietly produced a short bed.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

import kinocut.engine_audio_bed as engine
from kinocut.engine_audio_bed import _audio_sample_rate, audio_bed
from kinocut.errors import ProcessingError

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")


def _short_wav(path, seconds: float) -> str:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:duration={seconds}",
            str(path),
        ],
        check=True,
        timeout=120,
    )
    return str(path)


@pytest.mark.parametrize("voice", ["sample_video", "sample_video_no_audio"])
def test_audio_bed_output_keeps_the_source_sample_rate(voice, sample_audio, tmp_path, request):
    voice_path = request.getfixturevalue(voice)
    out = str(tmp_path / "bed.mp4")
    audio_bed(voice_path, sample_audio, out)
    rate = _audio_sample_rate(out)
    assert rate is not None and rate != 96000
    expected = _audio_sample_rate(voice_path) or _audio_sample_rate(sample_audio)
    assert rate == expected


def test_failed_verification_leaves_the_previous_output_untouched(
    sample_video, sample_audio, tmp_path, monkeypatch, overwrite_consent
):
    out = tmp_path / "bed.mp4"
    out.write_bytes(b"previous deliverable")

    def failing_verify(path, target, tolerance):
        raise ProcessingError("audio_bed duration verification", 0, "tampered: 0.1 vs 3.0")

    monkeypatch.setattr(engine, "_verify_output_duration", failing_verify)
    with pytest.raises(ProcessingError):
        audio_bed(sample_video, sample_audio, str(out))
    # The old code published first and then unlinked the output on failure.
    assert out.read_bytes() == b"previous deliverable"
    assert not list(tmp_path.glob(".audio-bed.*"))


def test_zero_crossfade_with_a_short_bed_is_reported(sample_video, tmp_path):
    bed = _short_wav(tmp_path / "bed.wav", 1.0)
    result = audio_bed(sample_video, bed, str(tmp_path / "bed.mp4"), loop=True, loop_crossfade=0.0)
    assert "bed_shorter_than_voice_crossfade_zero" in result["warnings"]
    assert "bed_shorter_than_voice_loop_disabled" not in result["warnings"]


def test_disabled_loop_with_a_short_bed_keeps_its_warning(sample_video, tmp_path):
    bed = _short_wav(tmp_path / "bed.wav", 1.0)
    result = audio_bed(sample_video, bed, str(tmp_path / "bed.mp4"), loop=False)
    assert "bed_shorter_than_voice_loop_disabled" in result["warnings"]
    assert "bed_shorter_than_voice_crossfade_zero" not in result["warnings"]
