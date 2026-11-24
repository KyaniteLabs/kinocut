"""Exercise Hyperframes IO and public option parity without a Node installation."""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_type_hints

import pytest

from kinocut import hyperframes_engine as engine
from kinocut import server_tools_hyperframes as tools
from kinocut.cli.handlers_hyperframes import handle_hyperframes_commands
from kinocut.cli.parser import build_parser
from kinocut.client import Client
from kinocut.errors import MCPVideoError
from kinocut.hyperframes.runner import current_runner, use_runner


@dataclass
class FakePreview:
    pid: int = 42
    exit_code: int | None = None
    stopped: bool = False

    def poll(self):
        return self.exit_code

    def stop(self):
        self.stopped = True
        self.exit_code = -15


@dataclass
class FakeRunner:
    commands: list[list[str]] = field(default_factory=list)
    environments: list[dict[str, str]] = field(default_factory=list)
    probes: list[tuple[int, Path, int]] = field(default_factory=list)
    child: FakePreview = field(default_factory=FakePreview)
    ready: bool = True

    def which(self, command):
        return f"/fake/bin/{command}" if command in {"node", "hyperframes"} else None

    def run(self, command, *, cwd, timeout, env):
        self.commands.append(command)
        self.environments.append(env)
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "0.8.140", "")
        if command[1] == "render":
            Path(command[command.index("--output") + 1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0, '{"result": "ok"}', "")

    def start_preview(self, command, *, cwd, env):
        self.commands.append(command)
        self.environments.append(env)
        return self.child

    def preview_ready(self, port, project, pid):
        self.probes.append((port, project, pid))
        return self.ready


@pytest.fixture
def project(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    return tmp_path


@pytest.fixture
def fake_runner(monkeypatch):
    monkeypatch.delenv(engine.HYPERFRAMES_COMMAND_ENV, raising=False)
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", "false")
    fake = FakeRunner()
    with use_runner(fake):
        yield fake


def _cli_result(capsys, command, *args):
    parsed = build_parser().parse_args(["--format", "json", command, *args])
    if not handle_hyperframes_commands(parsed, use_json=True):
        pytest.fail(f"No handler for {command}")
    return json.loads(capsys.readouterr().out)


def test_runner_override_is_scoped(project):
    original = current_runner()
    outer, inner = FakeRunner(), FakeRunner()
    with use_runner(outer):
        with use_runner(inner):
            assert engine.info(str(project)).data == {"result": "ok"}
        assert current_runner() is outer
    assert current_runner() is original
    assert inner.commands[0][:2] == ["/fake/bin/hyperframes", "info"]
    assert outer.commands == []


def test_preview_uses_adapter_for_launch_readiness_and_cleanup(project, fake_runner, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("HYPERFRAMES_PREVIEW_HOST", "invalid-host")
    port = 53139
    try:
        result = engine.preview(str(project), port=port)
        assert result.pid == fake_runner.child.pid
        assert fake_runner.commands[0][1:] == ["--version"]
        assert fake_runner.commands[1][1:4] == ["preview", str(project), "--port"]
        assert fake_runner.probes == [(port, project, result.pid)]
        for env in fake_runner.environments:
            assert "OPENAI_API_KEY" not in env
            assert env["HYPERFRAMES_NO_TELEMETRY"] == "1"
        assert fake_runner.environments[1]["HYPERFRAMES_PREVIEW_HOST"] == "127.0.0.1"
    finally:
        stopped = engine.stop_preview(port)
    assert stopped and fake_runner.child.stopped


def test_preview_failed_start_stops_child_without_registering(project, fake_runner):
    fake_runner.child.exit_code = 1
    port = 53140
    with pytest.raises(engine.HyperframesProjectError, match="exited immediately"):
        engine.preview(str(project), port=port)
    assert fake_runner.child.stopped
    assert not engine.stop_preview(port)


@pytest.mark.parametrize(
    ("color", "browser", "rate", "rate_value"),
    [("hdr", "browser_gpu", "crf", 19), ("sdr", "no_browser_gpu", "video_bitrate", "8M")],
)
def test_render_surface_options(project, fake_runner, monkeypatch, capsys, color, browser, rate, rate_value):
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", "true")
    output = str(project / "render.mp4")
    variables_file = project / "data.json"
    variables_file.write_text("{}")
    switches = {
        key: True for key in (color, browser, "docker", "gpu", "quiet", "strict", "strict_all", "strict_variables")
    }
    params = {
        **switches,
        rate: rate_value,
        "max_concurrent_renders": 2,
        "variables": {"headline": "Hi"},
        "variables_file": str(variables_file),
        "quality": "standard",
        "format": "mp4",
    }
    flags = ["--" + key.replace("_", "-") for key in switches]
    mcp = tools.hyperframes_render(str(project), output_path=output, **params)
    Path(output).unlink(missing_ok=True)
    client = Client().hyperframes_render(str(project), output=output, **params)
    Path(output).unlink(missing_ok=True)
    cli = _cli_result(
        capsys,
        "hyperframes-render",
        str(project),
        "--output",
        output,
        *flags,
        "--" + rate.replace("_", "-"),
        str(rate_value),
        "--max-concurrent-renders",
        "2",
        "--variables",
        '{"headline":"Hi"}',
        "--variables-file",
        str(variables_file),
    )
    assert mcp["success"] and client.success and cli["success"], mcp
    assert type(client) is get_type_hints(Client.hyperframes_render.__wrapped__.__wrapped__)["return"]
    command, *other = fake_runner.commands
    assert other == [command, command]
    assert set(flags).issubset(command)
    assert command[command.index("--" + rate.replace("_", "-")) + 1] == str(rate_value)


def test_inspect_surface_options(project, fake_runner, capsys):
    options = {
        "samples": 3,
        "at": [0.25, 1.5],
        "tolerance": 5,
        "timeout_ms": 50,
        "max_issues": 7,
        "strict": True,
    }
    mcp = tools.hyperframes_inspect(str(project), **options)
    client = Client().hyperframes_inspect(str(project), **options)
    cli = _cli_result(
        capsys,
        "hyperframes-inspect",
        str(project),
        "--samples",
        "3",
        "--at",
        "0.25",
        "1.5",
        "--tolerance",
        "5",
        "--timeout-ms",
        "50",
        "--max-issues",
        "7",
        "--strict",
    )
    assert mcp["success"] and client.success and cli["success"], mcp
    command, *other = fake_runner.commands
    assert other == [command, command]
    assert command[command.index("--at") + 1] == "0.25,1.5"
    assert "--strict" in command


def test_tts_list_voices_surface_options(fake_runner, capsys):
    mcp = tools.hyperframes_tts(language="en", list_voices=True)
    client = Client().hyperframes_tts(language="en", list_voices=True)
    cli = _cli_result(capsys, "hyperframes-tts", "--list-voices", "--language", "en")
    assert mcp["success"] and client.success and cli["success"], mcp
    assert fake_runner.commands == [["/fake/bin/hyperframes", "tts", "--lang", "en", "--list", "--json"]] * 3


@pytest.mark.parametrize(
    ("operation", "kwargs", "flags", "message"),
    [
        ("render", {"crf": 99}, ["--crf", "99"], "Invalid crf"),
        ("inspect", {"samples": 0}, ["--samples", "0"], "samples must be"),
        ("tts", {"speed": -1}, ["--speed", "-1"], "speed must be"),
    ],
)
def test_option_validation_is_shared(project, fake_runner, capsys, operation, kwargs, flags, message):
    positional = [] if operation == "tts" else [str(project)]
    mcp = getattr(tools, f"hyperframes_{operation}")(*positional, **kwargs)
    assert mcp["error"]["code"] == "invalid_parameter", mcp
    with pytest.raises(MCPVideoError, match=message):
        getattr(Client(), f"hyperframes_{operation}")(*positional, **kwargs)
    with pytest.raises(MCPVideoError, match=message):
        _cli_result(capsys, f"hyperframes-{operation}", *positional, *flags)
    assert fake_runner.commands == []
