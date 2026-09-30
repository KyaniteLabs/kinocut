"""mix_audio: many sounds layered in one pass, one AAC encode (no generation loss)."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from kinocut import Client
from kinocut.engine_audio_mix import _build_mix_args, mix_audio
from kinocut.errors import MCPVideoError

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ffmpeg(*args: str) -> str:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *args], capture_output=True, text=True, timeout=120, check=True
    ).stderr


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
        [{"path": "a.wav", "start": 1.5, "volume": 0.5, "fade_in": 0.1, "fade_out": 0.2, "duration": 1.0}],
        True,
        3.0,
        "o.mp4",
        "256k",
    )
    graph = args[args.index("-filter_complex") + 1]
    assert "adelay=72000S:all=1" in graph and "amix=inputs=2:duration=longest:normalize=0" in graph
    assert args[args.index("-c:v") + 1] == "copy" and args[args.index("-b:a") + 1] == "256k"


@pytest.mark.parametrize("rate", ["0k", "513k", "²k", "256", "999999999999999k", "-1k", 256])
def test_bitrate_validation_is_structured(media, tmp_path, rate):
    video, tick = media
    with pytest.raises(MCPVideoError) as exc:
        mix_audio(str(video), [{"path": str(tick)}], str(tmp_path / "invalid.mp4"), audio_bitrate=rate)
    assert exc.value.error_type == "validation_error"


def test_one_ffmpeg_encode_and_one_probe_per_unique_track(media, tmp_path, monkeypatch):
    from kinocut import engine_audio_mix as module

    video, tick = media
    calls, probes = [], []
    real_run, real_probe = module._run_ffmpeg, module.probe_audio_input

    def run(args):
        calls.append(args)
        return real_run(args)

    def probe(path):
        probes.append(path)
        return real_probe(path)

    monkeypatch.setattr(module, "_run_ffmpeg", run)
    monkeypatch.setattr(module, "probe_audio_input", probe)
    result = Client().mix_audio(
        str(video),
        [{"path": str(tick), "start": start} for start in (1.0, 2.0, 3.0)],
        output=str(tmp_path / "single.mp4"),
    )
    assert len(calls) == 1 and len(probes) == 1
    assert calls[0].count("-c:a") == 1 and calls[0][calls[0].index("-c:v") + 1] == "copy"
    assert result.operation == "mix_audio" and result.warnings


@pytest.mark.parametrize("stage", ["encode", "postflight"])
def test_failure_preserves_destination_and_cleans_staging(media, tmp_path, monkeypatch, stage):
    from kinocut import engine_audio_mix as module
    from kinocut.errors import ProcessingError

    video, tick = media
    output = tmp_path / "existing.mp4"
    output.write_bytes(video.read_bytes())
    original = output.read_bytes()

    def fail(*args, **kwargs):
        raise ProcessingError("forced failure", returncode=1, stderr="injected failure")

    monkeypatch.setattr(module, "_run_ffmpeg" if stage == "encode" else "_build_edit_result", fail)
    with pytest.raises(ProcessingError):
        mix_audio(str(video), [{"path": str(tick)}], str(output))
    assert output.read_bytes() == original
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_fade_out_is_streaming_and_applies_to_clipped_track(media, tmp_path):
    video, _ = media
    tone = tmp_path / "long.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "8", str(tone))
    result = mix_audio(
        str(video), [{"path": str(tone), "start": 1.0, "fade_out": 1.0}], str(tmp_path / "fade.mp4"), keep_source=False
    )
    assert _rms(result.output_path, 3.8, 0.15) < _rms(result.output_path, 2.0, 0.3) - 12
    args = _build_mix_args(
        str(video),
        [{"path": str(tone), "duration": 3.0, "start": 1.0, "volume": 1.0, "fade_in": 0.0, "fade_out": 1.0}],
        False,
        4.0,
        "o.mp4",
        "256k",
    )
    graph = args[args.index("-filter_complex") + 1]
    assert "areverse" not in graph and "afade=t=out:st=2.0:d=1.0" in graph


@pytest.mark.parametrize("source", ["video_10s", "video_10s_silent", "video_multistream"])
def test_mix_loop_audio_fills_added_track_and_remains_bounded(tmp_path, source):
    # Standalone media helpers avoid importing fixture modules as packages.
    video = tmp_path / "loop_source.mp4"
    args = ["-f", "lavfi", "-i", "color=c=gray:s=160x90:r=25:d=4"]
    if source != "video_10s_silent":
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a"]
        if source == "video_multistream":
            args += ["-map", "1:a"]
    _ffmpeg(*args, "-t", "4", "-pix_fmt", "yuv420p", str(video))
    audio = tmp_path / "loop.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=0.5", str(audio))
    result = Client().add_audio(
        str(video),
        str(audio),
        mix=True,
        duration_policy="loop_audio",
        start_time=0.25,
        output=str(tmp_path / "loop.mp4"),
    )
    assert abs(result.duration - 4.0) < 0.1
    assert _rms(result.output_path, 3.0, 0.5) > -30


def test_client_duck_audio_works_without_store_and_ducks_on_voice(tmp_path):
    video, music = tmp_path / "voice.mp4", tmp_path / "music.wav"
    voice = "aevalsrc=0.4*sin(2*PI*220*t)*between(t\\,1\\,2):s=48000:d=4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=gray:s=160x90:r=25:d=4",
        "-f",
        "lavfi",
        "-i",
        voice,
        "-t",
        "4",
        "-pix_fmt",
        "yuv420p",
        str(video),
    )
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=6000:sample_rate=48000:d=4", str(music))
    result = Client().duck_audio(str(video), str(music), output=str(tmp_path / "ducked.mp4"))
    assert result.operation == "duck_audio" and abs(result.duration - 4.0) < 0.1
    assert _rms(result.output_path, 1.4, 0.4, True) < _rms(result.output_path, 0.4, 0.4, True) - 8


def test_audio_input_hardlink_cannot_be_output(media, tmp_path):
    import os

    video, tick = media
    output = tmp_path / "alias.mp4"
    os.link(tick, output)
    original = tick.read_bytes()
    with pytest.raises(MCPVideoError, match="aliases"):
        mix_audio(str(video), [{"path": str(tick)}], str(output))
    assert tick.read_bytes() == original


def test_silent_picture_can_receive_one_pass_mix(sample_video_no_audio, sample_audio, tmp_path):
    result = Client().mix_audio(sample_video_no_audio, [{"path": sample_audio}], str(tmp_path / "silent.mov"))
    assert result.success and result.format == "mov"


@pytest.mark.parametrize("keep", [0, 1, "false", None])
def test_keep_source_is_strict_boolean(media, tmp_path, keep):
    video, tick = media
    with pytest.raises(MCPVideoError, match="boolean"):
        mix_audio(str(video), [{"path": str(tick)}], str(tmp_path / "bool.mp4"), keep_source=keep)
