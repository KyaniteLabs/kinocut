"""Audio operator adapters preserve strict input and existing engine behavior."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import threading

import pytest

from kinocut.audio_mix_inputs import parse_mix_sounds
from kinocut.defaults import DEFAULT_AUDIO_MIX_BITRATE, DEFAULT_DUCK_MUSIC_VOLUME, DEFAULT_DUCK_THRESHOLD
from kinocut.errors import MCPVideoError
from kinocut.models import EditResult


def _parse(*argv):
    from kinocut.cli.parser.audio_mix import add_parsers

    parser = argparse.ArgumentParser()
    add_parsers(parser.add_subparsers(dest="command"))
    return parser.parse_args(argv)


def test_mcp_mix_worker_does_not_block_event_loop(monkeypatch):
    from kinocut.server_tools_audio import video_mix_audio

    async def exercise():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        worker_threads = []

        def blocked_mix(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise RuntimeError("test worker release timed out")
            return EditResult(output_path="mixed.mp4", duration=1.0)

        monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", blocked_mix)
        task = asyncio.create_task(video_mix_audio("video.mp4", [{"path": "sound.wav"}]))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            heartbeat = asyncio.Event()
            loop.call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), timeout=1)
            assert not task.done()
            assert len(worker_threads) == 1
            assert worker_threads[0] != threading.get_ident()
        finally:
            release.set()
            result = await asyncio.wait_for(task, timeout=6)
        assert result["success"] is True

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "sounds",
    [
        "{",
        "null",
        "[]",
        '[{"path":"a.wav","start":true}]',
        '[{"path":"a.wav","volume":NaN}]',
        '[{"path":"a.wav","volume":Infinity}]',
        '[{"path":"a.wav","path":"b.wav"}]',
        [{"path": "a.wav", "fade_out": float("inf")}],
        [{"path": "a.wav", "start": -1}],
        [{"path": "a.wav", "volume": True}],
        [{"path": "a.wav", "volume": 5}],
        [{"path": "a.wav", "loop": True}],
        [{"path": "a.wav", "start": {"value": 1}}],
        [{"path": ""}],
        [{"path": "a.wav"}] * 65,
    ],
)
def test_adapter_rejects_invalid_tracks_before_engine(sounds, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid descriptions must not execute the engine")

    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", forbidden)
    from kinocut.server_tools_audio import video_mix_audio

    result = asyncio.run(video_mix_audio("video.mp4", sounds))
    assert result["success"] is False and result["error"]["code"] == "invalid_parameter"


def test_json_byte_ceiling_applies_to_native_and_unicode_inputs(monkeypatch):
    import kinocut.audio_mix_inputs as inputs

    track = [{"path": "雪.wav"}]
    text = json.dumps(track, ensure_ascii=False)
    monkeypatch.setattr(inputs, "MAX_AUDIO_MIX_JSON_BYTES", len(text.encode()) - 1)
    with pytest.raises(MCPVideoError, match="byte limit"):
        parse_mix_sounds(text)
    # Native and JSON representations share the ceiling, including separators.
    compact = json.dumps(track, ensure_ascii=False, separators=(",", ":"))
    monkeypatch.setattr(inputs, "MAX_AUDIO_MIX_JSON_BYTES", len(compact.encode()) - 1)
    with pytest.raises(MCPVideoError, match="byte limit"):
        parse_mix_sounds(track)


def test_mcp_defaults_and_custom_values_forward_once(monkeypatch):
    from kinocut.server_tools_audio import video_mix_audio

    calls = []

    def engine(*args, **kwargs):
        calls.append((args, kwargs))
        return EditResult(output_path="out.mp4", warnings=["listen"])

    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", engine)
    tracks = [{"path": "tick.wav", "start": 0.25, "volume": 0.4, "fade_out": 0.1}]
    result = asyncio.run(video_mix_audio("v.mp4", json.dumps(tracks)))
    assert calls.pop() == (("v.mp4", tracks, None), {"keep_source": True, "audio_bitrate": DEFAULT_AUDIO_MIX_BITRATE})
    assert result["warnings"] == ["listen"]
    asyncio.run(video_mix_audio("v.mp4", tracks, "o.mov", False, "192k"))
    assert calls == [(("v.mp4", tracks, "o.mov"), {"keep_source": False, "audio_bitrate": "192k"})]


@pytest.mark.parametrize(
    "sounds",
    [" " * 65_536 + '[{"path":"a.wav"}]', '[{"path":"a.wav","path":"b.wav"}]'],
    ids=["oversize-raw-json", "duplicate-track-keys"],
)
def test_actual_mcp_sdk_rejects_raw_json_before_lossy_preparse(sounds, monkeypatch):
    from kinocut.server_app import mcp
    import kinocut.server_tools_audio  # noqa: F401 - register actual MCP adapter.

    calls = []

    def engine(*args, **kwargs):
        calls.append(args)
        return EditResult(output_path="o.mp4")

    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", engine)
    result = asyncio.run(mcp.call_tool("video_mix_audio", {"input_path": "v.mp4", "sounds": sounds}))
    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload["success"] is False and payload["error"]["code"] == "invalid_parameter"
    assert calls == []


def test_actual_mcp_sdk_native_tracks_preserve_custom_values(monkeypatch):
    from kinocut.server_app import mcp
    import kinocut.server_tools_audio  # noqa: F401 - register actual MCP adapter.

    calls = []

    def engine(*args, **kwargs):
        calls.append((args, kwargs))
        return EditResult(output_path="o.mp4")

    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", engine)
    tracks = [{"path": "a.wav", "start": 0.2}]
    result = asyncio.run(
        mcp.call_tool(
            "video_mix_audio", {"input_path": "v.mp4", "sounds": tracks, "keep_source": False, "audio_bitrate": "192k"}
        )
    )
    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload["success"]
    assert calls == [(("v.mp4", tracks, None), {"keep_source": False, "audio_bitrate": "192k"})]


def test_client_source_output_aliases_still_forward_to_same_engine(monkeypatch):
    from kinocut import Client

    calls = []

    def engine(*args, **kwargs):
        calls.append((args, kwargs))
        return EditResult(output_path="o.mp4")

    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", engine)
    Client().mix_audio(input_path="v.mp4", tracks=[{"path": "a.wav"}], output_path="o.mp4", keep_source=False)
    assert calls == [
        (("v.mp4", [{"path": "a.wav"}], "o.mp4"), {"keep_source": False, "audio_bitrate": DEFAULT_AUDIO_MIX_BITRATE})
    ]


@pytest.mark.parametrize(
    "tracks",
    [
        [],
        [{"path": "a.wav", "start": True}],
        [{"path": "a.wav", "volume": float("nan")}],
        [{"path": "a.wav", "loop": True}],
        [{"path": "a.wav"}] * 65,
        '[{"path":"a.wav"}]',
    ],
)
def test_client_reuses_strict_native_track_validation_before_media_work(tracks, monkeypatch):
    from kinocut import Client

    def forbidden(*args, **kwargs):
        pytest.fail("invalid native tracks must fail before any media work")

    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", forbidden)
    with pytest.raises(MCPVideoError):
        Client().mix_audio(input_path="v.mp4", tracks=tracks)


def test_client_native_track_byte_ceiling_matches_operator_adapters(monkeypatch):
    from kinocut import Client
    import kinocut.audio_mix_inputs as inputs

    monkeypatch.setattr(inputs, "MAX_AUDIO_MIX_JSON_BYTES", 8)
    with pytest.raises(MCPVideoError, match="byte limit"):
        Client().mix_audio(input_path="v.mp4", tracks=[{"path": "a.wav"}])


def test_cli_defaults_aliases_and_all_duck_options_forward(monkeypatch, capsys):
    from kinocut.cli.handlers_audio_mix import handle_audio_mix_commands

    calls = []

    def engine(*args, **kwargs):
        calls.append((args, kwargs))
        return EditResult(output_path="o.mp4", operation="audio")

    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", engine)
    monkeypatch.setattr("kinocut.engine_audio_ops.duck_audio", engine)
    args = _parse("mix-audio", "v.mp4", "--tracks", '[{"path":"a.wav"}]')
    assert handle_audio_mix_commands(args, use_json=True)
    assert calls.pop() == (
        ("v.mp4", [{"path": "a.wav"}]),
        {"output_path": None, "keep_source": True, "audio_bitrate": DEFAULT_AUDIO_MIX_BITRATE},
    )
    assert json.loads(capsys.readouterr().out)["success"]
    defaults = _parse("duck-audio", "v.mp4", "m.wav")
    assert defaults.music_volume == DEFAULT_DUCK_MUSIC_VOLUME and defaults.threshold == DEFAULT_DUCK_THRESHOLD
    args = _parse(
        "duck-audio",
        "v.mp4",
        "m.wav",
        "--music-volume",
        "0.3",
        "--threshold",
        "0.1",
        "--ratio",
        "4",
        "--attack",
        "30",
        "--release",
        "450",
        "-o",
        "o.mp4",
    )
    assert handle_audio_mix_commands(args, use_json=True)
    assert calls == [
        (
            ("v.mp4", "m.wav"),
            {
                "output_path": "o.mp4",
                "music_volume": 0.3,
                "threshold": 0.1,
                "ratio": 4.0,
                "attack": 30.0,
                "release": 450.0,
            },
        )
    ]


def test_cli_policy_stays_plain_file_and_engine_validation_is_preserved(monkeypatch):
    from kinocut.cli.handlers_audio_mix import handle_audio_mix_commands

    with pytest.raises(SystemExit):
        _parse("mix-audio", "v.mp4", "--sounds", "[]", "--duration-policy", "extend")
    args = _parse("mix-audio", "v.mp4", "--sounds", '[{"path":"a.wav","volume":false}]')
    with pytest.raises(MCPVideoError, match="finite number"):
        handle_audio_mix_commands(args, use_json=True)
    args = _parse("duck-audio", "missing.mp4", "missing.wav", "--ratio", "nan")
    with pytest.raises(MCPVideoError):
        handle_audio_mix_commands(args, use_json=True)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires native FFmpeg")
def test_real_mcp_mix_stream_copies_picture_and_encodes_aac_once(tmp_path, monkeypatch):
    from kinocut import engine_audio_mix as engine
    from kinocut.server_tools_audio import video_mix_audio

    video, sound, output = (tmp_path / name for name in ("v.mp4", "sound.wav", "mixed.mp4"))

    def run(args):
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=True)

    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=white:s=64x64:r=10:d=1",
            "-c:v",
            "libx264",
            str(video),
        ]
    )
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2", str(sound)])
    commands, original = [], engine._run_ffmpeg

    def capture(args):
        commands.append(args)
        return original(args)

    monkeypatch.setattr(engine, "_run_ffmpeg", capture)
    result = asyncio.run(video_mix_audio(str(video), [{"path": str(sound), "start": 0.25}], str(output), False))
    assert result["success"] and result["duration"] == pytest.approx(1, abs=0.05)
    assert len(commands) == 1 and commands[0][commands[0].index("-c:a") + 1] == "aac"
    assert commands[0][commands[0].index("-c:v") + 1] == "copy"
    hashes = []
    for path in (video, output):
        raw = run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_packets",
                "-show_data_hash",
                "sha256",
                "-show_entries",
                "packet=data_hash",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
        hashes.append([packet["data_hash"] for packet in json.loads(raw)["packets"]])
    assert hashes[0] == hashes[1] and len(hashes[0]) == 10
