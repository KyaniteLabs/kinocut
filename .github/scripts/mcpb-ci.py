#!/usr/bin/env python3
"""Bounded build and hosted-runtime helpers for the staged MCPB workflow."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import venv
import zipfile
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PHASE_TIMEOUT = 20
COMMAND_TIMEOUT = 180
MAX_CAPTURE = 16 * 1024
TREE_GRACE = 2.0
_OWNER_MODULE: Any | None = None
logger = logging.getLogger(__name__)


def _owner_helper():
    global _OWNER_MODULE
    if _OWNER_MODULE is not None:
        return _OWNER_MODULE
    path = Path(__file__).with_name("mcpb_process_owner.py")
    spec = importlib.util.spec_from_file_location("mcpb_process_owner", path)
    if not spec or not spec.loader:
        raise RuntimeError("process_owner_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _OWNER_MODULE = module
    return _OWNER_MODULE


class BoundedProcessError(RuntimeError):
    """A subprocess failed after its owned process tree reached a known state."""

    def __init__(self, classification: str, cleanup: str) -> None:
        super().__init__(classification)
        self.classification = classification
        self.cleanup = cleanup


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _drain(
    pipe: Any,
    target: bytearray,
    captured: list[int],
    lock: threading.Lock,
    overflow: threading.Event,
) -> None:
    for chunk in iter(lambda: pipe.read(4096), b""):
        with lock:
            remaining = MAX_CAPTURE - captured[0]
            if remaining > 0:
                accepted = chunk[:remaining]
                target.extend(accepted)
                captured[0] += len(accepted)
            if len(chunk) > remaining:
                overflow.set()
                continue


def _tree_exists(process: subprocess.Popen[bytes]) -> bool:
    process.poll()
    if os.name == "nt":
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_tree_gone(process: subprocess.Popen[bytes], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _tree_exists(process):
            return True
        time.sleep(0.02)
    return not _tree_exists(process)


def _windows_tree_kill(process: subprocess.Popen[bytes], *, force: bool) -> bool:
    command = ["taskkill", "/PID", str(process.pid), "/T"]
    if force:
        command.append("/F")
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _terminate_tree(process: subprocess.Popen[bytes]) -> bool:
    attempted = False
    if os.name == "nt":
        attempted = _windows_tree_kill(process, force=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            attempted = True
        except ProcessLookupError:
            return True
        except OSError:
            attempted = False
    if attempted and _wait_tree_gone(process, TREE_GRACE):
        return True
    if os.name == "nt":
        attempted = _windows_tree_kill(process, force=True) or attempted
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            attempted = True
        except ProcessLookupError:
            return True
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return False
    return attempted and _wait_tree_gone(process, TREE_GRACE)


def _popen(command: list[str], *, cwd: Path | None, env: dict[str, str] | None) -> subprocess.Popen[bytes]:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)


def _run(
    command: list[str],
    *,
    timeout: float = COMMAND_TIMEOUT,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    owner: Any | None = None,
) -> str:
    try:
        process = _popen(command, cwd=cwd, env=env)
    except OSError as error:
        raise BoundedProcessError("command_not_startable", "passed") from error
    if process.stdout is None or process.stderr is None:
        cleanup = "passed" if _terminate_tree(process) else "failed"
        raise BoundedProcessError("command_capture_unavailable", cleanup)
    if owner is not None:
        try:
            owner.bind(process)
            activated = owner.wait_activated(process)
        except (OSError, RuntimeError):
            activated = False
        if not activated:
            try:
                owner_clean = owner.terminate()
            except OSError:
                owner_clean = False
            root_clean = not _tree_exists(process) or _terminate_tree(process)
            raise BoundedProcessError("owner_not_activated", "passed" if owner_clean and root_clean else "failed")
    stdout = bytearray()
    stderr = bytearray()
    captured = [0]
    lock = threading.Lock()
    overflow = threading.Event()
    threads = [
        threading.Thread(target=_drain, args=(pipe, target, captured, lock, overflow), daemon=True)
        for pipe, target in ((process.stdout, stdout), (process.stderr, stderr))
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    classification = None
    while process.poll() is None:
        if overflow.is_set():
            classification = "command_output_overflow"
            break
        if time.monotonic() >= deadline:
            classification = "command_timeout"
            break
        time.sleep(0.02)
    if classification:
        cleanup = "passed" if _stop_tree(process, owner) else "failed"
        for thread in threads:
            thread.join(timeout=5)
        raise BoundedProcessError(classification, cleanup)
    returncode = process.returncode
    for thread in threads:
        thread.join(timeout=5)
    try:
        descendant_found = _tree_active(process, owner)
    except OSError:
        _stop_tree(process, owner)
        raise BoundedProcessError("owner_state_unavailable", "failed") from None
    cleanup = "passed" if not descendant_found or _stop_tree(process, owner) else "failed"
    if overflow.is_set():
        raise BoundedProcessError("command_output_overflow", cleanup)
    if descendant_found:
        raise BoundedProcessError("descendant_survived_command", cleanup)
    if returncode != 0:
        raise BoundedProcessError("command_failed", cleanup)
    return bytes(stdout).decode("utf-8", errors="replace").strip()


def _tree_active(process: subprocess.Popen[bytes], owner: Any | None) -> bool:
    return bool(owner.active()) if owner is not None else _tree_exists(process)


def _stop_tree(process: subprocess.Popen[bytes], owner: Any | None) -> bool:
    if owner is None:
        return _terminate_tree(process)
    try:
        clean = owner.terminate()
    except OSError:
        clean = False
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return False
    return bool(clean)


def _builder():
    path = ROOT / "scripts" / "build-mcpb.py"
    spec = importlib.util.spec_from_file_location("build_mcpb", path)
    if not spec or not spec.loader:
        raise RuntimeError("builder_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract(bundle: Path, destination: Path) -> list[str]:
    builder = _builder()
    receipt = builder.audit_bundle(bundle)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("extraction_destination_exists")
    destination.mkdir(parents=True)
    with zipfile.ZipFile(bundle) as archive:
        for name in receipt["archive_inventory"]:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(archive.read(name))
    return receipt["archive_inventory"]


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def prepare(args: argparse.Namespace) -> int:
    wheels = sorted(Path().glob(args.wheel_glob))
    if len(wheels) != 1 or not wheels[0].is_file() or wheels[0].is_symlink():
        raise RuntimeError("candidate_wheel_inventory_invalid")
    if args.venv.exists() or args.venv.is_symlink():
        raise RuntimeError("venv_destination_exists")
    venv.EnvBuilder(with_pip=True, clear=False).create(args.venv)
    requirement = str(wheels[0].resolve()) + (f"[{args.extra}]" if args.extra else "")
    _run([str(_venv_python(args.venv)), "-m", "pip", "install", "--quiet", requirement], timeout=600)
    return 0


def official(args: argparse.Namespace) -> int:
    destination = Path(tempfile.mkdtemp(prefix="mcpb-extract-")) / "bundle"
    try:
        inventory = _extract(args.bundle, destination)
        version = _run([str(args.validator), "--version"], timeout=20)
        if not any(token.lstrip("v") == "2.1.2" for token in version.split()):
            raise RuntimeError("validator_version_mismatch")
        _run([str(args.validator), "validate", str(ROOT / "mcpb" / "manifest.json")], timeout=30)
        _run([str(args.validator), "validate", str(destination / "manifest.json")], timeout=30)
        receipt = {
            "artifact_kind": "mcpb_official_validation",
            "source_sha": args.source_sha,
            "archive_sha256": _sha256(args.bundle),
            "wheel_sha256": _sha256(args.wheel),
            "archive_inventory": inventory,
            "validator": {"name": "@anthropic-ai/mcpb", "version": "2.1.2"},
            "source_manifest": "passed",
            "extracted_manifest": "passed",
        }
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(destination.parent, ignore_errors=True)
    return 0


def extract(args: argparse.Namespace) -> int:
    inventory = _extract(args.bundle, args.destination)
    print(json.dumps({"archive_inventory": inventory}, sort_keys=True))
    return 0


def _payload(result: Any) -> dict[str, Any]:
    if result.structuredContent:
        payload = result.structuredContent
    elif result.content:
        payload = json.loads(result.content[0].text)
    else:
        raise RuntimeError("empty_tool_response")
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_tool_response")
    return payload


async def _deadline(awaitable: Any) -> Any:
    async with asyncio.timeout(PHASE_TIMEOUT):
        return await awaitable


async def _call(session: Any, progress: dict[str, Any], phase: str, name: str, arguments: dict) -> dict:
    progress["phase"] = phase
    return _payload(await _deadline(session.call_tool(name, arguments)))


async def _core_calls(session: Any, media: Path, progress: dict[str, Any], gates: dict[str, str]) -> None:
    transcribe = await _call(
        session, progress, "mcp_call_video_ai_transcribe", "video_ai_transcribe", {"input_path": str(media)}
    )
    if transcribe.get("success") is not False or transcribe.get("error", {}).get("code") != "missing_whisper":
        raise RuntimeError("missing_whisper_contract_failed")
    if "[transcribe]" not in transcribe.get("error", {}).get("message", ""):
        raise RuntimeError("missing_whisper_hint_failed")
    gates["missing_whisper"] = "passed"
    after_whisper = await _call(
        session, progress, "mcp_reuse_after_missing_whisper", "video_info", {"input_path": str(media)}
    )
    if after_whisper.get("success") is not True:
        raise RuntimeError("session_failed_after_whisper_absence")
    gates["core_after_missing_whisper"] = "passed"
    doctor = await _call(session, progress, "mcp_call_hyperframes_doctor_absent", "hyperframes_doctor", {})
    if doctor.get("success") is not False or doctor.get("error", {}).get("code") != "hyperframes_not_found":
        raise RuntimeError("hyperframes_absence_contract_failed")
    gates["hyperframes_not_found"] = "passed"


async def _optional_calls(session: Any, media: Path, progress: dict[str, Any], gates: dict[str, str]) -> None:
    doctor = await _call(session, progress, "mcp_call_hyperframes_doctor_present", "hyperframes_doctor", {})
    if doctor.get("success") is not True or "0.8.30" not in json.dumps(doctor, sort_keys=True):
        raise RuntimeError("hyperframes_present_contract_failed")
    scene = await _call(
        session,
        progress,
        "mcp_call_video_ai_scene_detect",
        "video_ai_scene_detect",
        {"input_path": str(media), "use_ai": True},
    )
    if scene.get("success") is not True:
        raise RuntimeError("scene_tool_callability_failed")
    gates.update(hyperframes_0_8_30_detected="passed", scene_tool_callable="passed")


async def _runtime_session(args: argparse.Namespace, media: Path, progress: dict[str, Any]) -> dict[str, str]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    python = _venv_python(args.venv.absolute())
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["KINOCUT_MCPB_PYTHON"] = str(python)
    env["KINOCUT_MCPB_FFMPEG"] = str(args.ffmpeg.resolve())
    env["KINOCUT_MCPB_SUPERVISED_PROCESS_TREE"] = "1"
    env["MCP_VIDEO_HYPERFRAMES_COMMAND"] = args.hyperframes
    params = StdioServerParameters(
        command=str(args.node.resolve()), args=[str(args.launcher.resolve())], env=env, cwd=media.parent
    )
    gates: dict[str, str] = {}
    progress["gates"] = gates
    stack = AsyncExitStack()
    primary_phase: str | None = None
    with Path(os.devnull).open("w", encoding="utf-8") as errlog:
        try:
            progress["phase"] = "mcp_stdio_start"
            read, write = await _deadline(stack.enter_async_context(stdio_client(params, errlog=errlog)))
            progress["phase"] = "mcp_client_start"
            session = await _deadline(stack.enter_async_context(ClientSession(read, write)))
            progress["phase"] = "mcp_initialize"
            await _deadline(session.initialize())
            gates["initialize"] = "passed"
            progress["phase"] = "mcp_list_tools"
            tools = await _deadline(session.list_tools())
            names = {tool.name for tool in tools.tools}
            required = {"video_info", "video_ai_transcribe", "hyperframes_doctor", "video_ai_scene_detect"}
            if not required <= names:
                raise RuntimeError("required_tools_missing")
            gates["list_tools"] = "passed"
            info = await _call(session, progress, "mcp_call_video_info", "video_info", {"input_path": str(media)})
            if info.get("success") is not True:
                raise RuntimeError("core_call_failed")
            gates["core_call"] = "passed"
            if args.mode == "core":
                await _core_calls(session, media, progress, gates)
            else:
                await _optional_calls(session, media, progress, gates)
            again = await _call(session, progress, "mcp_session_reuse", "video_info", {"input_path": str(media)})
            if again.get("success") is not True:
                raise RuntimeError("session_reuse_failed")
            gates["session_reuse"] = "passed"
        except Exception as error:
            primary_phase = progress["phase"]
            logger.warning("MCPB runtime transition failed during %s (%s)", primary_phase, type(error).__name__)
            raise
        finally:
            progress["phase"] = "mcp_shutdown"
            try:
                await _deadline(stack.aclose())
            except Exception as shutdown_error:
                logger.warning("MCPB runtime shutdown failed")
                progress["shutdown_failure_phase"] = "mcp_shutdown"
                progress["shutdown_exit_class"] = _exit_class(shutdown_error)
                if primary_phase is None:
                    raise
            else:
                progress["session_closed"] = True
            if primary_phase is not None:
                progress["phase"] = primary_phase
    return gates


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CAPTURE:
        raise RuntimeError("receipt_invalid")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("receipt_invalid")
    return payload


def _cleanup_probe_valid(args: argparse.Namespace) -> bool:
    if args.mode != "core":
        return True
    if args.cleanup_probe_receipt is None:
        return False
    try:
        receipt = _read_json(args.cleanup_probe_receipt)
    except (OSError, RuntimeError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return receipt == {
        "artifact_kind": "mcpb_cleanup_probe",
        "os": args.os,
        "architecture": args.architecture,
        "status": "passed",
        "cleanup": "passed",
        "exit_class": "descendant_survived_command",
        "topology": "launcher_to_mcp_server",
        "false_success_suppressed": "passed",
    }


def _supervised_failure(args: argparse.Namespace, error: BoundedProcessError) -> None:
    try:
        receipt = _read_json(args.receipt)
    except (OSError, RuntimeError, json.JSONDecodeError, UnicodeDecodeError):
        receipt = {
            "artifact_kind": "mcpb_hosted_runtime" if args.mode == "core" else "mcpb_optional_dependencies",
            "source_sha": args.source_sha,
            "archive_sha256": args.archive_sha,
            "os": args.os,
            "architecture": args.architecture,
            "status": "failed",
            "failure_phase": "runtime_supervisor",
            "exit_class": error.classification,
            "gates": {},
        }
    receipt["status"] = "failed"
    receipt["cleanup"] = error.cleanup
    receipt.setdefault("failure_phase", "runtime_supervisor")
    receipt.setdefault("exit_class", error.classification)
    receipt["supervisor_exit_class"] = error.classification
    _write_json(args.receipt, receipt)


def _run_owned(command: list[str], *, env: dict[str, str], timeout: float) -> tuple[str, str]:
    owner_root = Path(tempfile.mkdtemp(prefix="mcpb-owner-"))
    owner = None
    closed = False
    try:
        try:
            owner = _owner_helper().create_owner(owner_root)
        except (OSError, RuntimeError) as error:
            cleanup = getattr(error, "cleanup", "passed")
            raise BoundedProcessError("owner_not_activated", cleanup) from error
        child_env = dict(env)
        child_env.update(owner.environment())
        output = _run(command, env=child_env, timeout=timeout, owner=owner)
    except BoundedProcessError as error:
        if owner is not None:
            closed = owner.close()
        if owner is not None and not closed:
            error.cleanup = "failed"
        raise
    else:
        if owner is None:
            raise BoundedProcessError("owner_not_activated", "failed")
        closed = owner.close()
        if not closed:
            raise BoundedProcessError("owner_close_failed", "failed")
        return output, owner.kind
    finally:
        if owner is not None and not closed:
            owner.terminate()
            owner.close()
        shutil.rmtree(owner_root, ignore_errors=True)


def _reexec_runtime(args: argparse.Namespace) -> int | None:
    desired_python = _venv_python(args.venv.absolute())
    if os.environ.get("KINOCUT_MCPB_RUNTIME_CHILD") == "1":
        _owner_helper().activate_child_from_env()
        return None
    child_env = dict(os.environ)
    child_env["KINOCUT_MCPB_RUNTIME_CHILD"] = "1"
    try:
        _, owner_kind = _run_owned(
            [str(desired_python), str(Path(__file__).resolve()), *sys.argv[1:]],
            env=child_env,
            timeout=300,
        )
    except BoundedProcessError as error:
        _supervised_failure(args, error)
        return 1
    try:
        receipt = _read_json(args.receipt)
    except (OSError, RuntimeError, json.JSONDecodeError, UnicodeDecodeError):
        return 1
    if (
        receipt.get("status") != "passed"
        or receipt.get("cleanup") != "session_closed"
        or receipt.get("process_owner") != owner_kind
    ):
        receipt.update(status="failed", failure_phase="runtime_supervisor", exit_class="invalid_child_receipt")
        _write_json(args.receipt, receipt)
        return 1
    if not _cleanup_probe_valid(args):
        receipt.update(status="failed", cleanup="passed", failure_phase="cleanup_probe", exit_class="invalid_receipt")
        _write_json(args.receipt, receipt)
        return 1
    receipt["cleanup"] = "passed"
    if args.mode == "core":
        receipt["gates"]["cleanup_probe"] = "passed"
    _write_json(args.receipt, receipt)
    return 0


def _runtime_receipt(args: argparse.Namespace, gates: dict[str, str], archive_sha: str, inventory: list[str]) -> dict:
    python = _venv_python(args.venv.absolute())
    return {
        "artifact_kind": "mcpb_hosted_runtime" if args.mode == "core" else "mcpb_optional_dependencies",
        "source_sha": args.source_sha,
        "archive_sha256": archive_sha,
        "wheel_sha256": _sha256(args.wheel),
        "archive_inventory": inventory,
        "os": args.os,
        "architecture": args.architecture,
        "status": "passed",
        "cleanup": "session_closed",
        "process_owner": os.environ.get("KINOCUT_MCPB_OWNER_KIND", "unowned"),
        "gates": gates,
        "kinocut_version": _run([str(python), "-c", "import kinocut; print(kinocut.__version__)"]),
        "python_version": _run([str(python), "-c", "import platform; print(platform.python_version())"]),
        "node_version": _run([str(args.node.resolve()), "--version"]),
        "ffmpeg_version": _run([str(args.ffmpeg.resolve()), "-version"]).splitlines()[0],
    }


def _exit_class(error: BaseException) -> str:
    if isinstance(error, BoundedProcessError):
        return error.classification
    if isinstance(error, RuntimeError) and re.fullmatch(r"[a-z0-9_]{1,80}", str(error)):
        return str(error)
    return type(error).__name__.lower()


def _runtime_failure_receipt(
    args: argparse.Namespace, progress: dict[str, Any], error: BaseException
) -> dict[str, Any]:
    receipt = {
        "artifact_kind": "mcpb_hosted_runtime" if args.mode == "core" else "mcpb_optional_dependencies",
        "source_sha": args.source_sha,
        "archive_sha256": args.archive_sha,
        "os": args.os,
        "architecture": args.architecture,
        "status": "failed",
        "cleanup": "session_closed" if progress["session_closed"] else "not_observed",
        "process_owner": os.environ.get("KINOCUT_MCPB_OWNER_KIND", "unowned"),
        "failure_phase": progress["phase"],
        "exit_class": _exit_class(error),
        "gates": progress["gates"],
    }
    for name in ("shutdown_failure_phase", "shutdown_exit_class"):
        if name in progress:
            receipt[name] = progress[name]
    return receipt


def runtime(args: argparse.Namespace) -> int:
    child_result = _reexec_runtime(args)
    if child_result is not None:
        return child_result
    desired_python = _venv_python(args.venv.absolute())
    work = Path(tempfile.mkdtemp(prefix="mcpb-runtime-"))
    progress: dict[str, Any] = {"phase": "artifact_validation", "gates": {}, "session_closed": False}
    try:
        archive_sha = _sha256(args.bundle)
        if archive_sha != args.archive_sha:
            raise RuntimeError("archive_digest_mismatch")
        inventory = _builder().audit_bundle(args.bundle)["archive_inventory"]
        progress["phase"] = "fixture_generation"
        media = work / "fixture.mp4"
        _run(
            [
                str(args.ffmpeg.resolve()),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=160x120:rate=15",
                "-t",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(media),
            ],
            timeout=60,
        )
        progress["phase"] = "mcp_session"
        gates = asyncio.run(_runtime_session(args, media, progress))
        progress["gates"] = gates
        if args.mode == "optional":
            progress["phase"] = "optional_discovery"
            doctor = json.loads(_run([str(desired_python), "-m", "kinocut", "doctor", "--json"]))
            checks = {check.get("name"): check for check in doctor.get("checks", [])}
            if checks.get("imagehash", {}).get("ok") is not True:
                raise RuntimeError("imagehash_discovery_failed")
            gates["imagehash_detected"] = "passed"
        progress["phase"] = "version_capture"
        receipt = _runtime_receipt(args, gates, archive_sha, inventory)
        if args.mode == "optional":
            receipt.update(
                {
                    name: gates[name]
                    for name in ("imagehash_detected", "hyperframes_0_8_30_detected", "scene_tool_callable")
                }
            )
        _write_json(args.receipt, receipt)
    except Exception as error:
        logger.warning("MCPB runtime failed during %s", progress["phase"])
        _write_json(args.receipt, _runtime_failure_receipt(args, progress, error))
        failed = True
    else:
        failed = False
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


def cleanup_probe(args: argparse.Namespace) -> int:
    payload = _owner_helper().cleanup_probe_payload(args, _run_owned, Path(__file__).resolve(), MAX_CAPTURE)
    _write_json(args.receipt, payload)
    if payload["status"] != "passed":
        raise RuntimeError("cleanup_probe_failed")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--wheel-glob", required=True)
    prepare_parser.add_argument("--venv", type=Path, required=True)
    prepare_parser.add_argument("--extra", default="")
    official_parser = sub.add_parser("official")
    official_parser.add_argument("--bundle", type=Path, required=True)
    official_parser.add_argument("--wheel", type=Path, required=True)
    official_parser.add_argument("--validator", type=Path, required=True)
    official_parser.add_argument("--source-sha", required=True)
    official_parser.add_argument("--receipt", type=Path, required=True)
    extract_parser = sub.add_parser("extract")
    extract_parser.add_argument("--bundle", type=Path, required=True)
    extract_parser.add_argument("--destination", type=Path, required=True)
    runtime_parser = sub.add_parser("runtime")
    runtime_parser.add_argument("--mode", choices=("core", "optional"), required=True)
    runtime_parser.add_argument("--launcher", type=Path, required=True)
    runtime_parser.add_argument("--bundle", type=Path, required=True)
    runtime_parser.add_argument("--wheel", type=Path, required=True)
    runtime_parser.add_argument("--venv", type=Path, required=True)
    runtime_parser.add_argument("--node", type=Path, required=True)
    runtime_parser.add_argument("--ffmpeg", type=Path, required=True)
    runtime_parser.add_argument("--hyperframes", required=True)
    runtime_parser.add_argument("--source-sha", required=True)
    runtime_parser.add_argument("--archive-sha", required=True)
    runtime_parser.add_argument("--os", required=True)
    runtime_parser.add_argument("--architecture", required=True)
    runtime_parser.add_argument("--receipt", type=Path, required=True)
    runtime_parser.add_argument("--cleanup-probe-receipt", type=Path)
    cleanup_parser = sub.add_parser("cleanup-probe")
    cleanup_parser.add_argument("--launcher", type=Path, required=True)
    cleanup_parser.add_argument("--venv", type=Path, required=True)
    cleanup_parser.add_argument("--node", type=Path, required=True)
    cleanup_parser.add_argument("--os", required=True)
    cleanup_parser.add_argument("--architecture", required=True)
    cleanup_parser.add_argument("--receipt", type=Path, required=True)
    cleanup_child = sub.add_parser("cleanup-probe-child", help=argparse.SUPPRESS)
    cleanup_child.add_argument("--launcher", type=Path, required=True)
    cleanup_child.add_argument("--venv", type=Path, required=True)
    cleanup_child.add_argument("--node", type=Path, required=True)
    cleanup_child.add_argument("--pid-file", type=Path, required=True)
    cleanup_child.add_argument("--survival-file", type=Path, required=True)
    cleanup_child.add_argument("--token", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return {
            "prepare": prepare,
            "official": official,
            "extract": extract,
            "runtime": runtime,
            "cleanup-probe": cleanup_probe,
            "cleanup-probe-child": lambda child_args: _owner_helper().cleanup_probe_child(
                child_args, MAX_CAPTURE, PHASE_TIMEOUT
            ),
        }[args.command](args)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile):
        print("MCPB CI helper failed in a bounded phase.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
