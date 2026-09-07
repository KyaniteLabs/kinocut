"""Fail-closed contracts for the three-file staged MCPB artifact."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import importlib.util
import json
import os
import stat
import sys
import time
import types
import zipfile
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
LABEL = "user-configured-local-access"


def _builder():
    spec = importlib.util.spec_from_file_location("build_mcpb", ROOT / "scripts" / "build-mcpb.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ci_helper():
    spec = importlib.util.spec_from_file_location("mcpb_ci", ROOT / ".github" / "scripts" / "mcpb-ci.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_built_archive_has_exact_inventory_digest_and_valid_extracted_manifest(tmp_path: Path) -> None:
    builder = _builder()

    bundle = builder.build_bundle(tmp_path)
    receipt = json.loads((tmp_path / "mcpb-build-receipt.json").read_text(encoding="utf-8"))
    independent_receipt = builder.audit_bundle(bundle)

    assert receipt["archive_inventory"] == ["README.md", "manifest.json", "server/launcher.js"]
    assert len(receipt["archive_sha256"]) == 64
    assert receipt["source_manifest_valid"] is True
    assert receipt["extracted_manifest_valid"] is True
    assert independent_receipt["source_manifest_valid"] is False
    assert independent_receipt["extracted_manifest_valid"] is True


def test_ci_command_capture_stops_during_output_overflow() -> None:
    helper = _ci_helper()
    started = time.monotonic()

    with pytest.raises(RuntimeError, match="command_output_overflow"):
        helper._run([sys.executable, "-c", "import sys; sys.stdout.write('x' * 100_000)"])

    assert time.monotonic() - started < 5


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_ci_timeout_stops_owned_descendant_tree(tmp_path: Path) -> None:
    helper = _ci_helper()
    pid_file = tmp_path / "descendant.pid"
    source = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid),encoding='utf-8');"
        "time.sleep(60)"
    )

    with pytest.raises(helper.BoundedProcessError) as caught:
        helper._run([sys.executable, "-c", source], timeout=1)

    assert caught.value.classification == "command_timeout"
    assert caught.value.cleanup == "passed"
    assert pid_file.is_file()
    assert helper._owner_helper().wait_pid_gone(int(pid_file.read_text(encoding="utf-8")))


def test_cleanup_probe_records_observed_launcher_loss_and_suppresses_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _ci_helper()
    receipt = tmp_path / "cleanup.json"
    owner_helper = helper._owner_helper()
    monkeypatch.setattr(owner_helper, "wait_pid_gone", lambda _pid: True)
    monkeypatch.setattr(owner_helper, "pid_exists", lambda _pid: False)

    def fail_after_observation(command: list[str], **_kwargs: object) -> None:
        survival_file = Path(command[command.index("--survival-file") + 1])
        token = command[command.index("--token") + 1]
        success = {"token": token, "pid": 12345, "phase": "survival_published"}
        survival_file.write_text(json.dumps(success), encoding="utf-8")
        raise helper.BoundedProcessError("descendant_survived_command", "passed")

    monkeypatch.setattr(helper, "_run_owned", fail_after_observation)
    args = argparse.Namespace(
        os="test-os",
        architecture="test-arch",
        receipt=receipt,
        launcher=tmp_path / "launcher.js",
        venv=tmp_path / "venv",
        node=tmp_path / "node",
    )

    result = helper.cleanup_probe(args)

    assert result == 0
    assert json.loads(receipt.read_text(encoding="utf-8")) == {
        "artifact_kind": "mcpb_cleanup_probe",
        "os": "test-os",
        "architecture": "test-arch",
        "status": "passed",
        "cleanup": "passed",
        "exit_class": "descendant_survived_command",
        "topology": "launcher_to_mcp_server",
        "false_success_suppressed": "passed",
    }


def test_cleanup_probe_rejects_descendant_without_server_survival_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _ci_helper()
    receipt = tmp_path / "cleanup.json"
    owner_helper = helper._owner_helper()
    monkeypatch.setattr(owner_helper, "wait_pid_gone", lambda _pid: True)
    monkeypatch.setattr(owner_helper, "pid_exists", lambda _pid: False)

    def fail_without_survival_proof(command: list[str], **_kwargs: object) -> None:
        pid_file = Path(command[command.index("--pid-file") + 1])
        token = command[command.index("--token") + 1]
        pid_file.write_text(json.dumps({"token": token, "pid": 12345}), encoding="utf-8")
        raise helper.BoundedProcessError("descendant_survived_command", "passed")

    monkeypatch.setattr(helper, "_run_owned", fail_without_survival_proof)
    args = argparse.Namespace(
        os="test-os",
        architecture="test-arch",
        receipt=receipt,
        launcher=tmp_path / "launcher.js",
        venv=tmp_path / "venv",
        node=tmp_path / "node",
    )

    with pytest.raises(RuntimeError, match="cleanup_probe_failed"):
        helper.cleanup_probe(args)

    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["status"] == "failed"
    assert failure["false_success_suppressed"] == "failed"


def test_runtime_failure_receipt_preserves_phase_classification_and_completed_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _ci_helper()
    monkeypatch.setattr(helper, "_reexec_runtime", lambda _args: None)
    receipt = tmp_path / "runtime.json"
    args = argparse.Namespace(
        mode="core",
        venv=tmp_path / "venv",
        bundle=tmp_path / "missing.mcpb",
        archive_sha="b" * 64,
        source_sha="a" * 40,
        os="linux",
        architecture="X64",
        receipt=receipt,
    )

    assert helper.runtime(args) == 1
    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["failure_phase"] == "artifact_validation"
    assert failure["exit_class"] == "filenotfounderror"
    assert failure["gates"] == {}
    assert failure["cleanup"] == "not_observed"


def test_runtime_supervisor_promotes_cleanup_only_after_same_host_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _ci_helper()
    runtime_receipt = tmp_path / "runtime.json"
    cleanup_receipt = tmp_path / "cleanup.json"
    runtime_receipt.write_text(
        json.dumps({"status": "passed", "cleanup": "session_closed", "process_owner": "test_owner", "gates": {}}),
        encoding="utf-8",
    )
    cleanup_receipt.write_text(
        json.dumps(
            {
                "artifact_kind": "mcpb_cleanup_probe",
                "os": "linux",
                "architecture": "X64",
                "status": "passed",
                "cleanup": "passed",
                "exit_class": "descendant_survived_command",
                "topology": "launcher_to_mcp_server",
                "false_success_suppressed": "passed",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("KINOCUT_MCPB_RUNTIME_CHILD", raising=False)
    monkeypatch.setattr(helper, "_run_owned", lambda *_args, **_kwargs: ("", "test_owner"))
    args = argparse.Namespace(
        mode="core",
        venv=tmp_path / "venv",
        receipt=runtime_receipt,
        cleanup_probe_receipt=cleanup_receipt,
        os="linux",
        architecture="X64",
    )

    assert helper._reexec_runtime(args) == 0
    promoted = json.loads(runtime_receipt.read_text(encoding="utf-8"))
    assert promoted["cleanup"] == "passed"
    assert promoted["gates"]["cleanup_probe"] == "passed"


def test_runtime_supervisor_rejects_wrong_host_cleanup_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _ci_helper()
    runtime_receipt = tmp_path / "runtime.json"
    cleanup_receipt = tmp_path / "cleanup.json"
    runtime_receipt.write_text(
        json.dumps({"status": "passed", "cleanup": "session_closed", "process_owner": "test_owner", "gates": {}}),
        encoding="utf-8",
    )
    cleanup_receipt.write_text(
        json.dumps(
            {
                "artifact_kind": "mcpb_cleanup_probe",
                "os": "windows",
                "architecture": "X64",
                "status": "passed",
                "cleanup": "passed",
                "exit_class": "descendant_survived_command",
                "topology": "launcher_to_mcp_server",
                "false_success_suppressed": "passed",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("KINOCUT_MCPB_RUNTIME_CHILD", raising=False)
    monkeypatch.setattr(helper, "_run_owned", lambda *_args, **_kwargs: ("", "test_owner"))
    args = argparse.Namespace(
        mode="core",
        venv=tmp_path / "venv",
        receipt=runtime_receipt,
        cleanup_probe_receipt=cleanup_receipt,
        os="linux",
        architecture="X64",
    )

    assert helper._reexec_runtime(args) == 1
    rejected = json.loads(runtime_receipt.read_text(encoding="utf-8"))
    assert rejected["status"] == "failed"
    assert rejected["failure_phase"] == "cleanup_probe"


def test_runtime_supervisor_never_preserves_child_success_after_tree_failure(tmp_path: Path) -> None:
    helper = _ci_helper()
    receipt = tmp_path / "runtime.json"
    receipt.write_text(json.dumps({"status": "passed", "cleanup": "session_closed", "gates": {}}), encoding="utf-8")
    args = argparse.Namespace(
        mode="core",
        receipt=receipt,
        source_sha="a" * 40,
        archive_sha="b" * 64,
        os="linux",
        architecture="X64",
    )

    helper._supervised_failure(args, helper.BoundedProcessError("descendant_survived_command", "passed"))

    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["status"] == "failed"
    assert failure["cleanup"] == "passed"
    assert failure["failure_phase"] == "runtime_supervisor"
    assert failure["exit_class"] == "descendant_survived_command"


class _FakeOwner:
    def __init__(self, *, activated: bool = True) -> None:
        self.activated = activated
        self.bound = False
        self.alive = True
        self.terminated = False

    def bind(self, _process: object) -> None:
        self.bound = True

    def wait_activated(self, _process: object, _timeout: float = 5) -> bool:
        return self.activated

    def active(self) -> bool:
        return self.alive

    def terminate(self) -> bool:
        self.terminated = True
        self.alive = False
        return True


def test_owned_run_detects_descendant_after_root_exits() -> None:
    helper = _ci_helper()
    owner = _FakeOwner()

    with pytest.raises(helper.BoundedProcessError) as caught:
        helper._run([sys.executable, "-c", "pass"], owner=owner)

    assert owner.bound is True
    assert owner.terminated is True
    assert caught.value.classification == "descendant_survived_command"
    assert caught.value.cleanup == "passed"


def test_owned_run_fails_closed_when_child_never_activates() -> None:
    helper = _ci_helper()
    owner = _FakeOwner(activated=False)

    with pytest.raises(helper.BoundedProcessError) as caught:
        helper._run([sys.executable, "-c", "import time; time.sleep(1)"], owner=owner)

    assert owner.terminated is True
    assert caught.value.classification == "owner_not_activated"


class _FakeKernel:
    def __init__(self, *, close_ok: bool = True, query_ok: bool = True, terminate_ok: bool = True) -> None:
        self.active = 1
        self.close_ok = close_ok
        self.query_ok = query_ok
        self.terminate_ok = terminate_ok
        self.calls: list[str] = []

    def CreateJobObjectW(self, _security: object, _name: str) -> int:
        self.calls.append("create")
        return 101

    def SetInformationJobObject(self, *_args: object) -> int:
        self.calls.append("configure")
        return 1

    def QueryInformationJobObject(self, _handle: object, _kind: object, target: object, *_args: object) -> int:
        if not self.query_ok:
            return 0
        info = ctypes.cast(target, ctypes.POINTER(ctypes.c_byte * 48))
        accounting = ctypes.cast(info, ctypes.POINTER(_ci_helper()._owner_helper()._Accounting)).contents
        accounting.ActiveProcesses = self.active
        return 1

    def TerminateJobObject(self, *_args: object) -> int:
        self.calls.append("terminate")
        if not self.terminate_ok:
            return 0
        self.active = 0
        return 1

    def CloseHandle(self, _handle: object) -> int:
        self.calls.append("close")
        return int(self.close_ok)

    def OpenJobObjectW(self, *_args: object) -> int:
        self.calls.append("open")
        return 202

    def AssignProcessToJobObject(self, *_args: object) -> int:
        self.calls.append("assign")
        return 1

    def GetCurrentProcess(self) -> int:
        return 303


def test_windows_job_owner_observes_and_terminates_descendants(tmp_path: Path) -> None:
    owner_module = _ci_helper()._owner_helper()
    kernel = _FakeKernel()
    owner = owner_module.WindowsJobOwner(tmp_path, kernel=kernel)

    assert owner.active() is True
    assert owner.terminate() is True
    assert owner.active() is False
    assert owner.close() is True
    assert kernel.calls == ["create", "configure", "terminate", "close"]


def test_windows_child_closes_join_handle_before_publishing_ready(tmp_path: Path) -> None:
    owner_module = _ci_helper()._owner_helper()
    kernel = _FakeKernel()
    ready = tmp_path / "ready"
    token = "a" * 64

    owner_module._activate_windows_child(kernel, "job", ready, token)

    assert ready.read_text(encoding="utf-8") == token
    assert kernel.calls == ["open", "assign", "close"]


def test_windows_child_close_failure_never_publishes_ready(tmp_path: Path) -> None:
    owner_module = _ci_helper()._owner_helper()
    kernel = _FakeKernel(close_ok=False)
    ready = tmp_path / "ready"

    with pytest.raises(owner_module.OwnerActivationError, match="owner_not_activated"):
        owner_module._activate_windows_child(kernel, "job", ready, "a" * 64)

    assert not ready.exists()
    assert kernel.calls == ["open", "assign", "close", "close"]


@pytest.mark.parametrize("failure", ["query", "terminate", "close"])
def test_windows_job_owner_failures_never_report_cleanup(tmp_path: Path, failure: str) -> None:
    owner_module = _ci_helper()._owner_helper()
    kernel = _FakeKernel(query_ok=failure != "query", terminate_ok=failure != "terminate", close_ok=failure != "close")
    owner = owner_module.WindowsJobOwner(tmp_path, kernel=kernel)

    if failure == "query":
        with pytest.raises(OSError, match="job_query_failed"):
            owner.active()
        assert owner.terminate() is False
    elif failure == "terminate":
        assert owner.terminate() is False
    else:
        assert owner.close() is False


def test_windows_pid_fallback_uses_taskkill_without_unix_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_module = _ci_helper()._owner_helper()
    calls: list[list[str]] = []
    monkeypatch.setattr(owner_module, "pid_exists", lambda _pid: bool(not calls))
    monkeypatch.setattr(owner_module.os, "name", "nt")

    def fake_run(command: list[str], **_kwargs: object) -> types.SimpleNamespace:
        calls.append(command)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(owner_module.subprocess, "run", fake_run)

    assert owner_module.force_pid_gone(12345) is True
    assert calls == [["taskkill", "/PID", "12345", "/T", "/F"]]


class _AsyncContext:
    def __init__(
        self,
        value: object,
        *,
        enter_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.value = value
        self.enter_error = enter_error
        self.close_error = close_error

    async def __aenter__(self) -> object:
        if self.enter_error is not None:
            raise self.enter_error
        return self.value

    async def __aexit__(self, *_args: object) -> None:
        if self.close_error is not None:
            raise self.close_error


class _FakeSession:
    def __init__(self, fail_operation: str | None) -> None:
        self.fail_operation = fail_operation
        self.video_info_calls = 0

    async def initialize(self) -> None:
        if self.fail_operation == "initialize":
            raise RuntimeError("initialize_broke")

    async def list_tools(self) -> object:
        if self.fail_operation == "list_tools":
            raise RuntimeError("list_broke")
        names = ("video_info", "video_ai_transcribe", "hyperframes_doctor", "video_ai_scene_detect")
        return types.SimpleNamespace(tools=[types.SimpleNamespace(name=name) for name in names])

    async def call_tool(self, name: str, _arguments: object) -> object:
        if self.fail_operation == name:
            raise RuntimeError("tool_broke")
        if name == "video_info":
            self.video_info_calls += 1
            if self.fail_operation == "session_reuse" and self.video_info_calls == 3:
                raise RuntimeError("reuse_broke")
        payload: dict[str, object] = {"success": True}
        if name == "video_ai_transcribe":
            payload = {"success": False, "error": {"code": "missing_whisper", "message": "[transcribe] install"}}
        if name == "hyperframes_doctor":
            payload = {"success": False, "error": {"code": "hyperframes_not_found"}}
        return types.SimpleNamespace(structuredContent=payload, content=[])


def _install_fake_mcp(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_operation: str | None,
    shutdown_error: BaseException | None = None,
) -> None:
    session = _FakeSession(fail_operation)
    mcp = types.ModuleType("mcp")
    client_enter_error = RuntimeError("client_broke") if fail_operation == "client_start" else None
    mcp.ClientSession = lambda _read, _write: _AsyncContext(  # type: ignore[attr-defined]
        session, enter_error=client_enter_error, close_error=shutdown_error
    )
    client = types.ModuleType("mcp.client")
    stdio = types.ModuleType("mcp.client.stdio")
    stdio.StdioServerParameters = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    stdio_enter_error = RuntimeError("stdio_broke") if fail_operation == "stdio_start" else None
    stdio.stdio_client = lambda _params, **_kwargs: _AsyncContext(  # type: ignore[attr-defined]
        (object(), object()), enter_error=stdio_enter_error
    )
    monkeypatch.setitem(sys.modules, "mcp", mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio)


def _runtime_session_args(tmp_path: Path) -> argparse.Namespace:
    executable = Path(sys.executable)
    return argparse.Namespace(
        venv=executable.parent.parent,
        ffmpeg=executable,
        node=executable,
        launcher=executable,
        hyperframes="absent",
        mode="core",
    )


def test_runtime_session_reports_initialize_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _ci_helper()
    _install_fake_mcp(monkeypatch, fail_operation="initialize")
    progress = {"phase": "mcp_session", "gates": {}, "session_closed": False}

    with pytest.raises(RuntimeError, match="initialize_broke"):
        asyncio.run(helper._runtime_session(_runtime_session_args(tmp_path), tmp_path / "media.mp4", progress))

    assert progress["phase"] == "mcp_initialize"
    assert progress["session_closed"] is True


@pytest.mark.parametrize(
    ("operation", "phase", "completed"),
    [
        ("stdio_start", "mcp_stdio_start", set()),
        ("client_start", "mcp_client_start", set()),
        ("video_ai_transcribe", "mcp_call_video_ai_transcribe", {"initialize", "list_tools", "core_call"}),
        (
            "session_reuse",
            "mcp_session_reuse",
            {
                "initialize",
                "list_tools",
                "core_call",
                "missing_whisper",
                "core_after_missing_whisper",
                "hyperframes_not_found",
            },
        ),
    ],
)
def test_runtime_session_reports_exact_failed_transition_and_completed_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    phase: str,
    completed: set[str],
) -> None:
    helper = _ci_helper()
    _install_fake_mcp(monkeypatch, fail_operation=operation)
    progress = {"phase": "mcp_session", "gates": {}, "session_closed": False}

    with pytest.raises(RuntimeError):
        asyncio.run(helper._runtime_session(_runtime_session_args(tmp_path), tmp_path / "media.mp4", progress))

    assert progress["phase"] == phase
    assert set(progress["gates"]) == completed
    assert progress["session_closed"] is True


def test_runtime_session_preserves_primary_tool_error_when_shutdown_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _ci_helper()
    _install_fake_mcp(monkeypatch, fail_operation="video_info", shutdown_error=TimeoutError("private shutdown"))
    progress = {"phase": "mcp_session", "gates": {}, "session_closed": False}

    with pytest.raises(RuntimeError, match="tool_broke"):
        asyncio.run(helper._runtime_session(_runtime_session_args(tmp_path), tmp_path / "media.mp4", progress))

    assert progress["phase"] == "mcp_call_video_info"
    assert progress["shutdown_failure_phase"] == "mcp_shutdown"
    assert progress["shutdown_exit_class"] == "timeouterror"
    assert "private shutdown" not in json.dumps(progress)


def test_runtime_session_reports_shutdown_as_primary_when_calls_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _ci_helper()
    _install_fake_mcp(monkeypatch, fail_operation=None, shutdown_error=TimeoutError("private shutdown"))
    progress = {"phase": "mcp_session", "gates": {}, "session_closed": False}

    with pytest.raises(TimeoutError, match="private shutdown"):
        asyncio.run(helper._runtime_session(_runtime_session_args(tmp_path), tmp_path / "media.mp4", progress))

    assert progress["phase"] == "mcp_shutdown"
    assert progress["shutdown_failure_phase"] == "mcp_shutdown"
    assert progress["shutdown_exit_class"] == "timeouterror"
    receipt = helper._runtime_failure_receipt(
        argparse.Namespace(mode="core", source_sha="a" * 40, archive_sha="b" * 64, os="linux", architecture="X64"),
        progress,
        TimeoutError("private shutdown"),
    )
    assert receipt["failure_phase"] == "mcp_shutdown"
    assert receipt["shutdown_exit_class"] == "timeouterror"
    assert "private shutdown" not in json.dumps(receipt)


def test_ci_extraction_reuses_audit_and_refuses_existing_destination(tmp_path: Path) -> None:
    bundle = _builder().build_bundle(tmp_path / "dist")
    helper = _ci_helper()
    destination = tmp_path / "unpacked"

    inventory = helper._extract(bundle, destination)

    assert inventory == ["README.md", "manifest.json", "server/launcher.js"]
    assert (
        sorted(path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file())
        == inventory
    )
    with pytest.raises(RuntimeError, match="destination_exists"):
        helper._extract(bundle, destination)


def test_builder_rejects_symlinked_or_escaping_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder = _builder()
    source_root = tmp_path / "mcpb"
    (source_root / "server").mkdir(parents=True)
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    (source_root / "manifest.json").write_text(json.dumps(builder._load_manifest()), encoding="utf-8")
    (source_root / "README.md").write_text("readme", encoding="utf-8")
    (source_root / "server" / "launcher.js").symlink_to(outside)
    monkeypatch.setattr(builder, "MCPB_DIR", source_root)

    with pytest.raises(ValueError, match="regular non-symlink"):
        builder.build_bundle(tmp_path / "dist")


@pytest.mark.parametrize(
    "name",
    ["/manifest.json", "../manifest.json", "server\\launcher.js", "extra.txt"],
)
def test_archive_audit_rejects_unsafe_or_unlisted_names(tmp_path: Path, name: str) -> None:
    builder = _builder()
    bundle = tmp_path / "hostile.mcpb"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(name, b"x")

    with pytest.raises(ValueError):
        builder.audit_bundle(bundle)


def test_archive_audit_rejects_duplicate_and_non_regular_members(tmp_path: Path) -> None:
    builder = _builder()
    duplicate = tmp_path / "duplicate.mcpb"
    with pytest.warns(UserWarning, match="Duplicate name"), zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("manifest.json", b"{}")
    with pytest.raises(ValueError, match="duplicate"):
        builder.audit_bundle(duplicate)

    linked = tmp_path / "linked.mcpb"
    info = zipfile.ZipInfo("server/launcher.js")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(linked, "w") as archive:
        archive.writestr(info, b"../../outside")
    with pytest.raises(ValueError, match="regular file"):
        builder.audit_bundle(linked)


def test_public_surfaces_use_the_selected_local_access_label() -> None:
    paths = [
        ROOT / "mcpb" / "manifest.json",
        ROOT / "mcpb" / "README.md",
        ROOT / "docs" / "MCPB.md",
        ROOT / "README.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert LABEL in text, path
        assert "not a sandbox" in text.lower(), path
        assert "unsigned" in text.lower(), path

    operator_docs = paths[2].read_text(encoding="utf-8").lower()
    assert "staged publication does not depend on native bundle completion" in operator_docs
    native_docs = (ROOT / "docs" / "MCPB_NATIVE_GATES.md").read_text(encoding="utf-8")
    assert "future native-only" in native_docs.lower()
    status = (ROOT / "docs" / "status" / "2026-08-12-product-pipeline-complete.md").read_text(encoding="utf-8")
    assert "Correction (2026-09-06)" in status
    assert "planning evidence" in status


def test_official_validator_is_exactly_locked_for_ci() -> None:
    tool_dir = ROOT / "tools" / "mcpb-validator"
    package = json.loads((tool_dir / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((tool_dir / "package-lock.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["dependencies"] == {"@anthropic-ai/mcpb": "2.1.2"}
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["dependencies"] == package["dependencies"]
    assert lock["packages"]["node_modules/@anthropic-ai/mcpb"]["version"] == "2.1.2"


def test_official_gate_rejects_a_different_version_containing_locked_digits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _ci_helper()
    bundle = _builder().build_bundle(tmp_path / "dist")
    wheel = tmp_path / "candidate.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(helper, "_run", lambda command, **_kwargs: "mcpb 12.1.2")
    args = argparse.Namespace(
        bundle=bundle,
        wheel=wheel,
        validator=tmp_path / "validator",
        source_sha="a" * 40,
        receipt=tmp_path / "receipt.json",
    )

    with pytest.raises(RuntimeError, match="validator_version_mismatch"):
        helper.official(args)


def test_mcpb_deadline_preserves_task_affinity_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _ci_helper()

    def force_task(awaitable, **_kwargs):
        return asyncio.create_task(awaitable)

    @asynccontextmanager
    async def task_affine():
        assert (entered := asyncio.current_task()) is not None
        yield
        assert asyncio.current_task() is entered

    async def exercise() -> None:
        stack = AsyncExitStack()
        await helper._deadline(stack.enter_async_context(task_affine()))
        await helper._deadline(stack.aclose())
        with pytest.raises(TimeoutError):
            await helper._deadline(asyncio.sleep(1))

    monkeypatch.setattr(helper, "PHASE_TIMEOUT", 0.01)
    monkeypatch.setattr(helper.asyncio, "wait_for", force_task)
    asyncio.run(exercise())


def test_staged_mcpb_workflow_has_exact_evidence_boundaries() -> None:
    workflow = (ROOT / ".github" / "workflows" / "mcpb.yml").read_text(encoding="utf-8")
    helper = (ROOT / ".github" / "scripts" / "mcpb-ci.py").read_text(encoding="utf-8")

    assert "pull_request:" in workflow and "push:" in workflow and "workflow_dispatch:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert workflow.count("timeout-minutes:") == 4
    assert "ubuntu-24.04" in workflow and "macos-latest" in workflow and "windows-latest" in workflow
    assert "npm ci --ignore-scripts" in workflow
    assert "@anthropic-ai/mcpb" not in workflow
    assert "python -m build --wheel" in workflow
    assert "pip install -e" not in workflow
    assert "--extra ai-scene" in workflow
    assert "hyperframes@0.8.30" in workflow
    assert "--require-ready ci_validated" in workflow
    assert "native-launcher" not in workflow
    assert "secrets." not in workflow
    assert "PYTHONNOUSERSITE" in helper and 'env.pop("PYTHONPATH"' in helper
    assert "async with asyncio.timeout(PHASE_TIMEOUT)" in helper
    assert "MAX_CAPTURE" in helper
    assert "KINOCUT_MCPB_RUNTIME_CHILD" in helper
    assert '"-m", "kinocut", "doctor", "--json"' in helper
    assert "core_after_missing_whisper" in helper
    assert "missing_whisper" in helper and "hyperframes_not_found" in helper
    assert "cleanup-probe" in workflow
    assert "--cleanup-probe-receipt" in workflow
    assert "mcpb-cleanup-${{ matrix.os }}.json" in workflow
