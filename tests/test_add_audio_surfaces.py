"""Surface parity + ai_video receipt evidence for add_audio duration_policy (Plan 01 Task 2).

MCP ``video_add_audio``, ``Client.add_audio``, and the CLI ``add-audio
--duration-policy`` flag must all reach the engine with the chosen policy;
omitting it preserves the safe ``keep_video`` default; an invalid value is a
clean validation error; and the MCP result carries an additive ``ai_video``
section recording the ``duration_policy`` and any preservation warning.
"""

from __future__ import annotations

import argparse

import pytest

from mcp_video.models import EditResult


def _fake_engine(captured: dict):
    def _engine(*args, **kwargs):
        captured.update(kwargs)
        warns = []
        if kwargs.get("duration_policy") == "shortest":
            warns = ["duration_policy='shortest' may shorten the output below the video duration."]
        return EditResult(output_path="out.mp4", operation="add_audio", warnings=warns)

    return _engine


# ---- MCP surface ----------------------------------------------------------


def _mcp_setup(monkeypatch, tmp_path):
    from mcp_video import server_tools_basic

    video, audio = tmp_path / "v.mp4", tmp_path / "a.wav"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    monkeypatch.setattr(server_tools_basic, "_validate_input_path", lambda p: p)
    return server_tools_basic, str(video), str(audio)


def test_mcp_add_audio_passes_duration_policy(monkeypatch, tmp_path):
    stb, v, a = _mcp_setup(monkeypatch, tmp_path)
    captured: dict = {}
    monkeypatch.setattr(stb, "add_audio", _fake_engine(captured))
    stb.video_add_audio(v, a, duration_policy="pad_audio", output_path=str(tmp_path / "o.mp4"))
    assert captured.get("duration_policy") == "pad_audio"


def test_mcp_add_audio_defaults_to_keep_video(monkeypatch, tmp_path):
    stb, v, a = _mcp_setup(monkeypatch, tmp_path)
    captured: dict = {}
    monkeypatch.setattr(stb, "add_audio", _fake_engine(captured))
    stb.video_add_audio(v, a, output_path=str(tmp_path / "o.mp4"))  # policy omitted
    assert captured.get("duration_policy") == "keep_video"


def test_mcp_add_audio_invalid_policy_is_validation_error(monkeypatch, tmp_path):
    stb, v, a = _mcp_setup(monkeypatch, tmp_path)
    result = stb.video_add_audio(v, a, duration_policy="bogus", output_path=str(tmp_path / "o.mp4"))
    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"  # stable error type
    assert result["error"]["code"] == "invalid_duration_policy"  # stable error code
    assert "bogus" not in str(result)  # hostile value not echoed


def test_mcp_add_audio_receipt_records_policy_and_warning(monkeypatch, tmp_path):
    stb, v, a = _mcp_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(stb, "add_audio", _fake_engine({}))
    result = stb.video_add_audio(v, a, duration_policy="shortest", output_path=str(tmp_path / "o.mp4"))
    assert result["ai_video"]["duration_policy"] == "shortest"
    assert result["ai_video"]["warnings"]  # a preservation warning code is recorded


def test_mcp_add_audio_receipt_keep_video_has_no_warning(monkeypatch, tmp_path):
    stb, v, a = _mcp_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(stb, "add_audio", _fake_engine({}))
    result = stb.video_add_audio(v, a, output_path=str(tmp_path / "o.mp4"))
    assert result["ai_video"]["duration_policy"] == "keep_video"
    assert result["ai_video"]["warnings"] == []


# ---- Python client surface ------------------------------------------------


def test_client_add_audio_passes_duration_policy(monkeypatch):
    from mcp_video import Client
    from mcp_video.client import media

    captured: dict = {}
    monkeypatch.setattr(media, "_add_audio", _fake_engine(captured))
    Client().add_audio("v.mp4", "a.wav", duration_policy="loop_audio")
    assert captured.get("duration_policy") == "loop_audio"


def test_client_add_audio_defaults_to_keep_video(monkeypatch):
    from mcp_video import Client
    from mcp_video.client import media

    captured: dict = {}
    monkeypatch.setattr(media, "_add_audio", _fake_engine(captured))
    Client().add_audio("v.mp4", "a.wav")
    assert captured.get("duration_policy") == "keep_video"


# ---- CLI surface ----------------------------------------------------------


def _add_audio_args(*extra):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    from mcp_video.cli.parser import effects

    effects.add_parsers(sub)
    return parser.parse_args(["add-audio", "v.mp4", "a.wav", *extra])


def test_cli_parser_accepts_duration_policy_flag():
    args = _add_audio_args("--duration-policy", "trim_audio")
    assert args.duration_policy == "trim_audio"


def test_cli_parser_defaults_to_keep_video():
    args = _add_audio_args()
    assert args.duration_policy == "keep_video"


def test_cli_parser_rejects_invalid_duration_policy():
    with pytest.raises(SystemExit):  # argparse validation rejection
        _add_audio_args("--duration-policy", "bogus")


def test_cli_duration_policy_error_never_echoes_hostile_value(capsys):
    hostile = "/Users/victim/../../etc/passwd"
    with pytest.raises(SystemExit):
        _add_audio_args("--duration-policy", hostile)
    err = capsys.readouterr().err
    assert hostile not in err  # raw home/traversal value must not leak to stderr
    assert "keep_video" in err  # bounded, closed-value message is shown instead


class _FakeCommandRunner:
    """Records registrations and dispatches the command under test."""

    def __init__(self, args, use_json):
        self.args, self.use_json, self.handlers = args, use_json, {}

    def register(self, command, handler):
        self.handlers[command] = handler

    def dispatch(self):
        handler = self.handlers.get(self.args.command)
        if handler:
            handler(self.args, self.use_json)
            return True
        return False


def test_cli_add_audio_dispatch_forwards_duration_policy_to_engine(monkeypatch):
    # Behavioral proof: the parsed --duration-policy value actually reaches the
    # engine call, not merely appearing as a string in the handler source.
    from types import SimpleNamespace

    from mcp_video.cli import handlers_core, runner

    captured: dict = {}

    def _fake_resolve(engine_fn):
        def _engine(*a, **k):
            captured["engine_fn"] = engine_fn
            captured.update(k)
            return "ok"

        return _engine

    monkeypatch.setattr(runner, "_resolve_engine", _fake_resolve)
    monkeypatch.setattr(runner, "_with_spinner", lambda _msg, fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(runner, "output_json", lambda _x: None)
    monkeypatch.setattr(handlers_core, "CommandRunner", _FakeCommandRunner)

    args = SimpleNamespace(
        command="add-audio",
        video="v.mp4",
        audio="a.wav",
        volume=1.0,
        fade_in=0.0,
        fade_out=0.0,
        mix=False,
        start_time=None,
        output="o.mp4",
        duration_policy="pad_audio",
    )
    handlers_core.handle_initial_command(args, use_json=True)
    assert captured["engine_fn"] == "mcp_video.engine:add_audio"
    assert captured["duration_policy"] == "pad_audio"
