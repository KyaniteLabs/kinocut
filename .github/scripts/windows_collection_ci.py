"""Run complete Windows pytest collection under a bounded external owner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
COLLECTION_TIMEOUT = 120.0
ROOT_EXIT_TIMEOUT = 5.0
RECEIPT_MAX_BYTES = 1024
_TOKEN = re.compile(r"[0-9a-f]{64}")
_OWNER_MODULE: Any | None = None


class CollectionFailure(RuntimeError):
    """Collection or its process cleanup could not be verified."""


def _owner_helper():
    global _OWNER_MODULE
    if _OWNER_MODULE is not None:
        return _OWNER_MODULE
    path = Path(__file__).with_name("mcpb_process_owner.py")
    spec = importlib.util.spec_from_file_location("windows_collection_process_owner", path)
    if not spec or not spec.loader:
        raise CollectionFailure("process_owner_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _OWNER_MODULE = module
    return module


def _write_receipt(path: Path, token: str, collected: int, returncode: int) -> None:
    if (
        path.exists()
        or path.is_symlink()
        or not _TOKEN.fullmatch(token)
        or isinstance(collected, bool)
        or not isinstance(collected, int)
        or collected < 0
        or isinstance(returncode, bool)
        or not isinstance(returncode, int)
    ):
        raise CollectionFailure("collection_receipt_invalid")
    payload = json.dumps(
        {"collected": collected, "returncode": returncode, "token": token},
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(payload.encode("utf-8")) > RECEIPT_MAX_BYTES:
        raise CollectionFailure("collection_receipt_invalid")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(payload)
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise CollectionFailure("collection_receipt_unwritable") from error


def _read_receipt(path: Path, token: str) -> int:
    try:
        if path.is_symlink() or not path.is_file():
            raise CollectionFailure("collection_receipt_missing")
        size = path.stat().st_size
        if size <= 0 or size > RECEIPT_MAX_BYTES:
            raise CollectionFailure("collection_receipt_invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except CollectionFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectionFailure("collection_receipt_invalid") from error
    if not isinstance(payload, dict) or set(payload) != {"collected", "returncode", "token"}:
        raise CollectionFailure("collection_receipt_invalid")
    collected = payload.get("collected")
    returncode = payload.get("returncode")
    if (
        payload.get("token") != token
        or isinstance(collected, bool)
        or not isinstance(collected, int)
        or collected <= 0
        or isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or returncode != 0
    ):
        raise CollectionFailure("collection_receipt_invalid")
    return collected


class _CollectionCounter:
    def __init__(self) -> None:
        self.collected = 0

    def pytest_collection_finish(self, session: Any) -> None:
        self.collected = len(session.items)


def _run_child(receipt: Path, token: str) -> int:
    _owner_helper().activate_child_from_env()
    import pytest

    counter = _CollectionCounter()
    returncode = int(
        pytest.main(
            ["--collect-only", "-qq", "-s", "--tb=short", "--color=no"],
            plugins=[counter],
        )
    )
    _write_receipt(receipt, token, counter.collected, returncode)
    return returncode


def _launch_child(repo_root: Path, receipt: Path, token: str, environment: dict[str, str]):
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--receipt",
        str(receipt),
        "--token",
        token,
    ]
    options: dict[str, Any] = {}
    if os.name != "nt":
        options["start_new_session"] = True
    return subprocess.Popen(
        command,
        cwd=repo_root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,
    )


def _terminate_root(process: subprocess.Popen[bytes] | None) -> bool:
    if process is None:
        return True
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=ROOT_EXIT_TIMEOUT)
        return True
    except subprocess.TimeoutExpired:
        process.kill()
    try:
        process.wait(timeout=ROOT_EXIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False
    return process.poll() is not None


def _abort(owner: Any, process: subprocess.Popen[bytes] | None) -> bool:
    try:
        owner_clean = bool(owner.terminate())
    except (OSError, RuntimeError):
        owner_clean = False
    try:
        root_clean = _terminate_root(process)
    except (OSError, RuntimeError):
        root_clean = False
    try:
        inactive = not owner.active()
    except (OSError, RuntimeError):
        inactive = False
    try:
        closed = bool(owner.close())
    except (OSError, RuntimeError):
        closed = False
    return owner_clean and root_clean and inactive and closed


def _run_supervised(repo_root: Path = ROOT, *, timeout: float = COLLECTION_TIMEOUT) -> int:
    private_root = Path(tempfile.mkdtemp(prefix="kinocut-windows-collection-"))
    owner = None
    process = None
    closed = False
    failure: CollectionFailure | None = None
    try:
        token = secrets.token_hex(32)
        receipt = private_root / "collection.json"
        try:
            owner = _owner_helper().create_owner(private_root)
        except (OSError, RuntimeError) as error:
            detail = "" if getattr(error, "cleanup", "passed") == "passed" else "; cleanup_failed"
            raise CollectionFailure(f"owner_not_activated{detail}") from error
        environment = dict(os.environ)
        environment.update(owner.environment())
        try:
            process = _launch_child(repo_root, receipt, token, environment)
            owner.bind(process)
            activated = owner.wait_activated(process)
        except (OSError, RuntimeError) as error:
            raise CollectionFailure("owner_not_activated") from error
        if not activated:
            raise CollectionFailure("owner_not_activated")
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise CollectionFailure("collection_timeout") from error
        if returncode != 0:
            raise CollectionFailure("collection_failed")
        collected = _read_receipt(receipt, token)
        try:
            active = owner.active()
        except (OSError, RuntimeError) as error:
            raise CollectionFailure("owner_state_unavailable") from error
        if active:
            raise CollectionFailure("owner_still_active")
        try:
            closed = bool(owner.close())
        except (OSError, RuntimeError) as error:
            raise CollectionFailure("owner_close_failed") from error
        if not closed:
            raise CollectionFailure("owner_close_failed")
        return collected
    except CollectionFailure as error:
        failure = error
        if owner is not None:
            closed = _abort(owner, process)
        if owner is not None and not closed:
            raise CollectionFailure(f"{error}; cleanup_failed") from error
        raise
    except (OSError, RuntimeError) as error:
        failure = CollectionFailure("collection_supervisor_failed")
        if owner is not None:
            closed = _abort(owner, process)
        detail = "" if owner is None or closed else "; cleanup_failed"
        raise CollectionFailure(f"collection_supervisor_failed{detail}") from error
    finally:
        if owner is not None and not closed and failure is None:
            _abort(owner, process)
        shutil.rmtree(private_root, ignore_errors=True)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--token")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.child:
        if args.receipt is None or not isinstance(args.token, str):
            return 1
        try:
            return _run_child(args.receipt, args.token)
        except (CollectionFailure, OSError, RuntimeError):
            return 1
    if args.receipt is not None or args.token is not None:
        return 1
    try:
        collected = _run_supervised()
    except CollectionFailure as error:
        print(f"Windows collection failed: {error}", file=sys.stderr)
        return 1
    print(f"Collected {collected} tests under a verified external process owner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
