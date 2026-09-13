"""Private MCPB interpreter observation at the MCP run boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut.__main__ import _run_mcp_mode
from kinocut.errors import MCPVideoError


def _request(monkeypatch: pytest.MonkeyPatch, root: Path, *, token: str = "a" * 64) -> Path:
    marker = root / "interpreter.json"
    monkeypatch.setenv("KINOCUT_MCPB_SUPERVISED_PROCESS_TREE", "1")
    monkeypatch.setenv("KINOCUT_MCPB_OWNER_READY", str(root / "owner.ready"))
    monkeypatch.setenv("KINOCUT_MCPB_INTERPRETER_FILE", str(marker))
    monkeypatch.setenv("KINOCUT_MCPB_INTERPRETER_TOKEN", token)
    return marker


def test_observation_is_noop_outside_supervision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    marker = _request(monkeypatch, tmp_path)
    monkeypatch.delenv("KINOCUT_MCPB_SUPERVISED_PROCESS_TREE")
    observe_mcp_run_boundary()
    assert not marker.exists()


def test_supervision_without_both_marker_variables_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    monkeypatch.setenv("KINOCUT_MCPB_SUPERVISED_PROCESS_TREE", "1")
    monkeypatch.delenv("KINOCUT_MCPB_INTERPRETER_FILE", raising=False)
    monkeypatch.delenv("KINOCUT_MCPB_INTERPRETER_TOKEN", raising=False)
    observe_mcp_run_boundary()


def test_observation_writes_closed_actual_interpreter_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    marker = _request(monkeypatch, tmp_path)
    observe_mcp_run_boundary()
    assert json.loads(marker.read_text(encoding="utf-8")) == {
        "token": "a" * 64,
        "pid": os.getpid(),
        "role": "mcp_interpreter",
        "phase": "mcp_run_boundary",
    }


@pytest.mark.parametrize("missing", ["KINOCUT_MCPB_INTERPRETER_FILE", "KINOCUT_MCPB_INTERPRETER_TOKEN"])
def test_partial_observation_request_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    _request(monkeypatch, tmp_path)
    monkeypatch.delenv(missing)
    with pytest.raises(MCPVideoError, match="MCP process observation failed") as caught:
        observe_mcp_run_boundary()
    assert caught.value.code == "mcpb_observation_failed"


@pytest.mark.parametrize("token", ["", "A" * 64, "x" * 64, "a" * 63, "a" * 65])
def test_malformed_observation_token_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    _request(monkeypatch, tmp_path, token=token)
    with pytest.raises(MCPVideoError) as caught:
        observe_mcp_run_boundary()
    assert caught.value.code == "mcpb_observation_failed"


def test_observation_rejects_outside_owner_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    other = tmp_path / "other"
    other.mkdir()
    _request(monkeypatch, tmp_path)
    monkeypatch.setenv("KINOCUT_MCPB_INTERPRETER_FILE", str(other / "interpreter.json"))
    with pytest.raises(MCPVideoError):
        observe_mcp_run_boundary()


def test_observation_rejects_oversize_path_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    _request(monkeypatch, tmp_path)
    monkeypatch.setenv("KINOCUT_MCPB_INTERPRETER_FILE", "/" + "x" * 4097)
    with pytest.raises(MCPVideoError) as caught:
        observe_mcp_run_boundary()
    assert caught.value.code == "mcpb_observation_failed"


def test_observation_rejects_symlinked_owner_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    _request(monkeypatch, linked)
    with pytest.raises(MCPVideoError):
        observe_mcp_run_boundary()


@pytest.mark.parametrize("kind", ["regular", "symlink"])
def test_observation_never_overwrites_existing_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from kinocut._mcpb_observation import observe_mcp_run_boundary

    marker = _request(monkeypatch, tmp_path)
    target = tmp_path / "target"
    target.write_text("preserve", encoding="utf-8")
    if kind == "regular":
        marker.write_text("preserve", encoding="utf-8")
    else:
        try:
            marker.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is unavailable")
    with pytest.raises(MCPVideoError):
        observe_mcp_run_boundary()
    assert target.read_text(encoding="utf-8") == "preserve"
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_observation_mid_publication_race_does_not_overwrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import kinocut._mcpb_observation as observation

    marker = _request(monkeypatch, tmp_path)
    original_open = observation.os.open

    def racing_open(path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        marker.write_text("racer", encoding="utf-8")
        return original_open(path, flags, mode)

    monkeypatch.setattr(observation.os, "open", racing_open)
    with pytest.raises(MCPVideoError):
        observation.observe_mcp_run_boundary()
    assert marker.read_text(encoding="utf-8") == "racer"


def test_independent_interpreter_reports_its_own_pid(tmp_path: Path) -> None:
    marker = tmp_path / "interpreter.json"
    env = dict(os.environ)
    env.update(
        KINOCUT_MCPB_SUPERVISED_PROCESS_TREE="1",
        KINOCUT_MCPB_OWNER_READY=str(tmp_path / "owner.ready"),
        KINOCUT_MCPB_INTERPRETER_FILE=str(marker),
        KINOCUT_MCPB_INTERPRETER_TOKEN="b" * 64,
    )
    child = subprocess.run(
        [sys.executable, "-c", "from kinocut._mcpb_observation import observe_mcp_run_boundary as f; f()"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    pid = json.loads(marker.read_text(encoding="utf-8"))["pid"]
    assert pid != os.getpid()


def test_mcp_mode_reports_only_observation_error_as_constant_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kinocut._mcpb_observation as observation

    messages: list[str] = []
    ran: list[bool] = []
    monkeypatch.setattr(
        observation,
        "observe_mcp_run_boundary",
        lambda: (_ for _ in ()).throw(
            MCPVideoError("private/path token", error_type="processing_error", code="mcpb_observation_failed")
        ),
    )
    monkeypatch.setattr("kinocut.__main__.err_console.print", messages.append)
    with pytest.raises(SystemExit) as caught:
        _run_mcp_mode(lambda: SimpleNamespace(run=lambda: ran.append(True)))
    assert caught.value.code == 1
    assert ran == []
    assert messages == ["[red]MCP mode failed to start:[/red] supervised process observation failed."]
    assert "private" not in messages[0] and "token" not in messages[0]


def test_mcp_mode_does_not_reclassify_runtime_mcp_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import kinocut._mcpb_observation as observation

    monkeypatch.setattr(observation, "observe_mcp_run_boundary", lambda: None)
    runtime_error = MCPVideoError("runtime failure", code="runtime_code")
    with pytest.raises(MCPVideoError) as caught:
        _run_mcp_mode(lambda: SimpleNamespace(run=lambda: (_ for _ in ()).throw(runtime_error)))
    assert caught.value is runtime_error
