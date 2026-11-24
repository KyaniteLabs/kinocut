"""Real-media regressions for ``add_audio`` and ``duck_audio`` (roast audit C-07, C-13, C-40).

``adelay`` listed two channel delays and omitted ``all=1``, so channel 3+ of a
5.1 source was never delayed. Guardrails went to stderr via ``warnings.warn``
and never reached the agent. Extra audio tracks and subtitles were dropped
without a word, and mix mode summed tracks without saying so.
"""

from __future__ import annotations

import shutil
import subprocess
import wave

import numpy as np
import pytest

from kinocut.engine_audio_ops import add_audio, duck_audio
from kinocut.ffmpeg_helpers import _run_ffprobe_json

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")

SR = 44100


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, timeout=120)


def _make_video(path, duration: float = 2.0, *, audio_streams: int = 0) -> str:
    args = ["-f", "lavfi", "-i", f"color=c=blue:s=64x64:r=5:d={duration}"]
    for index in range(audio_streams):
        args += ["-f", "lavfi", "-i", f"sine=frequency={300 + 100 * index}:sample_rate={SR}:d={duration}"]
    args += ["-pix_fmt", "yuv420p", "-c:v", "libx264"]
    for index in range(audio_streams):
        args += ["-map", "0:v", "-map", f"{index + 1}:a"]
    args += ["-c:a", "aac"] if audio_streams else []
    args += [str(path)]
    _ffmpeg(args)
    return str(path)


def _make_click_wav(path, channels: int, *, seconds: float = 1.0, click_at: float = 0.01) -> str:
    samples = np.zeros((int(seconds * SR), channels))
    click = np.zeros(int(seconds * SR))
    click[int(click_at * SR) : int(click_at * SR) + 40] = 0.9
    samples[:] = click[:, None]
    pcm = (samples * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SR)
        wav_file.writeframes(pcm)
    return str(path)


def _decode(path: str) -> tuple[int, int, np.ndarray]:
    probe = _run_ffprobe_json(path)
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    channels = int(audio["channels"])
    rate = int(audio["sample_rate"])
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout
    return rate, channels, np.frombuffer(pcm, dtype=np.int16).astype(np.float64).reshape(-1, channels) / 32768.0


def _onset_seconds(channel: np.ndarray, threshold: float = 0.3) -> float:
    return float(np.argmax(np.abs(channel) > threshold) / SR)


def test_add_audio_delays_every_channel_of_a_surround_track(tmp_path):
    video = _make_video(tmp_path / "in.mp4")
    click = _make_click_wav(tmp_path / "click.wav", channels=6)

    out = add_audio(video, click, start_time=0.5, output_path=str(tmp_path / "out.mp4")).output_path

    _, channels, decoded = _decode(out)
    assert channels == 6
    onsets = [_onset_seconds(decoded[:, index]) for index in range(channels)]
    # Channel 6 used to stay at ~0.01 s while the first two moved to ~0.5 s.
    assert all(abs(onset - 0.51) < 0.05 for onset in onsets), onsets


def test_add_audio_guardrails_reach_the_result_not_stderr(tmp_path):
    import warnings

    video = _make_video(tmp_path / "in.mp4", audio_streams=1)
    click = _make_click_wav(tmp_path / "click.wav", channels=1)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = add_audio(video, click, volume=1.5, mix=True, output_path=str(tmp_path / "out.mp4"))

    assert any("volume=1.5 > 1.0" in warning for warning in result.warnings)
    assert any("summed without loudness normalization" in warning for warning in result.warnings)
    assert not any("AUDIO GUARDRAIL" in str(item.message) for item in caught)


def test_add_audio_and_duck_audio_name_the_streams_they_drop(tmp_path):
    video = _make_video(tmp_path / "in.mp4", audio_streams=2)
    click = _make_click_wav(tmp_path / "click.wav", channels=1)

    added = add_audio(video, click, mix=True, output_path=str(tmp_path / "added.mp4"))
    ducked = duck_audio(video, click, output_path=str(tmp_path / "ducked.mp4"))

    for result in (added, ducked):
        assert any("1 additional audio track" in warning for warning in result.warnings), result.warnings
        assert any("only the first is kept" in warning for warning in result.warnings)


def test_clean_stereo_sources_add_no_stream_warnings(tmp_path):
    video = _make_video(tmp_path / "in.mp4", audio_streams=1)
    click = _make_click_wav(tmp_path / "click.wav", channels=1)

    result = add_audio(video, click, mix=True, output_path=str(tmp_path / "out.mp4"))

    assert not any("not carried into the output" in warning for warning in result.warnings)
