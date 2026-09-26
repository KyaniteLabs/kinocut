"""mix_audio: many sounds layered in one pass, one AAC encode (no generation loss)."""

from __future__ import annotations

import re
import subprocess

import pytest

from kinocut import Client
from kinocut.engine_audio_mix import _build_mix_args, mix_audio
from kinocut.errors import MCPVideoError

pytestmark = pytest.mark.skipif(
    subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=30).returncode != 0, reason="needs ffmpeg"
)


def _ffmpeg(*args: str) -> str:
    return subprocess.run(["ffmpeg", "-hide_banner", "-y", *args], capture_output=True, text=True, timeout=120).stderr


@pytest.fixture
def media(tmp_path):
    # A quiet, bright drone (two low sawtooths, like a music bed) under a grey picture, encoded once like any rush.
    video = tmp_path / "bed.mp4"
    drone = r"aevalsrc='0.02*(2*mod(110*t\,1)-1)+0.015*(2*mod(164.8*t\,1)-1)':s=48000:d=4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=gray:s=160x90:r=25",
        "-f",
        "lavfi",
        "-i",
        drone,
        "-t",
        "4",
        "-ac",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(video),
    )
    tick = tmp_path / "tick.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "0.05", str(tick))
    return video, tick


def _rms(path, start: float, length: float, highpass: bool = False) -> float:
    chain = "highpass=f=5000,highpass=f=5000," if highpass else ""
    report = _ffmpeg(
        "-ss",
        str(start),
        "-t",
        str(length),
        "-i",
        str(path),
        "-af",
        f"{chain}astats=measure_perchannel=none",
        "-f",
        "null",
        "-",
    )
    level = re.search(r"RMS level dB: (-inf|-?[\d.]+)", report).group(1)
    return -200.0 if level == "-inf" else float(level)


def test_one_encode_adds_less_hiss_than_one_encode_per_sound(media, tmp_path):
    video, tick = media
    ticks = [{"path": str(tick), "start": 3.0 + k * 0.05, "volume": 0.5} for k in range(10)]
    once = mix_audio(str(video), ticks, str(tmp_path / "once.mp4"))
    current = str(video)
    for k, track in enumerate(ticks):  # the pattern mix_audio replaces
        current = (
            Client()
            .add_audio(
                current,
                track["path"],
                volume=0.5,
                mix=True,
                start_time=track["start"],
                output=str(tmp_path / f"step-{k}.mp4"),
            )
            .output_path
        )
    # Before the ticks only the drone plays: its highs grow with each lossy generation (about 7 dB after ten).
    once_highs, stacked_highs = _rms(once.output_path, 0.5, 2, True), _rms(current, 0.5, 2, True)
    assert once_highs < stacked_highs - 4, (once_highs, stacked_highs)


def test_sounds_land_on_the_timeline_at_unity_and_the_video_length_is_kept(media, tmp_path):
    video, tick = media
    out = mix_audio(
        str(video), [{"path": str(tick), "start": 1.0, "volume": 2.0}], str(tmp_path / "out.mp4"), keep_source=False
    )
    assert abs(out.duration - 4.0) < 0.1
    assert _rms(out.output_path, 0.2, 0.6) < -80, "silent before the sound"
    assert _rms(out.output_path, 1.005, 0.04) > -20, "sound at 1 s, doubled"


@pytest.mark.parametrize(
    "tracks",
    [
        [],
        [{"path": 3}],
        [{"path": "x", "volume": 9}],
        [{"path": "x", "start": float("nan")}],
        [{"path": "x", "gain": 1}],
    ],
)
def test_bad_tracks_are_refused(media, tmp_path, tracks):
    video, tick = media
    for track in tracks:
        if track.get("path") == "x":
            track["path"] = str(tick)
    with pytest.raises(MCPVideoError):
        mix_audio(str(video), tracks, str(tmp_path / "out.mp4"))


def test_filter_values_are_escaped():
    args = _build_mix_args(
        "v.mp4",
        [{"path": "a.wav", "start": 1.5, "volume": 0.5, "fade_in": 0.1, "fade_out": 0.2}],
        True,
        3.0,
        "o.mp4",
        "256k",
    )
    graph = args[args.index("-filter_complex") + 1]
    assert "adelay=1500|1500" in graph and "amix=inputs=2:duration=longest:normalize=0" in graph
    assert args[args.index("-c:v") + 1] == "copy" and args[args.index("-b:a") + 1] == "256k"
