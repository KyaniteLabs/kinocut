"""The Hyperframes subprocess boundary cannot silently enable upstream opt-ins."""

import subprocess
from unittest.mock import MagicMock

import pytest

from kinocut import hyperframes_engine as engine
from kinocut.errors import MCPVideoError


@pytest.fixture(autouse=True)
def telemetry_off(monkeypatch):
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", "false")


def test_unset_consent_disables_telemetry(monkeypatch):
    monkeypatch.delenv("KINOCUT_HYPERFRAMES_TELEMETRY", raising=False)
    assert engine._hyperframes_telemetry_allowed() is False
    assert engine._hyperframes_environment()["HYPERFRAMES_NO_TELEMETRY"] == "1"


def test_commands_suppress_telemetry_installers_and_update_checks(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-credential")
    for name in ["HYPERFRAMES_SKIP_SKILLS", "HYPERFRAMES_NO_TELEMETRY", "HYPERFRAMES_NO_UPDATE_CHECK", "DO_NOT_TRACK"]:
        monkeypatch.setenv(name, "0")
    calls = []
    monkeypatch.setattr(engine, "_hyperframes_command_prefix", lambda **kwargs: ["hyperframes"])
    monkeypatch.setattr(
        engine.subprocess, "run", lambda *a, **kw: calls.append(kw) or subprocess.CompletedProcess(a, 0)
    )
    engine._run_hyperframes(["info"], tmp_path)
    policy = calls[0]["env"]
    assert "GEMINI_API_KEY" not in policy
    for name in [
        "HYPERFRAMES_SKIP_SKILLS",
        "HYPERFRAMES_NO_TELEMETRY",
        "VITE_HYPERFRAMES_NO_TELEMETRY",
        "HYPERFRAMES_NO_UPDATE_CHECK",
        "DO_NOT_TRACK",
    ]:
        assert policy[name] == "1"


def test_capture_never_uses_ambient_provider_credentials(monkeypatch, tmp_path):
    for name in ["OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "HYPERFRAMES_VERTEX_SERVICE_ACCOUNT"]:
        monkeypatch.setenv(name, "fixture-key")
    monkeypatch.setattr(engine, "_require_node", lambda: None)
    monkeypatch.setattr(engine, "_require_hyperframes_deps", lambda **kwargs: None)
    commands = []
    monkeypatch.setattr(
        engine, "_run_hyperframes", lambda args, **kw: commands.append(args) or subprocess.CompletedProcess(args, 0)
    )
    engine._hyperframes_op("capture", url="https://example.invalid", cwd=str(tmp_path))
    assert "--skip-vision" in commands[0]


def test_snapshots_disable_implicit_gemini_analysis(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "_require_node", lambda: None)
    monkeypatch.setattr(engine, "_require_hyperframes_deps", lambda **kw: None)
    monkeypatch.setattr(engine, "_validate_project", lambda path: (tmp_path, tmp_path / "index.html"))
    commands = []
    monkeypatch.setattr(
        engine, "_run_hyperframes", lambda args, **kw: commands.append(args) or subprocess.CompletedProcess(args, 0)
    )
    engine._hyperframes_op("snapshot", project_path=str(tmp_path))
    position = commands[0].index("--describe")
    assert commands[0][position + 1] == "false"


def test_preview_uses_same_privacy_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine, "_run_hyperframes", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="0.8.140")
    )
    monkeypatch.setenv("HYPERFRAMES_NO_TELEMETRY", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-credential")
    monkeypatch.setenv("HYPERFRAMES_PREVIEW_HOST", "0.0.0.0")  # noqa: S104  -- refused ambient bind value
    monkeypatch.setattr(engine, "_require_node", lambda: None)
    monkeypatch.setattr(engine, "_require_hyperframes_deps", lambda **kw: None)
    monkeypatch.setattr(engine, "_validate_project", lambda path: (tmp_path, tmp_path / "index.html"))
    monkeypatch.setattr(engine, "_hyperframes_command_prefix", lambda **kw: ["hyperframes"])
    monkeypatch.setattr(engine, "stop_preview", lambda port: None)
    monkeypatch.setattr(engine, "_register_preview", lambda *a: None)
    monkeypatch.setattr(engine, "_preview_ready", lambda *a: True)
    monkeypatch.setattr(engine.time, "sleep", lambda seconds: None)
    process = MagicMock()
    process.poll.return_value = None
    calls = []
    monkeypatch.setattr(engine.subprocess, "Popen", lambda *a, **kw: calls.append(kw) or process)
    engine.preview(str(tmp_path))
    assert calls[0]["env"]["HYPERFRAMES_NO_TELEMETRY"] == "1"
    assert calls[0]["env"]["HYPERFRAMES_SKIP_SKILLS"] == "1"
    assert calls[0]["env"]["HYPERFRAMES_PREVIEW_HOST"] == "127.0.0.1"
    assert "GEMINI_API_KEY" not in calls[0]["env"]


@pytest.mark.parametrize("version", ["0.8.30", "0.8.141", "", "Hyperframes 0.8.104"])
def test_unverified_preview_cannot_stop_existing_preview(monkeypatch, tmp_path, version):
    monkeypatch.setattr(engine, "_require_node", lambda: None)
    monkeypatch.setattr(engine, "_require_hyperframes_deps", lambda **kw: None)
    monkeypatch.setattr(engine, "_validate_project", lambda path: (tmp_path, tmp_path / "index.html"))
    monkeypatch.setattr(engine, "_run_hyperframes", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=version))
    stop = MagicMock()
    launch = MagicMock()
    monkeypatch.setattr(engine, "stop_preview", stop)
    monkeypatch.setattr(engine.subprocess, "Popen", launch)
    with pytest.raises(MCPVideoError, match="telemetry opt-out"):
        engine.preview(str(tmp_path))
    stop.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize("version", ["0.8.104", "0.8.140"])
def test_verified_preview_versions_pass(monkeypatch, tmp_path, version):
    monkeypatch.setattr(engine, "_run_hyperframes", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=version))
    engine._require_private_preview(tmp_path)


def test_docker_refused_before_any_command(monkeypatch):
    require_node = MagicMock()
    monkeypatch.setattr(engine, "_require_node", require_node)
    with pytest.raises(MCPVideoError, match="Docker rendering"):
        engine._hyperframes_op("render", docker=True)
    require_node.assert_not_called()


def test_consent_allows_docker_without_enabling_model_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    monkeypatch.setattr(engine, "_require_node", lambda: None)
    monkeypatch.setattr(engine, "_require_hyperframes_deps", lambda **kw: None)
    monkeypatch.setattr(engine, "_validate_project", lambda path: (tmp_path, tmp_path / "index.html"))
    commands = []
    monkeypatch.setattr(
        engine, "_run_hyperframes", lambda args, **kw: commands.append(args) or subprocess.CompletedProcess(args, 0)
    )
    engine._hyperframes_op("render", project_path=str(tmp_path), docker=True)
    assert "--docker" in commands[0]
    engine._require_private_preview(tmp_path)
    assert len(commands) == 1  # Consented previews do not depend on a version allowlist.
    assert "GEMINI_API_KEY" not in engine._hyperframes_environment()


@pytest.mark.parametrize("value", ["yes", "1", ""])
def test_invalid_telemetry_consent_fails_closed(monkeypatch, value):
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", value)
    with pytest.raises(MCPVideoError, match="must be true or false"):
        engine._hyperframes_environment()
