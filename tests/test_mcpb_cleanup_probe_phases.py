"""Authenticated phase evidence for the hostile MCPB cleanup probe."""

from __future__ import annotations

import argparse
import importlib.util
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).parents[1]


def _owner_helper():
    path = ROOT / ".github" / "scripts" / "mcpb_process_owner.py"
    spec = importlib.util.spec_from_file_location("mcpb_cleanup_owner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Pipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Process:
    def __init__(
        self,
        *,
        polls: list[int | None] | None = None,
        kill_error: Exception | None = None,
        wait_error: Exception | None = None,
        stdin: _Pipe | None = None,
    ) -> None:
        self.stdin = stdin
        self._polls = iter(polls or [None])
        self._last_poll: int | None = None
        self.kill_error = kill_error
        self.wait_error = wait_error
        self.killed = False

    def poll(self) -> int | None:
        with suppress(StopIteration):
            self._last_poll = next(self._polls)
        return self._last_poll

    def kill(self) -> None:
        if self.kill_error:
            raise self.kill_error
        self.killed = True

    def wait(self, *, timeout: float) -> int:
        assert timeout == 5
        if self.wait_error:
            raise self.wait_error
        self._last_poll = -9
        return -9


class _Kernel:
    def __init__(self, *, query_ok: bool = True, member: bool = True) -> None:
        self.query_ok = query_ok
        self.member = member
        self.opened_processes: list[int] = []
        self.opened_jobs: list[str] = []
        self.exit_queries: list[int] = []
        self.membership_queries: list[tuple[int, int]] = []
        self.closed: list[int] = []

    def OpenProcess(self, _access: int, _inherit: bool, pid: int) -> int:
        self.opened_processes.append(pid)
        return 41

    def GetExitCodeProcess(self, handle: int, result: Any) -> bool:
        self.exit_queries.append(handle)
        result._obj.value = 259
        return self.query_ok

    def OpenJobObjectW(self, _access: int, _inherit: bool, name: str) -> int:
        self.opened_jobs.append(name)
        return 42

    def IsProcessInJob(self, process: int, job: int, result: Any) -> bool:
        self.membership_queries.append((process, job))
        result._obj.value = self.member
        return self.query_ok

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return True


class _Identity:
    def __init__(self, *, alive: list[bool | Exception] | None = None, member: bool | Exception = True) -> None:
        self._alive = iter(alive or [True, True, True])
        self.member = member
        self.closed = 0
        self.events: list[str] = []

    def alive(self) -> bool:
        self.events.append("alive")
        result = next(self._alive)
        if isinstance(result, Exception):
            raise result
        return result

    def in_owner(self, _name: str) -> bool:
        self.events.append("membership")
        if isinstance(self.member, Exception):
            raise self.member
        return self.member

    def close(self) -> bool:
        self.events.append("close")
        self.closed += 1
        return True


def _args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        launcher=tmp_path / "launcher.js",
        venv=tmp_path / "venv",
        node=tmp_path / "node",
        pid_file=tmp_path / "server.json",
        survival_file=tmp_path / "survival.state",
        token="a" * 64,
    )


def _run_child(
    helper: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    launcher: _Process | None = None,
    keeper: _Process | None = None,
    identity: _Identity | None = None,
) -> argparse.Namespace:
    args = _args(tmp_path)
    launcher = launcher or _Process(stdin=_Pipe())
    keeper = keeper or _Process(polls=[None, None])
    processes = iter([launcher, keeper])
    monkeypatch.setenv(helper.OWNER_READY_ENV, str(tmp_path / "owner" / "owner.ready"))
    monkeypatch.setenv(helper.OWNER_NAME_ENV, "test-owner")
    monkeypatch.setattr(helper, "activate_child_from_env", lambda: "test_owner")
    monkeypatch.setattr(helper.subprocess, "Popen", lambda *_args, **_kwargs: next(processes))
    monkeypatch.setattr(helper, "observed_interpreter_pid", lambda *_args, **_kwargs: 12345)
    monkeypatch.setattr(helper, "_InterpreterIdentity", lambda _pid: identity or _Identity())
    helper.cleanup_probe_child(args, 4096, 0.1)
    return args


def test_interpreter_marker_reader_requires_exact_authenticated_schema(tmp_path: Path) -> None:
    helper = _owner_helper()
    path = tmp_path / "interpreter.json"
    valid = {
        "token": "a" * 64,
        "pid": 12345,
        "role": "mcp_interpreter",
        "phase": "mcp_run_boundary",
    }
    path.write_text(json.dumps(valid), encoding="utf-8")
    assert helper.observed_interpreter_pid(path, "a" * 64, 4096) == 12345

    for key, value in (("role", "launcher_child"), ("phase", "spawned"), ("pid", True)):
        forged = dict(valid)
        forged[key] = value
        path.write_text(json.dumps(forged), encoding="utf-8")
        assert helper.observed_interpreter_pid(path, "a" * 64, 4096) is None

    valid["extra"] = "forged"
    path.write_text(json.dumps(valid), encoding="utf-8")
    assert helper.observed_interpreter_pid(path, "a" * 64, 4096) is None


def test_launcher_child_identity_cannot_masquerade_as_interpreter(tmp_path: Path) -> None:
    helper = _owner_helper()
    token = "a" * 64
    launcher_child = tmp_path / "launcher-child.json"
    interpreter = tmp_path / "interpreter.json"
    launcher_child.write_text(
        json.dumps({"token": token, "pid": 111, "role": "launcher_child", "phase": "spawned"}),
        encoding="utf-8",
    )
    interpreter.write_text(
        json.dumps({"token": token, "pid": 222, "role": "mcp_interpreter", "phase": "mcp_run_boundary"}),
        encoding="utf-8",
    )

    assert helper.observed_interpreter_pid(launcher_child, token, 4096) is None
    assert helper.observed_interpreter_pid(interpreter, token, 4096) == 222


def test_windows_interpreter_identity_retains_one_handle_and_proves_named_job() -> None:
    helper = _owner_helper()
    kernel = _Kernel()
    identity = helper._InterpreterIdentity(12345, kernel=kernel, windows=True)

    assert identity.alive() is True
    assert identity.alive() is True
    assert identity.in_owner("owner-name") is True
    assert identity.alive() is True
    assert identity.close() is True
    assert identity.close() is True

    assert kernel.opened_processes == [12345]
    assert kernel.exit_queries == [41, 41, 41]
    assert kernel.opened_jobs == ["owner-name"]
    assert kernel.membership_queries == [(41, 42)]
    assert kernel.closed == [42, 41]


def test_windows_interpreter_identity_treats_query_failure_as_unavailable() -> None:
    helper = _owner_helper()
    kernel = _Kernel(query_ok=False)
    identity = helper._InterpreterIdentity(12345, kernel=kernel, windows=True)
    with pytest.raises(OSError, match="process_state_unavailable"):
        identity.alive()
    assert identity.close() is True
    assert kernel.closed == [41]


def test_windows_membership_query_failure_closes_job_and_process_handles() -> None:
    helper = _owner_helper()
    kernel = _Kernel()
    identity = helper._InterpreterIdentity(12345, kernel=kernel, windows=True)
    assert identity.alive() is True
    kernel.query_ok = False
    with pytest.raises(OSError, match="owner_membership_unavailable"):
        identity.in_owner("owner-name")
    assert identity.close() is True
    assert kernel.closed == [42, 41]


def test_cleanup_state_rejects_skips_repeats_and_backward_transitions(tmp_path: Path) -> None:
    helper = _owner_helper()
    state = helper._CleanupProbeState(tmp_path / "state", "a" * 64)

    with pytest.raises(RuntimeError, match="cleanup_probe_state_sequence_invalid"):
        state.advance("launcher_started")
    state.advance("owner_activated")
    with pytest.raises(RuntimeError, match="cleanup_probe_state_sequence_invalid"):
        state.advance("owner_activated")
    state.advance("launcher_started")
    with pytest.raises(RuntimeError, match="cleanup_probe_state_sequence_invalid"):
        state.advance("owner_activated")


def test_first_failure_is_terminal_and_preserves_its_exact_bytes(tmp_path: Path) -> None:
    helper = _owner_helper()
    path = tmp_path / "state"
    state = helper._CleanupProbeState(path, "a" * 64)
    state.advance("owner_activated")
    state.fail("launcher_started", "launcher_not_startable")
    first_failure = path.read_bytes()

    operations = [
        lambda: state.fail("launcher_started", "launcher_exited"),
        lambda: state.advance("launcher_started"),
        lambda: state.publish_survival(12345),
    ]
    for operation in operations:
        with pytest.raises(RuntimeError, match="cleanup_probe_state_sequence_invalid"):
            operation()
        assert path.read_bytes() == first_failure
    assert not helper._read_ready(path, "a" * 64)


def test_failed_failure_write_is_terminal_and_leaves_parent_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _owner_helper()
    path = tmp_path / "state"
    state = helper._CleanupProbeState(path, "a" * 64)
    state.advance("owner_activated")
    completed_phase = path.read_bytes()
    original = helper._write_cleanup_state

    def fail_failure_record(target: Path, contents: str) -> None:
        if "failure_phase" in contents:
            raise OSError("private detail")
        original(target, contents)

    monkeypatch.setattr(helper, "_write_cleanup_state", fail_failure_record)
    with pytest.raises(OSError, match="private detail"):
        state.fail("launcher_started", "launcher_not_startable")
    assert path.read_bytes() == completed_phase

    operations = (
        lambda: state.fail("launcher_started", "launcher_not_startable"),
        lambda: state.advance("launcher_started"),
        lambda: state.publish_survival(12345),
    )
    for operation in operations:
        with pytest.raises(RuntimeError, match="cleanup_probe_state_sequence_invalid"):
            operation()
        assert path.read_bytes() == completed_phase
    assert helper._read_cleanup_probe_failure(path, "a" * 64, 4096) is None


def test_cleanup_state_writer_rejects_valid_enum_with_wrong_phase(tmp_path: Path) -> None:
    helper = _owner_helper()
    state = helper._CleanupProbeState(tmp_path / "state", "a" * 64)
    state.advance("owner_activated")

    with pytest.raises(RuntimeError, match="cleanup_probe_state_sequence_invalid"):
        state.fail("launcher_started", "interpreter_not_alive_after_launcher")


def test_cleanup_state_reader_rejects_valid_enum_with_wrong_phase(tmp_path: Path) -> None:
    helper = _owner_helper()
    path = tmp_path / "state"
    path.write_text(
        json.dumps(
            {
                "token": "a" * 64,
                "phase": "owner_activated",
                "failure_phase": "launcher_started",
                "probe_exit_class": "interpreter_not_alive_after_launcher",
            }
        ),
        encoding="utf-8",
    )

    assert helper._read_cleanup_probe_failure(path, "a" * 64, 4096) is None


@pytest.mark.parametrize(
    "contents",
    [
        "{}",
        "not-json",
        '{"token":"' + "b" * 64 + '","phase":"owner_activated"}',
        json.dumps(
            {
                "token": "a" * 64,
                "phase": None,
                "failure_phase": "owner_activated",
                "probe_exit_class": [],
            }
        ),
    ],
)
def test_cleanup_state_reader_rejects_malformed_or_forged_state(tmp_path: Path, contents: str) -> None:
    helper = _owner_helper()
    path = tmp_path / "state"
    path.write_text(contents, encoding="utf-8")

    assert helper._read_cleanup_probe_failure(path, "a" * 64, 4096) is None


def test_cleanup_state_reader_rejects_oversize(tmp_path: Path) -> None:
    helper = _owner_helper()
    target = tmp_path / "target"
    target.write_text("x" * 4097, encoding="utf-8")
    assert helper._read_cleanup_probe_failure(target, "a" * 64, 4096) is None


def test_cleanup_state_reader_rejects_symlink(tmp_path: Path) -> None:
    helper = _owner_helper()
    target = tmp_path / "target"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert helper._read_cleanup_probe_failure(link, "a" * 64, 4096) is None


def test_cleanup_child_publishes_terminal_proof_only_after_exact_interpreter_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _owner_helper()
    writes: list[str] = []
    original = helper._write_cleanup_state

    def capture(path: Path, contents: str) -> None:
        writes.append(contents)
        original(path, contents)

    monkeypatch.setattr(helper, "_write_cleanup_state", capture)
    identity = _Identity()
    args = _run_child(helper, tmp_path, monkeypatch, identity=identity)

    assert helper._read_cleanup_probe_success(args.survival_file, args.token, 4096) == 12345
    assert [json.loads(item)["phase"] for item in writes] == [
        "owner_activated",
        "launcher_started",
        "interpreter_observed",
        "interpreter_alive_before_close",
        "stdin_keeper_started",
        "interpreter_alive_after_transfer",
        "launcher_terminated",
        "interpreter_alive_after_launcher",
        "owner_membership_confirmed",
        "survival_published",
    ]
    assert identity.events[:5] == ["alive", "alive", "alive", "membership", "close"]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OSError("private detail"), "launcher_not_startable"),
        (_Process(stdin=None), "launcher_capture_unavailable"),
        (_Process(stdin=_Pipe(), polls=[1]), "launcher_exited"),
    ],
)
def test_launcher_start_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception | _Process, expected: str
) -> None:
    helper = _owner_helper()
    args = _args(tmp_path)
    monkeypatch.setenv(helper.OWNER_READY_ENV, str(tmp_path / "owner" / "owner.ready"))
    monkeypatch.setattr(helper, "activate_child_from_env", lambda: "test_owner")

    def popen(*_args: object, **_kwargs: object) -> _Process:
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(helper.subprocess, "Popen", popen)
    with pytest.raises(RuntimeError, match=expected):
        helper.cleanup_probe_child(args, 4096, 0.1)

    assert helper._read_cleanup_probe_failure(args.survival_file, args.token, 4096) == {
        "failure_phase": "launcher_started",
        "probe_exit_class": expected,
    }


def test_interpreter_observation_timeout_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _owner_helper()
    args = _args(tmp_path)
    launcher = _Process(stdin=_Pipe())
    monkeypatch.setattr(helper, "activate_child_from_env", lambda: "test_owner")
    monkeypatch.setenv(helper.OWNER_READY_ENV, str(tmp_path / "owner" / "owner.ready"))
    monkeypatch.setattr(helper.subprocess, "Popen", lambda *_args, **_kwargs: launcher)
    monkeypatch.setattr(helper, "observed_interpreter_pid", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="interpreter_unobserved"):
        helper.cleanup_probe_child(args, 4096, 0)

    assert helper._read_cleanup_probe_failure(args.survival_file, args.token, 4096) == {
        "failure_phase": "interpreter_observed",
        "probe_exit_class": "interpreter_unobserved",
    }


def test_keeper_start_failure_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _owner_helper()
    args = _args(tmp_path)
    launcher = _Process(stdin=_Pipe())
    calls = iter([launcher, OSError("private detail")])
    monkeypatch.setenv(helper.OWNER_READY_ENV, str(tmp_path / "owner" / "owner.ready"))
    monkeypatch.setattr(helper, "activate_child_from_env", lambda: "test_owner")
    monkeypatch.setattr(
        helper.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(value) if isinstance((value := next(calls)), Exception) else value
        ),
    )
    monkeypatch.setattr(helper, "observed_interpreter_pid", lambda *_args, **_kwargs: 12345)
    monkeypatch.setattr(helper, "_InterpreterIdentity", lambda _pid: _Identity())

    with pytest.raises(RuntimeError, match="stdin_keeper_not_startable"):
        helper.cleanup_probe_child(args, 4096, 0.1)

    assert helper._read_cleanup_probe_failure(args.survival_file, args.token, 4096) == {
        "failure_phase": "stdin_keeper_started",
        "probe_exit_class": "stdin_keeper_not_startable",
    }


@pytest.mark.parametrize(
    ("polls", "failure_phase"),
    [
        ([1], "stdin_keeper_started"),
        ([None, 1], "interpreter_alive_after_transfer"),
        ([None, None, 1], "launcher_terminated"),
        ([None, None, None, 1], "interpreter_alive_after_launcher"),
    ],
)
def test_keeper_must_be_alive_on_both_sides_of_node_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    polls: list[int | None],
    failure_phase: str,
) -> None:
    helper = _owner_helper()
    args = _args(tmp_path)
    launcher = _Process(stdin=_Pipe())
    keeper = _Process(polls=polls)
    processes = iter([launcher, keeper])
    monkeypatch.setenv(helper.OWNER_READY_ENV, str(tmp_path / "owner" / "owner.ready"))
    monkeypatch.setattr(helper, "activate_child_from_env", lambda: "test_owner")
    monkeypatch.setattr(helper.subprocess, "Popen", lambda *_args, **_kwargs: next(processes))
    monkeypatch.setattr(helper, "observed_interpreter_pid", lambda *_args, **_kwargs: 12345)
    monkeypatch.setattr(helper, "_InterpreterIdentity", lambda _pid: _Identity())

    with pytest.raises(RuntimeError, match="stdin_keeper_exited"):
        helper.cleanup_probe_child(args, 4096, 0.1)

    assert helper._read_cleanup_probe_failure(args.survival_file, args.token, 4096) == {
        "failure_phase": failure_phase,
        "probe_exit_class": "stdin_keeper_exited",
    }


@pytest.mark.parametrize("operation", ["kill", "wait"])
def test_node_termination_failure_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    helper = _owner_helper()
    error = OSError("private detail")
    launcher = _Process(
        stdin=_Pipe(),
        kill_error=error if operation == "kill" else None,
        wait_error=error if operation == "wait" else None,
    )

    with pytest.raises(RuntimeError, match="launcher_terminate_failed"):
        _run_child(helper, tmp_path, monkeypatch, launcher=launcher)


@pytest.mark.parametrize(
    ("alive", "expected_phase", "expected"),
    [
        ([False], "interpreter_alive_before_close", "interpreter_not_alive_before_close"),
        ([True, False], "interpreter_alive_after_transfer", "interpreter_not_alive_after_transfer"),
        ([True, True, False], "interpreter_alive_after_launcher", "interpreter_not_alive_after_launcher"),
        ([OSError("private detail")], "interpreter_alive_before_close", "interpreter_state_unavailable"),
    ],
)
def test_exact_interpreter_liveness_failure_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alive: list[bool | Exception],
    expected_phase: str,
    expected: str,
) -> None:
    helper = _owner_helper()
    args = _args(tmp_path)
    launcher = _Process(stdin=_Pipe())
    keeper = _Process(polls=[None, None, None, None])
    processes = iter([launcher, keeper])
    monkeypatch.setenv(helper.OWNER_READY_ENV, str(tmp_path / "owner" / "owner.ready"))
    monkeypatch.setattr(helper, "activate_child_from_env", lambda: "test_owner")
    monkeypatch.setattr(helper.subprocess, "Popen", lambda *_args, **_kwargs: next(processes))
    monkeypatch.setattr(helper, "observed_interpreter_pid", lambda *_args, **_kwargs: 12345)
    monkeypatch.setattr(helper, "_InterpreterIdentity", lambda _pid: _Identity(alive=alive))
    with pytest.raises(RuntimeError, match=expected):
        helper.cleanup_probe_child(args, 4096, 0.1)
    assert helper._read_cleanup_probe_failure(args.survival_file, args.token, 4096) == {
        "failure_phase": expected_phase,
        "probe_exit_class": expected,
    }


@pytest.mark.parametrize(
    ("member", "expected"),
    [(False, "interpreter_not_in_owner"), (OSError("private detail"), "owner_membership_unavailable")],
)
def test_owner_membership_is_required_before_survival(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: bool | Exception, expected: str
) -> None:
    identity = _Identity(member=member)
    with pytest.raises(RuntimeError, match=expected):
        _run_child(_owner_helper(), tmp_path, monkeypatch, identity=identity)
    assert identity.closed >= 1


def test_final_publication_failure_after_interpreter_observation_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _owner_helper()
    args = _args(tmp_path)
    original = helper._CleanupProbeState.publish_survival

    def fail_publication(self: Any, _pid: int) -> None:
        raise OSError("private detail")

    monkeypatch.setattr(helper._CleanupProbeState, "publish_survival", fail_publication)
    with pytest.raises(RuntimeError, match="survival_publish_failed"):
        _run_child(helper, tmp_path, monkeypatch)
    monkeypatch.setattr(helper._CleanupProbeState, "publish_survival", original)

    assert helper._read_cleanup_probe_failure(args.survival_file, args.token, 4096) == {
        "failure_phase": "survival_published",
        "probe_exit_class": "survival_publish_failed",
    }


def test_failed_outer_receipt_uses_only_authenticated_failure_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _owner_helper()

    def runner(command: list[str], **_kwargs: object) -> None:
        state_path = Path(command[command.index("--survival-file") + 1])
        token = command[command.index("--token") + 1]
        state = helper._CleanupProbeState(state_path, token)
        state.advance("owner_activated")
        state.fail("launcher_started", "launcher_not_startable")
        error = RuntimeError("outer detail")
        error.classification = "command_failed"  # type: ignore[attr-defined]
        error.cleanup = "passed"  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(helper, "force_pid_gone", lambda _pid: True)
    args = argparse.Namespace(os="windows", architecture="X64", launcher="x", venv="v", node="n")
    payload = helper.cleanup_probe_payload(args, runner, Path("helper.py"), 4096)

    assert payload["status"] == "failed"
    assert payload["cleanup"] == "passed"
    assert payload["failure_phase"] == "launcher_started"
    assert payload["probe_exit_class"] == "launcher_not_startable"
    assert set(payload) == {
        "artifact_kind",
        "os",
        "architecture",
        "status",
        "cleanup",
        "exit_class",
        "topology",
        "false_success_suppressed",
        "failure_phase",
        "probe_exit_class",
    }


@pytest.mark.parametrize("state", [None, "intermediate", "forged"])
def test_untrusted_outer_state_is_bounded_unknown(tmp_path: Path, state: str | None) -> None:
    helper = _owner_helper()

    def runner(command: list[str], **_kwargs: object) -> None:
        path = Path(command[command.index("--survival-file") + 1])
        token = command[command.index("--token") + 1]
        if state == "intermediate":
            helper._CleanupProbeState(path, token).advance("owner_activated")
        elif state == "forged":
            path.write_text(json.dumps({"token": "b" * 64, "phase": "owner_activated"}), encoding="utf-8")
        error = RuntimeError("outer detail")
        error.classification = "command_failed"  # type: ignore[attr-defined]
        error.cleanup = "passed"  # type: ignore[attr-defined]
        raise error

    args = argparse.Namespace(os="windows", architecture="X64", launcher="x", venv="v", node="n")
    payload = helper.cleanup_probe_payload(args, runner, Path("helper.py"), 4096)

    assert payload["failure_phase"] == "evidence_unavailable"
    assert payload["probe_exit_class"] == "cleanup_probe_evidence_unknown"


def test_windows_outer_success_uses_authenticated_owner_cleanup_without_reopening_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _owner_helper()

    def runner(command: list[str], **_kwargs: object) -> None:
        path = Path(command[command.index("--survival-file") + 1])
        token = command[command.index("--token") + 1]
        state = helper._CleanupProbeState(path, token)
        for phase in helper._CLEANUP_PHASES[:-1]:
            state.advance(phase)
        state.publish_survival(12345)
        error = RuntimeError("outer detail")
        error.classification = "descendant_survived_command"  # type: ignore[attr-defined]
        error.cleanup = "passed"  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(helper, "_WINDOWS_HOST", True)
    monkeypatch.setattr(
        helper, "pid_exists", lambda _pid: (_ for _ in ()).throw(AssertionError("numeric PID reopened"))
    )
    args = argparse.Namespace(os="windows", architecture="X64", launcher="x", venv="v", node="n")
    payload = helper.cleanup_probe_payload(args, runner, Path("helper.py"), 4096)

    assert payload["status"] == "passed"
    assert payload["cleanup"] == "passed"
    assert payload["false_success_suppressed"] == "passed"


def test_posix_outer_success_requires_exact_interpreter_pid_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _owner_helper()
    waited: list[int] = []

    def runner(command: list[str], **_kwargs: object) -> None:
        path = Path(command[command.index("--survival-file") + 1])
        token = command[command.index("--token") + 1]
        path.write_text(json.dumps({"token": token, "pid": 23456, "phase": "survival_published"}), encoding="utf-8")
        error = RuntimeError("outer detail")
        error.classification = "descendant_survived_command"  # type: ignore[attr-defined]
        error.cleanup = "passed"  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(helper, "_WINDOWS_HOST", False)
    monkeypatch.setattr(helper, "wait_pid_gone", lambda pid: not waited.append(pid))
    monkeypatch.setattr(helper, "pid_exists", lambda _pid: False)
    args = argparse.Namespace(os="linux", architecture="X64", launcher="x", venv="v", node="n")
    payload = helper.cleanup_probe_payload(args, runner, Path("helper.py"), 4096)

    assert payload["status"] == "passed"
    assert waited == [23456]
