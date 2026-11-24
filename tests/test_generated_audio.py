"""Real-media regressions for ``video_add_generated_audio``.

The tool used to fail on every default call (the temporary WAV was created
before the writer refused to overwrite it), discard the generated track whenever
the video already had audio (no explicit ``-map``), and truncate the picture to
the generated track's length (``-shortest``). Every test renders with real FFmpeg
and asserts on decoded audio content, not on the command line.
"""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from kinocut.audio_engine import add_generated_audio
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _get_video_duration, _run_ffprobe_json

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")

_SAMPLE_RATE = 44100


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, timeout=120)


def _make_video(path, duration: float, *, tone_hz: float | None = None) -> str:
    """A tiny video, optionally carrying a sine tone as its own audio track."""
    args = ["-f", "lavfi", "-i", f"color=c=blue:s=64x64:r=5:d={duration}"]
    if tone_hz is not None:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone_hz}:sample_rate={_SAMPLE_RATE}:d={duration}"]
    args += ["-pix_fmt", "yuv420p", "-c:v", "libx264"]
    if tone_hz is not None:
        args += ["-c:a", "aac", "-shortest"]
    args += [str(path)]
    _ffmpeg(args)
    return str(path)


def _strong_frequencies(path: str, *, within_db: float = 20.0) -> list[float]:
    """Frequencies whose magnitude is within ``within_db`` of the strongest one."""
    pcm = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(_SAMPLE_RATE),
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768.0
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    freqs = np.fft.rfftfreq(len(samples), d=1 / _SAMPLE_RATE)
    strong = np.where(spectrum >= spectrum.max() * 10 ** (-within_db / 20))[0]
    bands: list[list[int]] = []
    for index in strong:
        if bands and index == bands[-1][-1] + 1:
            bands[-1].append(index)
        else:
            bands.append([int(index)])
    return [float(freqs[max(band, key=spectrum.__getitem__)]) for band in bands]


def _near(frequencies: list[float], target: float, tolerance: float = 15.0) -> bool:
    return any(abs(frequency - target) <= tolerance for frequency in frequencies)


def test_generated_audio_replaces_silent_video_track(tmp_path):
    video = _make_video(tmp_path / "in.mp4", 2.0)
    output = str(tmp_path / "out.mp4")

    add_generated_audio(video, {"events": [{"type": "tone", "at": 0, "duration": 2, "freq": 440}]}, output)

    frequencies = _strong_frequencies(output)
    assert _near(frequencies, 440), frequencies
    assert len(frequencies) == 1, frequencies


def test_generated_audio_is_kept_when_video_already_has_audio(tmp_path):
    video = _make_video(tmp_path / "in.mp4", 2.0, tone_hz=300)
    output = str(tmp_path / "out.mp4")

    add_generated_audio(video, {"events": [{"type": "tone", "at": 0, "duration": 2, "freq": 440}]}, output)

    frequencies = _strong_frequencies(output)
    assert _near(frequencies, 300), frequencies
    assert _near(frequencies, 440), frequencies


def test_generated_audio_never_shortens_the_picture(tmp_path):
    video = _make_video(tmp_path / "in.mp4", 3.0)
    output = str(tmp_path / "out.mp4")

    add_generated_audio(video, {"events": [{"type": "tone", "at": 0, "duration": 0.5, "freq": 440}]}, output)

    assert _get_video_duration(output) == pytest.approx(3.0, abs=0.3)
    assert any(stream.get("codec_type") == "audio" for stream in _run_ffprobe_json(output)["streams"])


def test_generated_audio_drone_is_laid_under_the_video(tmp_path):
    video = _make_video(tmp_path / "in.mp4", 2.0)
    output = str(tmp_path / "out.mp4")

    add_generated_audio(video, {"drone": {"frequency": 110, "volume": 0.5}}, output)

    frequencies = _strong_frequencies(output)
    assert _near(frequencies, 110), frequencies


def test_generated_audio_output_respects_overwrite_consent(tmp_path):
    video = _make_video(tmp_path / "in.mp4", 1.0)
    output = str(tmp_path / "out.mp4")
    config = {"events": [{"type": "tone", "at": 0, "duration": 1, "freq": 440}]}

    add_generated_audio(video, config, output)
    with pytest.raises(MCPVideoError) as refused:
        add_generated_audio(video, config, output)
    assert refused.value.code == "output_exists"


def test_generated_audio_overwrites_with_consent(tmp_path, overwrite_consent):
    video = _make_video(tmp_path / "in.mp4", 1.0)
    output = str(tmp_path / "out.mp4")
    config = {"events": [{"type": "tone", "at": 0, "duration": 1, "freq": 440}]}

    add_generated_audio(video, config, output)
    add_generated_audio(video, config, output)

    assert _near(_strong_frequencies(output), 440)


def test_generated_audio_tool_warns_when_mixing_under_source_audio(tmp_path):
    from kinocut.server_tools_audio import video_add_generated_audio

    video = _make_video(tmp_path / "in.mp4", 1.0, tone_hz=300)
    config = {"events": [{"type": "tone", "at": 0, "duration": 1, "freq": 440}]}

    mixed = video_add_generated_audio(video, config, str(tmp_path / "mixed.mp4"))
    assert mixed["success"] is True, mixed
    assert any("mixed under" in warning for warning in mixed["warnings"])

    silent = _make_video(tmp_path / "silent.mp4", 1.0)
    replaced = video_add_generated_audio(silent, config, str(tmp_path / "replaced.mp4"))
    assert replaced["success"] is True, replaced
    assert not replaced.get("warnings")
