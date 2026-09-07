#!/usr/bin/env python3
"""Supervise one authenticated Windows collection diagnostic."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PRODUCT_COMMIT = "3a940a9e0fb1a5b447ef64cc5ff1b3f8f06cf306"
PRODUCT_TREE = "6f9ca184f2951acd09b2109fb7c3c9dc0184ff75"
SUPERVISOR_COMMIT = "90ad16b33e6449035e9aef02e4563490c3d9c66b"
SUPERVISOR_TREE = "f3ab49aa37cfaf9233c17ac240ae1f80f0dd3a82"
SUPERVISOR_CI_SHA256 = "18aa3333ec593b1aac6851e71b829a315bd6a58064817f56886e5a9ddf86548f"
SUPERVISOR_OWNER_SHA256 = "f19d0446ef473d233480887fd4993565e83c953ae7d3ac0adca6253f5c314aff"
WRAPPER_COMMIT = "77728c2a369073aaccabd2e04717b61929d19119"
WRAPPER_TREE = "390c9b92c37729ca95ce4960ced3038472d19dd8"
WRAPPER_BLOB = "a2a0a4ad5d4c82636571f06c0974110294102e52"
WRAPPER_SHA256 = "cdfa289f382ef4960c10a31e70b6cbbe165d3af593605c4b6617bf80cde08821"
EXPECTED_BRANCH = "ci/windows-supervised-collection-20260907"
EXPECTED_TESTS = 5370
MAX_INVENTORY_BYTES = 256 * 1024
MAX_RECEIPT_BYTES = 128 * 1024
MAX_CAPTURE_BYTES = 256 * 1024
_SHA = re.compile(r"[0-9a-f]{40,64}")
_SAFE_METADATA = re.compile(r"[A-Za-z0-9._-]{1,64}")
EVENTS_SHA256 = "b5d41fbf92819cf1f2c9997edd11c82b5ade53cde5bc88c2380f806a4b5be492"
EVENTS_BLOB = "c98224dda66d12040a65eda7f7317758a970a176"
OWNER_NAME_ENV = "KINOCUT_MCPB_OWNER_NAME"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
JOB_OBJECT_QUERY = 0x0004
ERROR_INVALID_PARAMETER = 87
STILL_ACTIVE = 259
SELF_TEST_BYTES = 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError("module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_events() -> Any:
    path = Path(__file__).with_name("windows_collection_events.py")
    if path.is_symlink() or not path.is_file() or _sha256(path) != EVENTS_SHA256:
        raise RuntimeError("event_source_identity_mismatch")
    return _load_module(path, "windows_collection_events")


EVENTS = _load_events()
DiagnosticError = EVENTS.DiagnosticError


def _require_hash(path: Path, expected: str) -> None:
    if path.is_symlink() or not path.is_file() or _sha256(path) != expected:
        raise DiagnosticError("source_identity_mismatch")


def _activate_owner(path: Path) -> None:
    _require_hash(path, SUPERVISOR_OWNER_SHA256)
    _load_module(path, "windows_supervised_owner").activate_child_from_env()


def _redirect_standard_streams() -> None:
    sys.stdout.flush()
    sys.stderr.flush()
    descriptor = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(descriptor, 1)
        os.dup2(descriptor, 2)
    finally:
        os.close(descriptor)


def collection_child(args: argparse.Namespace) -> int:
    _activate_owner(args.owner)
    _redirect_standard_streams()
    _require_hash(args.wrapper, WRAPPER_SHA256)
    wrapper = _load_module(args.wrapper, "windows_collection_wrapper")
    recorder = EVENTS.EventRecorder(args.state, args.token)
    os.chdir(args.product_root)
    previous = sys.argv
    sys.argv = [str(args.wrapper), "--watchdog-seconds", "180"]
    try:
        wrapper._write = recorder.write
        return int(wrapper.main())
    finally:
        sys.argv = previous


def _windows_kernel32() -> Any:
    if os.name != "nt":
        raise DiagnosticError("self_test_membership_invalid")
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError as error:
        raise DiagnosticError("self_test_membership_invalid") from error
    kernel.OpenJobObjectW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenJobObjectW.restype = ctypes.c_void_p
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    kernel.IsProcessInJob.restype = ctypes.c_int
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetExitCodeProcess.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    return kernel


def _prove_current_job_membership(name: str, *, kernel: Any | None = None) -> None:
    if not EVENTS.valid_text(name, 128):
        raise DiagnosticError("self_test_membership_invalid")
    api = kernel or _windows_kernel32()
    try:
        handle = api.OpenJobObjectW(JOB_OBJECT_QUERY, False, name)
    except OSError as error:
        raise DiagnosticError("self_test_membership_invalid") from error
    if not handle:
        raise DiagnosticError("self_test_membership_invalid")
    member = ctypes.c_int()
    query_ok = False
    try:
        try:
            query_ok = bool(api.IsProcessInJob(api.GetCurrentProcess(), handle, ctypes.byref(member)))
        except OSError:
            query_ok = False
    finally:
        try:
            close_ok = bool(api.CloseHandle(handle))
        except OSError:
            close_ok = False
    if not query_ok or member.value != 1 or not close_ok:
        raise DiagnosticError("self_test_membership_invalid")


def _strict_process_absent(pid: int, *, kernel: Any | None = None) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        raise DiagnosticError("self_test_process_state_unknown")
    api = kernel or _windows_kernel32()
    try:
        handle = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except OSError as error:
        raise DiagnosticError("self_test_process_state_unknown") from error
    if not handle:
        if ctypes.get_last_error() == ERROR_INVALID_PARAMETER:
            return True
        raise DiagnosticError("self_test_process_state_unknown")
    exit_code = ctypes.c_ulong()
    query_ok = False
    try:
        try:
            query_ok = bool(api.GetExitCodeProcess(handle, ctypes.byref(exit_code)))
        except OSError:
            query_ok = False
    finally:
        try:
            close_ok = bool(api.CloseHandle(handle))
        except OSError:
            close_ok = False
    if not query_ok or not close_ok:
        raise DiagnosticError("self_test_process_state_unknown")
    if exit_code.value == STILL_ACTIVE:
        raise DiagnosticError("self_test_failed")
    return True


def self_test_grandchild(args: argparse.Namespace) -> int:
    if not EVENTS.TOKEN.fullmatch(args.token):
        raise DiagnosticError("event_authenticator_invalid")
    _prove_current_job_membership(os.environ.get(OWNER_NAME_ENV, ""))
    EVENTS.atomic_json(
        args.state,
        {
            "schema": 1,
            "token": args.token,
            "pid": os.getpid(),
            "role": "grandchild",
            "job_membership": "passed",
        },
        SELF_TEST_BYTES,
    )
    time.sleep(60)
    return 0


def self_test_child(args: argparse.Namespace) -> int:
    _activate_owner(args.owner)
    if not EVENTS.TOKEN.fullmatch(args.token):
        raise DiagnosticError("event_authenticator_invalid")
    grandchild = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__)),
            "self-test-grandchild",
            "--state",
            str(args.state),
            "--token",
            args.token,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return int(grandchild.wait())


def _bounded_command(command: list[str], *, cwd: Path | None = None, timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DiagnosticError("bounded_command_failed") from error
    if result.returncode != 0 or len(result.stdout) > MAX_CAPTURE_BYTES:
        raise DiagnosticError("bounded_command_failed")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _git_identity(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise DiagnosticError("source_identity_mismatch")
    commit = _bounded_command(["git", "rev-parse", "HEAD"], cwd=root)
    tree = _bounded_command(["git", "rev-parse", "HEAD^{tree}"], cwd=root)
    if not _SHA.fullmatch(commit) or not _SHA.fullmatch(tree):
        raise DiagnosticError("source_identity_mismatch")
    return {"commit": commit, "tree": tree}


def _git_blob(root: Path, relative: str) -> str:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise DiagnosticError("source_identity_mismatch")
    blob = _bounded_command(["git", "hash-object", relative], cwd=root)
    if not re.fullmatch(r"[0-9a-f]{40}", blob):
        raise DiagnosticError("source_identity_mismatch")
    return blob


def _git_head_blob(root: Path, relative: str) -> str:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise DiagnosticError("source_identity_mismatch")
    blob = _bounded_command(["git", "rev-parse", f"HEAD:{relative}"], cwd=root)
    if not re.fullmatch(r"[0-9a-f]{40}", blob):
        raise DiagnosticError("source_identity_mismatch")
    return blob


def _python_identity(executable: Path, expected: str) -> dict[str, str]:
    if executable.is_symlink() or not executable.is_file():
        raise DiagnosticError("python_identity_mismatch")
    version = _bounded_command([str(executable), "-c", "import platform;print(platform.python_version())"], timeout=10)
    if version != expected and not (expected == "3.14" and version.startswith("3.14.")):
        raise DiagnosticError("python_identity_mismatch")
    return {"version": version, "executable_sha256": _sha256(executable)}


def _safe_metadata(name: str, expected: str | None = None) -> str:
    value = os.environ.get(name, "")
    if not _SAFE_METADATA.fullmatch(value) or (expected is not None and value != expected):
        raise DiagnosticError("runner_identity_mismatch")
    return value


def _artifact_paths(driver: Path) -> dict[str, Path]:
    evidence = driver / "evidence"
    return {
        "receipt": evidence / "windows-supervised-receipt.json",
        "export": evidence / "windows-supervised-events.json",
        "inventory": evidence / "windows-supervised-dependencies.json",
    }


def _validate_artifact_args(args: argparse.Namespace, driver: Path) -> None:
    expected = _artifact_paths(driver)
    for name, path in expected.items():
        if getattr(args, name).absolute() != path.absolute():
            raise DiagnosticError("artifact_path_invalid")


def _validate_context(args: argparse.Namespace) -> dict[str, Any]:
    driver = _git_identity(args.driver_root)
    product = _git_identity(args.product_root)
    supervisor = _git_identity(args.supervisor_root)
    wrapper = _git_identity(args.wrapper_root)
    if (
        driver["commit"] != os.environ.get("GITHUB_SHA")
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("GITHUB_REF_NAME") != EXPECTED_BRANCH
    ):
        raise DiagnosticError("driver_identity_mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise DiagnosticError("driver_identity_mismatch")
    if product != {"commit": PRODUCT_COMMIT, "tree": PRODUCT_TREE}:
        raise DiagnosticError("product_identity_mismatch")
    if supervisor != {"commit": SUPERVISOR_COMMIT, "tree": SUPERVISOR_TREE}:
        raise DiagnosticError("supervisor_identity_mismatch")
    if wrapper != {"commit": WRAPPER_COMMIT, "tree": WRAPPER_TREE}:
        raise DiagnosticError("wrapper_identity_mismatch")
    owner = args.supervisor_root / ".github" / "scripts" / "mcpb_process_owner.py"
    supervisor_ci = args.supervisor_root / ".github" / "scripts" / "mcpb-ci.py"
    old_wrapper = args.wrapper_root / ".github" / "scripts" / "windows_collection_diagnostic.py"
    driver_helper = args.driver_root / ".github" / "scripts" / "windows_collection_supervised.py"
    event_helper = args.driver_root / ".github" / "scripts" / "windows_collection_events.py"
    if Path(__file__).resolve() != driver_helper.resolve() or driver_helper.is_symlink():
        raise DiagnosticError("driver_identity_mismatch")
    if Path(EVENTS.__file__).resolve() != event_helper.resolve() or event_helper.is_symlink():
        raise DiagnosticError("driver_identity_mismatch")
    _require_hash(owner, SUPERVISOR_OWNER_SHA256)
    _require_hash(supervisor_ci, SUPERVISOR_CI_SHA256)
    _require_hash(old_wrapper, WRAPPER_SHA256)
    _require_hash(event_helper, EVENTS_SHA256)
    if _git_blob(args.wrapper_root, ".github/scripts/windows_collection_diagnostic.py") != WRAPPER_BLOB:
        raise DiagnosticError("wrapper_identity_mismatch")
    if _git_blob(args.driver_root, ".github/scripts/windows_collection_events.py") != EVENTS_BLOB:
        raise DiagnosticError("driver_identity_mismatch")
    for relative in (
        ".github/scripts/windows_collection_supervised.py",
        ".github/workflows/windows-collection-supervised.yml",
    ):
        if _git_blob(args.driver_root, relative) != _git_head_blob(args.driver_root, relative):
            raise DiagnosticError("driver_identity_mismatch")
    return {
        "driver": driver,
        "product": product,
        "supervisor": supervisor,
        "wrapper": {**wrapper, "blob": WRAPPER_BLOB, "sha256": WRAPPER_SHA256},
        "owner": owner,
        "supervisor_ci": supervisor_ci,
        "old_wrapper": old_wrapper,
        "event_helper": event_helper,
    }


def inventory(args: argparse.Namespace) -> int:
    output = args.output
    raw = _bounded_command([str(args.python), "-m", "pip", "list", "--format=json"], timeout=60)
    try:
        packages = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DiagnosticError("dependency_inventory_invalid") from error
    sanitized = []
    if not isinstance(packages, list) or len(packages) > 4096:
        raise DiagnosticError("dependency_inventory_invalid")
    for package in packages:
        if (
            not isinstance(package, dict)
            or not EVENTS.valid_text(package.get("name"), 128)
            or not EVENTS.valid_text(package.get("version"), 128)
        ):
            raise DiagnosticError("dependency_inventory_invalid")
        sanitized.append({"name": package["name"], "version": package["version"]})
    sanitized.sort(key=lambda item: (item["name"].casefold(), item["name"], item["version"]))
    try:
        EVENTS.atomic_json(output, {"schema": 1, "packages": sanitized}, MAX_INVENTORY_BYTES)
    except OSError as error:
        raise DiagnosticError("dependency_inventory_write_failed") from error
    return 0


def _read_self_test(path: Path, token: str) -> int:
    payload = EVENTS.read_json(path, SELF_TEST_BYTES)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "token", "pid", "role", "job_membership"}
        or payload.get("schema") != 1
        or payload.get("token") != token
        or payload.get("role") != "grandchild"
        or payload.get("job_membership") != "passed"
        or not isinstance(payload.get("pid"), int)
        or isinstance(payload.get("pid"), bool)
        or payload["pid"] < 1
    ):
        raise DiagnosticError("self_test_evidence_invalid")
    return payload["pid"]


def _run_self_test(supervisor: Any, context: dict[str, Any], args: argparse.Namespace, work: Path) -> dict[str, str]:
    state = work / "self-test.private.json"
    token = secrets.token_hex(32)
    command = [
        str(args.python314),
        str(args.driver_root / ".github" / "scripts" / "windows_collection_supervised.py"),
        "self-test-child",
        "--owner",
        str(context["owner"]),
        "--state",
        str(state),
        "--token",
        token,
    ]
    try:
        supervisor._run_owned(command, env=dict(os.environ), timeout=3)
    except supervisor.BoundedProcessError as error:
        classification, cleanup = error.classification, error.cleanup
    else:
        raise DiagnosticError("self_test_timeout_missing")
    pid = _read_self_test(state, token)
    gone = _strict_process_absent(pid)
    if classification != "command_timeout" or cleanup != "passed" or not gone:
        raise DiagnosticError("self_test_failed")
    return {
        "status": "passed",
        "exit_class": classification,
        "cleanup": cleanup,
        "job_membership": "passed",
        "grandchild_gone": "passed",
    }


def _collection_result(
    snapshot: dict[str, Any] | None, classification: str, cleanup: str, elapsed: float
) -> dict[str, Any]:
    result = snapshot.get("result") if snapshot else None
    return {
        "exit_class": classification,
        "cleanup": cleanup,
        "elapsed_seconds": round(elapsed, 3),
        "expected_tests": EXPECTED_TESTS,
        "actual_tests": result.get("collected") if isinstance(result, dict) else None,
        "return_code": result.get("return_code") if isinstance(result, dict) else None,
        "collector_starts": snapshot.get("collector_starts", 0) if snapshot else 0,
        "collector_completions": snapshot.get("collector_completions", 0) if snapshot else 0,
        "active_collectors": snapshot.get("active_collectors", []) if snapshot else [],
        "completed_digest": snapshot.get("completed_digest") if snapshot else None,
        "last_completed": snapshot.get("last_completed") if snapshot else None,
        "trace_status": "not_captured",
    }


def collection_passed(collection: dict[str, Any]) -> bool:
    return (
        collection.get("exit_class") == "command_passed"
        and collection.get("cleanup") == "passed"
        and collection.get("actual_tests") == EXPECTED_TESTS
        and isinstance(collection.get("return_code"), int)
        and not isinstance(collection.get("return_code"), bool)
        and collection.get("return_code") == 0
        and isinstance(collection.get("collector_starts"), int)
        and not isinstance(collection.get("collector_starts"), bool)
        and isinstance(collection.get("collector_completions"), int)
        and not isinstance(collection.get("collector_completions"), bool)
        and collection["collector_starts"] > 0
        and collection.get("collector_starts") == collection.get("collector_completions")
        and collection.get("active_collectors") == []
    )


def _run_collection(
    supervisor: Any, context: dict[str, Any], args: argparse.Namespace, work: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    state_path = work / "events.private.json"
    token = secrets.token_hex(32)
    command = [
        str(args.python314),
        str(args.driver_root / ".github" / "scripts" / "windows_collection_supervised.py"),
        "collection-child",
        "--owner",
        str(context["owner"]),
        "--wrapper",
        str(context["old_wrapper"]),
        "--product-root",
        str(args.product_root),
        "--state",
        str(state_path),
        "--token",
        token,
    ]
    started = time.monotonic()
    try:
        supervisor._run_owned(command, env=dict(os.environ), timeout=120)
    except supervisor.BoundedProcessError as error:
        classification, cleanup = error.classification, error.cleanup
    else:
        classification, cleanup = "command_passed", "passed"
    elapsed = time.monotonic() - started
    try:
        snapshot = EVENTS.read_private_state(state_path, token)
    except DiagnosticError:
        snapshot = None
    public = (
        EVENTS.sanitize_state(snapshot)
        if snapshot
        else {"schema": 1, "status": "evidence_unavailable", "trace_status": "not_captured"}
    )
    collection = _collection_result(snapshot, classification, cleanup, elapsed)
    return collection, public


def _read_inventory(path: Path) -> dict[str, Any]:
    payload = EVENTS.read_json(path, MAX_INVENTORY_BYTES)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "packages"}
        or not isinstance(payload.get("schema"), int)
        or isinstance(payload.get("schema"), bool)
        or payload.get("schema") != 1
    ):
        raise DiagnosticError("dependency_inventory_invalid")
    packages = payload.get("packages")
    if not isinstance(packages, list) or len(packages) > 4096:
        raise DiagnosticError("dependency_inventory_invalid")
    for package in packages:
        if not isinstance(package, dict) or set(package) != {"name", "version"}:
            raise DiagnosticError("dependency_inventory_invalid")
        if not EVENTS.valid_text(package.get("name"), 128) or not EVENTS.valid_text(package.get("version"), 128):
            raise DiagnosticError("dependency_inventory_invalid")
    expected = sorted(packages, key=lambda item: (item["name"].casefold(), item["name"], item["version"]))
    if packages != expected or len({item["name"].casefold() for item in packages}) != len(packages):
        raise DiagnosticError("dependency_inventory_invalid")
    return payload


def _provenance(context: dict[str, Any], args: argparse.Namespace, inventory_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "identities": {key: context[key] for key in ("driver", "product", "supervisor", "wrapper")},
        "sources": {
            "driver_sha256": _sha256(Path(__file__)),
            "events_sha256": _sha256(context["event_helper"]),
            "workflow_sha256": _sha256(args.driver_root / ".github/workflows/windows-collection-supervised.yml"),
            "supervisor_ci_sha256": SUPERVISOR_CI_SHA256,
            "supervisor_owner_sha256": SUPERVISOR_OWNER_SHA256,
        },
        "python": {
            "controller": _python_identity(args.python311, "3.11.9"),
            "collection": _python_identity(args.python314, "3.14"),
        },
        "runner": {
            "os": _safe_metadata("RUNNER_OS", "Windows"),
            "architecture": _safe_metadata("RUNNER_ARCH"),
            "image": _safe_metadata("ImageOS"),
        },
        "dependency_inventory_sha256": _sha256(args.inventory),
        "dependency_count": len(inventory_payload["packages"]),
        "dependency_resolution": "range_resolved_not_historical_lock",
    }


def controller(args: argparse.Namespace) -> int:
    driver = args.driver_root.absolute()
    _validate_artifact_args(args, driver)
    receipt = {
        "artifact_kind": "windows_supervised_collection",
        "schema": 1,
        "status": "failed",
        "failure_phase": "controller_startup",
        "exit_class": "diagnostic_failed",
        "trace_status": "not_captured",
    }
    work = Path(tempfile.mkdtemp(prefix="kinocut-windows-supervised-"))
    try:
        context = _validate_context(args)
        _require_hash(context["supervisor_ci"], SUPERVISOR_CI_SHA256)
        supervisor = _load_module(context["supervisor_ci"], "windows_collection_supervisor")
        inventory_payload = _read_inventory(args.inventory)
        provenance = _provenance(context, args, inventory_payload)
        self_test = _run_self_test(supervisor, context, args, work)
        collection, public = _run_collection(supervisor, context, args, work)
        EVENTS.atomic_json(args.export, public, EVENTS.MAX_EVENT_BYTES)
        receipt.update(
            failure_phase="collection",
            exit_class=collection["exit_class"],
            **provenance,
            self_test=self_test,
            collection=collection,
            evidence_sha256=_sha256(args.export),
        )
        if collection_passed(collection):
            receipt.update(status="passed", failure_phase=None, exit_class="command_passed")
    except DiagnosticError as error:
        receipt["exit_class"] = str(error)
    except (OSError, RuntimeError, ValueError, UnicodeError):
        receipt["exit_class"] = "controller_failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    try:
        EVENTS.atomic_json(args.receipt, receipt, MAX_RECEIPT_BYTES)
    except OSError as error:
        raise DiagnosticError("receipt_write_failed") from error
    return 0


def _valid_success_collection(collection: object, export: dict[str, Any]) -> bool:
    keys = {
        "exit_class",
        "cleanup",
        "elapsed_seconds",
        "expected_tests",
        "actual_tests",
        "return_code",
        "collector_starts",
        "collector_completions",
        "active_collectors",
        "completed_digest",
        "last_completed",
        "trace_status",
    }
    if not isinstance(collection, dict) or set(collection) != keys:
        return False
    integers = [
        collection.get(name)
        for name in ("expected_tests", "actual_tests", "return_code", "collector_starts", "collector_completions")
    ]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in integers):
        return False
    elapsed = collection.get("elapsed_seconds")
    if not isinstance(elapsed, float) or not math.isfinite(elapsed) or elapsed < 0:
        return False
    if collection.get("expected_tests") != EXPECTED_TESTS or not collection_passed(collection):
        return False
    return (
        collection.get("trace_status") == "not_captured"
        and isinstance(collection.get("completed_digest"), str)
        and re.fullmatch(r"[0-9a-f]{64}", collection["completed_digest"]) is not None
        and export.get("schema") == 1
        and export.get("started") is True
        and export.get("terminal") is True
        and export.get("failure_class") is None
        and export.get("result") == {"return_code": 0, "collected": EXPECTED_TESTS}
        and export.get("collector_starts") == collection.get("collector_starts")
        and export.get("collector_completions") == collection.get("collector_completions")
        and export.get("active_collectors") == collection.get("active_collectors")
        and export.get("completed_digest") == collection.get("completed_digest")
        and export.get("last_completed") == collection.get("last_completed")
        and export.get("trace_status") == collection.get("trace_status")
    )


def _valid_success_receipt(
    receipt: object, provenance: dict[str, Any], export: dict[str, Any], export_sha256: str
) -> bool:
    keys = {
        "artifact_kind",
        "schema",
        "status",
        "failure_phase",
        "exit_class",
        "trace_status",
        "identities",
        "sources",
        "python",
        "runner",
        "dependency_inventory_sha256",
        "dependency_count",
        "dependency_resolution",
        "self_test",
        "collection",
        "evidence_sha256",
    }
    if not isinstance(receipt, dict) or set(receipt) != keys:
        return False
    fixed = (
        receipt.get("artifact_kind") == "windows_supervised_collection"
        and isinstance(receipt.get("schema"), int)
        and not isinstance(receipt.get("schema"), bool)
        and receipt.get("schema") == 1
        and receipt.get("status") == "passed"
        and receipt.get("failure_phase") is None
        and receipt.get("exit_class") == "command_passed"
        and receipt.get("trace_status") == "not_captured"
        and receipt.get("evidence_sha256") == export_sha256
        and receipt.get("self_test")
        == {
            "status": "passed",
            "exit_class": "command_timeout",
            "cleanup": "passed",
            "job_membership": "passed",
            "grandchild_gone": "passed",
        }
    )
    count = receipt.get("dependency_count")
    provenance_matches = all(receipt.get(key) == value for key, value in provenance.items())
    return (
        fixed
        and isinstance(count, int)
        and not isinstance(count, bool)
        and provenance_matches
        and _valid_success_collection(receipt.get("collection"), export)
    )


def classify(args: argparse.Namespace) -> int:
    try:
        driver = args.driver_root.absolute()
        _validate_artifact_args(args, driver)
        context = _validate_context(args)
        _require_hash(context["supervisor_ci"], SUPERVISOR_CI_SHA256)
        inventory_payload = _read_inventory(args.inventory)
        provenance = _provenance(context, args, inventory_payload)
        receipt = EVENTS.read_json(args.receipt, MAX_RECEIPT_BYTES)
        export = EVENTS.read_sanitized_state(args.export)
        valid = _valid_success_receipt(receipt, provenance, export, _sha256(args.export))
    except (DiagnosticError, OSError, RuntimeError, TypeError, ValueError, UnicodeError):
        valid = False
    print("diagnostic_passed" if valid else "diagnostic_failed")
    return 0 if valid else 1


def _common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--driver-root", type=Path, required=True)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--supervisor-root", type=Path, required=True)
    parser.add_argument("--wrapper-root", type=Path, required=True)
    parser.add_argument("--python311", type=Path, required=True)
    parser.add_argument("--python314", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    controlled = commands.add_parser("controller")
    _common_paths(controlled)
    classified = commands.add_parser("classify")
    _common_paths(classified)
    inventoried = commands.add_parser("inventory")
    inventoried.add_argument("--python", type=Path, required=True)
    inventoried.add_argument("--output", type=Path, required=True)
    for name in ("self-test-child", "self-test-grandchild", "collection-child"):
        child = commands.add_parser(name)
        child.add_argument("--state", type=Path, required=True)
        child.add_argument("--token", required=True)
        if name != "self-test-grandchild":
            child.add_argument("--owner", type=Path, required=True)
        if name == "collection-child":
            child.add_argument("--wrapper", type=Path, required=True)
            child.add_argument("--product-root", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return {
        "controller": controller,
        "classify": classify,
        "inventory": inventory,
        "self-test-child": self_test_child,
        "self-test-grandchild": self_test_grandchild,
        "collection-child": collection_child,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
