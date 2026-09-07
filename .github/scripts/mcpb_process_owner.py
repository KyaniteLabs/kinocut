"""Cross-platform process ownership for the staged MCPB CI runtime."""

from __future__ import annotations

import ctypes
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, NoReturn


OWNER_NAME_ENV = "KINOCUT_MCPB_OWNER_NAME"
OWNER_READY_ENV = "KINOCUT_MCPB_OWNER_READY"
OWNER_TOKEN_ENV = "KINOCUT_MCPB_OWNER_TOKEN"  # noqa: S105 - transient process-ownership nonce, not a credential.
OWNER_KIND_ENV = "KINOCUT_MCPB_OWNER_KIND"
OWNER_TIMEOUT = 5.0
TREE_GRACE = 2.0
_TOKEN = re.compile(r"[0-9a-f]{64}")
_CLEANUP_PHASES = (
    "owner_activated",
    "launcher_started",
    "server_observed",
    "stdin_keeper_started",
    "launcher_terminated",
    "server_alive",
    "survival_published",
)
_CLEANUP_FAILURES_BY_PHASE = {
    "owner_activated": frozenset({"owner_activation_failed"}),
    "launcher_started": frozenset({"launcher_not_startable", "launcher_capture_unavailable", "launcher_exited"}),
    "server_observed": frozenset({"launcher_exited", "server_unobserved"}),
    "stdin_keeper_started": frozenset({"stdin_keeper_not_startable", "stdin_keeper_exited"}),
    "launcher_terminated": frozenset({"stdin_keeper_exited", "launcher_terminate_failed"}),
    "server_alive": frozenset({"stdin_keeper_exited", "server_state_unavailable", "server_not_alive_after_launcher"}),
    "survival_published": frozenset({"survival_publish_failed"}),
}
_CLEANUP_STATE_MAX = 1024


class OwnerActivationError(RuntimeError):
    """The runtime child could not enter its supervisor's owner."""

    def __init__(self, classification: str, cleanup: str = "passed") -> None:
        super().__init__(classification)
        self.cleanup = cleanup


class _JobLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


def _kernel32() -> Any:
    if os.name != "nt":
        raise OwnerActivationError("owner_not_activated")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel.CreateJobObjectW.restype = ctypes.c_void_p
    kernel.OpenJobObjectW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenJobObjectW.restype = ctypes.c_void_p
    kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    kernel.SetInformationJobObject.restype = ctypes.c_int
    kernel.QueryInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel.QueryInformationJobObject.restype = ctypes.c_int
    kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.AssignProcessToJobObject.restype = ctypes.c_int
    kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.TerminateJobObject.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetExitCodeProcess.restype = ctypes.c_int
    return kernel


def _wait_until(predicate: Any, timeout: float = TREE_GRACE) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _read_ready(path: Path, token: str) -> bool:
    try:
        return (
            not path.is_symlink()
            and path.is_file()
            and path.stat().st_size == 64
            and path.read_text(encoding="utf-8") == token
        )
    except OSError:
        return False


class PosixOwner:
    kind = "posix_process_group"

    def __init__(self, root: Path) -> None:
        self.token = secrets.token_hex(32)
        self.ready = root / "owner.ready"
        self.pid: int | None = None

    def environment(self) -> dict[str, str]:
        return {OWNER_KIND_ENV: self.kind, OWNER_READY_ENV: str(self.ready), OWNER_TOKEN_ENV: self.token}

    def bind(self, process: subprocess.Popen[bytes]) -> None:
        self.pid = process.pid

    def wait_activated(self, process: subprocess.Popen[bytes], timeout: float = OWNER_TIMEOUT) -> bool:
        return _wait_until(
            lambda: _read_ready(self.ready, self.token) or process.poll() is not None, timeout
        ) and _read_ready(self.ready, self.token)

    def active(self) -> bool:
        if self.pid is None:
            return False
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def terminate(self) -> bool:
        if self.pid is None:
            return True
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.pid, sig)
            except ProcessLookupError:
                return True
            except OSError:
                continue
            if _wait_until(lambda: not self.active()):
                return True
        return not self.active()

    def close(self) -> bool:
        return True


class WindowsJobOwner:
    kind = "windows_job"

    def __init__(self, root: Path, kernel: Any | None = None) -> None:
        self.kernel = kernel or _kernel32()
        self.token = secrets.token_hex(32)
        self.ready = root / "owner.ready"
        self.name = f"kinocut-mcpb-{self.token}"
        self.handle = self.kernel.CreateJobObjectW(None, self.name)
        if not self.handle:
            raise OwnerActivationError("owner_not_activated")
        limits = _ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            closed = self.close()
            raise OwnerActivationError("owner_not_activated", "passed" if closed else "failed")

    def environment(self) -> dict[str, str]:
        return {
            OWNER_KIND_ENV: self.kind,
            OWNER_NAME_ENV: self.name,
            OWNER_READY_ENV: str(self.ready),
            OWNER_TOKEN_ENV: self.token,
        }

    def bind(self, _process: subprocess.Popen[bytes]) -> None:
        return None

    def wait_activated(self, process: subprocess.Popen[bytes], timeout: float = OWNER_TIMEOUT) -> bool:
        return _wait_until(
            lambda: _read_ready(self.ready, self.token) or process.poll() is not None, timeout
        ) and _read_ready(self.ready, self.token)

    def active(self) -> bool:
        info = _Accounting()
        ok = self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None)
        if not ok:
            raise OSError("job_query_failed")
        return info.ActiveProcesses > 0

    def terminate(self) -> bool:
        try:
            if not self.active():
                return True
            if not self.kernel.TerminateJobObject(self.handle, 1):
                return False
            return _wait_until(lambda: not self.active())
        except OSError:
            return False

    def close(self) -> bool:
        if not self.handle:
            return True
        handle, self.handle = self.handle, None
        return bool(self.kernel.CloseHandle(handle))


def create_owner(root: Path) -> PosixOwner | WindowsJobOwner:
    return WindowsJobOwner(root) if os.name == "nt" else PosixOwner(root)


def _publish_ready(path: Path, token: str) -> None:
    if path.exists() or path.is_symlink() or not _TOKEN.fullmatch(token):
        raise OwnerActivationError("owner_not_activated")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(token)
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise OwnerActivationError("owner_not_activated") from error


def _write_cleanup_state(path: Path, contents: str) -> None:
    if len(contents.encode("utf-8")) > _CLEANUP_STATE_MAX:
        raise OSError("cleanup_probe_state_too_large")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError("cleanup_probe_state_invalid")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(contents)
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


class _CleanupProbeState:
    def __init__(self, path: Path, token: str) -> None:
        if not _TOKEN.fullmatch(token):
            raise RuntimeError("cleanup_probe_state_token_invalid")
        self.path = path
        self.token = token
        self.phase: str | None = None
        self.failed = False

    def _expected(self) -> str:
        index = 0 if self.phase is None else _CLEANUP_PHASES.index(self.phase) + 1
        return _CLEANUP_PHASES[index] if index < len(_CLEANUP_PHASES) else ""

    def advance(self, phase: str) -> None:
        if self.failed or phase != self._expected() or phase == "survival_published":
            raise RuntimeError("cleanup_probe_state_sequence_invalid")
        payload = {"token": self.token, "phase": phase}
        _write_cleanup_state(self.path, json.dumps(payload, separators=(",", ":")))
        self.phase = phase

    def fail(self, failure_phase: str, classification: str) -> None:
        if self.failed:
            raise RuntimeError("cleanup_probe_state_sequence_invalid")
        self.failed = True
        if (
            failure_phase != self._expected()
            or not isinstance(classification, str)
            or classification not in _CLEANUP_FAILURES_BY_PHASE.get(failure_phase, ())
        ):
            raise RuntimeError("cleanup_probe_state_sequence_invalid")
        payload = {
            "token": self.token,
            "phase": self.phase,
            "failure_phase": failure_phase,
            "probe_exit_class": classification,
        }
        _write_cleanup_state(self.path, json.dumps(payload, separators=(",", ":")))

    def publish_survival(self) -> None:
        if self.failed or self._expected() != "survival_published":
            raise RuntimeError("cleanup_probe_state_sequence_invalid")
        _write_cleanup_state(self.path, self.token)
        self.phase = "survival_published"


def _read_cleanup_probe_failure(path: Path, token: str, max_bytes: int) -> dict[str, str] | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > min(max_bytes, _CLEANUP_STATE_MAX):
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "token",
        "phase",
        "failure_phase",
        "probe_exit_class",
    }:
        return None
    phase = payload.get("phase")
    failure_phase = payload.get("failure_phase")
    classification = payload.get("probe_exit_class")
    completed = -1 if phase is None else _CLEANUP_PHASES.index(phase) if phase in _CLEANUP_PHASES else -2
    if (
        payload.get("token") != token
        or not isinstance(failure_phase, str)
        or not isinstance(classification, str)
        or failure_phase not in _CLEANUP_PHASES
        or classification not in _CLEANUP_FAILURES_BY_PHASE.get(failure_phase, ())
        or completed + 1 != _CLEANUP_PHASES.index(failure_phase)
    ):
        return None
    return {"failure_phase": failure_phase, "probe_exit_class": classification}


def activate_child_from_env() -> str:
    kind = os.environ.get(OWNER_KIND_ENV, "")
    ready = Path(os.environ.get(OWNER_READY_ENV, ""))
    token = os.environ.get(OWNER_TOKEN_ENV, "")
    if kind == PosixOwner.kind:
        if os.name == "nt" or os.getpgrp() != os.getpid():
            raise OwnerActivationError("owner_not_activated")
        _publish_ready(ready, token)
        return kind
    if kind != WindowsJobOwner.kind or os.name != "nt":
        raise OwnerActivationError("owner_not_activated")
    _activate_windows_child(_kernel32(), os.environ.get(OWNER_NAME_ENV, ""), ready, token)
    return kind


def _activate_windows_child(kernel: Any, name: str, ready: Path, token: str) -> None:
    handle = kernel.OpenJobObjectW(0x0001 | 0x0004, False, name)
    if not handle:
        raise OwnerActivationError("owner_not_activated")
    prepared = ready.with_name(f".{ready.name}.{os.getpid()}.tmp")
    try:
        if ready.exists() or ready.is_symlink() or not _TOKEN.fullmatch(token):
            raise OwnerActivationError("owner_not_activated")
        if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
            raise OwnerActivationError("owner_not_activated")
        with prepared.open("x", encoding="utf-8") as stream:
            stream.write(token)
        if not kernel.CloseHandle(handle):
            raise OwnerActivationError("owner_not_activated")
        handle = None
        prepared.replace(ready)
    except OSError as error:
        raise OwnerActivationError("owner_not_activated") from error
    finally:
        prepared.unlink(missing_ok=True)
        if handle:
            kernel.CloseHandle(handle)


def pid_exists(pid: int) -> bool:
    if os.name == "nt":
        kernel = _kernel32()
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return False
            raise OSError("process_state_unavailable")
        exit_code = ctypes.c_ulong()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_pid_gone(pid: int, timeout: float = 5) -> bool:
    return _wait_until(lambda: not pid_exists(pid), timeout)


def observed_pid(path: Path, token: str, max_bytes: int) -> int | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("token") != token:
        return None
    pid = payload.get("pid")
    return pid if isinstance(pid, int) and pid > 0 else None


def force_pid_gone(pid: int) -> bool:
    try:
        if not pid_exists(pid):
            return True
    except OSError:
        pass
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except OSError:
            return False
    try:
        return wait_pid_gone(pid)
    except OSError:
        return False


def _probe_failure(state: _CleanupProbeState, phase: str, classification: str) -> NoReturn:
    try:
        state.fail(phase, classification)
    except OSError as error:
        raise RuntimeError("cleanup_probe_evidence_write_failed") from error
    raise RuntimeError(classification)


def _start_probe_launcher(args: Any, state: _CleanupProbeState, env: dict[str, str]) -> subprocess.Popen[bytes]:
    try:
        launcher = subprocess.Popen(
            [str(args.node.resolve()), str(args.launcher.resolve())],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        _probe_failure(state, "launcher_started", "launcher_not_startable")
    if launcher.stdin is None:
        with suppress(OSError):
            launcher.kill()
        _probe_failure(state, "launcher_started", "launcher_capture_unavailable")
    if launcher.poll() is not None:
        _probe_failure(state, "launcher_started", "launcher_exited")
    state.advance("launcher_started")
    return launcher


def _observe_probe_server(
    args: Any, state: _CleanupProbeState, launcher: subprocess.Popen[bytes], max_bytes: int, timeout: float
) -> int:
    deadline = time.monotonic() + timeout
    server_pid = observed_pid(args.pid_file, args.token, max_bytes)
    while time.monotonic() < deadline and server_pid is None:
        if launcher.poll() is not None:
            _probe_failure(state, "server_observed", "launcher_exited")
        time.sleep(0.02)
        server_pid = observed_pid(args.pid_file, args.token, max_bytes)
    if server_pid is None:
        _probe_failure(state, "server_observed", "server_unobserved")
    state.advance("server_observed")
    return server_pid


def _start_stdin_keeper(state: _CleanupProbeState, launcher: subprocess.Popen[bytes]) -> subprocess.Popen[bytes]:
    try:
        keeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=launcher.stdin,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        _probe_failure(state, "stdin_keeper_started", "stdin_keeper_not_startable")
    if keeper.poll() is not None:
        _probe_failure(state, "stdin_keeper_started", "stdin_keeper_exited")
    state.advance("stdin_keeper_started")
    return keeper


def _terminate_probe_launcher(
    state: _CleanupProbeState, launcher: subprocess.Popen[bytes], keeper: subprocess.Popen[bytes]
) -> None:
    if keeper.poll() is not None:
        _probe_failure(state, "launcher_terminated", "stdin_keeper_exited")
    try:
        if launcher.stdin is None:
            raise OSError("cleanup_probe_capture_unavailable")
        launcher.stdin.close()
        launcher.kill()
        launcher.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        _probe_failure(state, "launcher_terminated", "launcher_terminate_failed")
    state.advance("launcher_terminated")


def _confirm_probe_server(state: _CleanupProbeState, keeper: subprocess.Popen[bytes], server_pid: int) -> None:
    if keeper.poll() is not None:
        _probe_failure(state, "server_alive", "stdin_keeper_exited")
    try:
        alive = pid_exists(server_pid)
    except OSError:
        _probe_failure(state, "server_alive", "server_state_unavailable")
    if not alive:
        _probe_failure(state, "server_alive", "server_not_alive_after_launcher")
    state.advance("server_alive")


def cleanup_probe_child(args: Any, max_bytes: int, phase_timeout: float) -> int:
    state = _CleanupProbeState(args.survival_file, args.token)
    try:
        activate_child_from_env()
    except OwnerActivationError:
        _probe_failure(state, "owner_activated", "owner_activation_failed")
    state.advance("owner_activated")
    python = args.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = dict(os.environ)
    env.update(
        KINOCUT_MCPB_PYTHON=str(python),
        KINOCUT_MCPB_SUPERVISED_PROCESS_TREE="1",
        KINOCUT_MCPB_SUPERVISED_PID_FILE=str(args.pid_file),
        KINOCUT_MCPB_SUPERVISED_TOKEN=args.token,
    )
    launcher = _start_probe_launcher(args, state, env)
    server_pid = _observe_probe_server(args, state, launcher, max_bytes, phase_timeout)
    keeper = _start_stdin_keeper(state, launcher)
    _terminate_probe_launcher(state, launcher, keeper)
    _confirm_probe_server(state, keeper, server_pid)
    try:
        state.publish_survival()
    except (OSError, RuntimeError):
        _probe_failure(state, "survival_published", "survival_publish_failed")
    return 0


def cleanup_probe_payload(args: Any, runner: Any, script: Path, max_bytes: int) -> dict[str, str]:
    work = Path(tempfile.mkdtemp(prefix="mcpb-cleanup-probe-"))
    pid_file = work / "server.json"
    survival_file = work / "server-survived"
    token = secrets.token_hex(32)
    server_pid = None
    payload = {
        "artifact_kind": "mcpb_cleanup_probe",
        "os": args.os,
        "architecture": args.architecture,
        "status": "failed",
        "cleanup": "failed",
        "exit_class": "cleanup_probe_failed",
        "topology": "launcher_to_mcp_server",
        "false_success_suppressed": "failed",
    }
    command = [
        sys.executable,
        str(script),
        "cleanup-probe-child",
        "--launcher",
        str(args.launcher),
        "--venv",
        str(args.venv),
        "--node",
        str(args.node),
        "--pid-file",
        str(pid_file),
        "--survival-file",
        str(survival_file),
        "--token",
        token,
    ]
    try:
        runner(command, env=dict(os.environ), timeout=30)
    except RuntimeError as error:
        payload["exit_class"] = getattr(error, "classification", "cleanup_probe_failed")
        payload["cleanup"] = getattr(error, "cleanup", "failed")
        server_pid = observed_pid(pid_file, token, max_bytes)
        survived = _read_ready(survival_file, token)
        try:
            clean = server_pid is not None and wait_pid_gone(server_pid)
        except OSError:
            clean = False
        if (
            payload["exit_class"] == "descendant_survived_command"
            and payload["cleanup"] == "passed"
            and survived
            and clean
        ):
            payload.update(status="passed", false_success_suppressed="passed")
    finally:
        if server_pid is None:
            server_pid = observed_pid(pid_file, token, max_bytes)
        if server_pid is not None:
            try:
                alive = pid_exists(server_pid)
            except OSError:
                alive = True
            if alive and not force_pid_gone(server_pid):
                payload.update(status="failed", cleanup="failed")
        if payload["status"] != "passed":
            evidence = _read_cleanup_probe_failure(survival_file, token, max_bytes)
            payload.update(
                evidence
                or {
                    "failure_phase": "evidence_unavailable",
                    "probe_exit_class": "cleanup_probe_evidence_unknown",
                }
            )
        shutil.rmtree(work, ignore_errors=True)
    return payload
