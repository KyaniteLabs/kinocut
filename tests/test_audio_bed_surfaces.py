"""Public MCP, Python, and CLI parity for the audio-bed facade."""

from __future__ import annotations

import argparse
import asyncio
import inspect

APPROVED = (
    "loop",
    "loop_crossfade",
    "fade_in",
    "fade_out",
    "target_lufs",
    "duck_threshold",
    "duck_ratio",
    "duck_attack",
    "duck_release",
    "music_volume",
    "save_receipt",
)
FORBIDDEN = {"duration_policy", "duration_tolerance", "project_dir", "authorization_decision_ids"}
CUSTOM = dict(
    loop=False,
    loop_crossfade=0.5,
    fade_in=0.25,
    fade_out=1.5,
    target_lufs=-18.0,
    duck_threshold=0.05,
    duck_ratio=4.0,
    duck_attack=30.0,
    duck_release=400.0,
    music_volume=0.7,
    save_receipt="r.json",
)


def _fake(captured):
    def run(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return {"output_path": args[2], "receipt": {"operation": "audio_bed"}}

    return run


def _parse(*extra):
    from kinocut.cli.parser.audio import add_parsers

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    add_parsers(sub)
    return parser.parse_args(["audio-bed", "v.mp4", "m.wav", "-o", "o.mp4", *extra]), sub


def test_public_signatures_and_registration():
    from kinocut import Client
    from kinocut.server import mcp
    from kinocut.server_tools_audio import video_audio_bed

    for fn in (video_audio_bed, Client.audio_bed):
        names = set(inspect.signature(fn).parameters) - {"self"}
        assert {"voice_source", "music_path", "output_path", *APPROVED} == names
        assert not names & FORBIDDEN
    assert "video_audio_bed" in {tool.name for tool in asyncio.run(mcp.list_tools())}


def test_mcp_and_client_forward_custom_values(monkeypatch):
    from kinocut import Client
    from kinocut.server_tools_audio import video_audio_bed

    for call in (video_audio_bed, Client().audio_bed):
        captured = {}
        monkeypatch.setattr("kinocut.engine_audio_bed.audio_bed", _fake(captured))
        monkeypatch.setattr("kinocut.client.media._audio_bed", _fake(captured))
        result = call("v.mp4", "m.wav", "o.mp4", **CUSTOM)
        assert captured["args"] == ("v.mp4", "m.wav", "o.mp4")
        assert {name: captured[name] for name in APPROVED} == CUSTOM
        assert result["receipt"]["operation"] == "audio_bed"


def test_cli_parser_defaults_and_forbidden_flags():
    args, sub = _parse()
    assert (args.loop, args.loop_crossfade, args.fade_out, args.target_lufs) == (True, 1.5, 2.2, -16.0)
    flags = {flag for action in sub.choices["audio-bed"]._actions for flag in action.option_strings}
    assert not {"--duration-policy", "--duration-tolerance", "--authorization-decision-id"} & flags


def test_cli_handler_forwards_all_values(monkeypatch):
    from kinocut.cli import handlers_audio

    argv = [
        item
        for pair in (("--" + key.replace("_", "-"), str(value)) for key, value in CUSTOM.items() if key not in {"loop"})
        for item in pair
    ]
    args, _ = _parse("--no-loop", *argv)
    args.command = "audio-bed"
    captured = {}

    class Runner:
        def __init__(self, parsed, use_json):
            self.parsed, self.use_json = parsed, use_json

        def register(self, command, handler):
            if command == "audio-bed":
                handler(self.parsed, self.use_json)

        def dispatch(self):
            return True

    monkeypatch.setattr(handlers_audio, "CommandRunner", Runner)
    monkeypatch.setattr(handlers_audio, "_with_spinner", lambda _m, fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(handlers_audio, "_out", lambda *a, **k: None)
    monkeypatch.setattr("kinocut.engine_audio_bed.audio_bed", _fake(captured))
    assert handlers_audio.handle_audio_commands(args, use_json=True)
    assert {name: captured[name] for name in APPROVED} == CUSTOM


def test_mcp_missing_inputs_fail_closed():
    from kinocut.server_tools_audio import video_audio_bed

    result = video_audio_bed("missing-voice.mp4", "missing-bed.wav", "out.mp4")
    assert result["success"] is False
    assert result["error"]["code"]
