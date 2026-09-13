"""Private process identity evidence for the supervised MCPB cleanup probe."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

from .errors import MCPVideoError


_SUPERVISED_ENV = "KINOCUT_MCPB_SUPERVISED_PROCESS_TREE"
_MARKER_ENV = "KINOCUT_MCPB_INTERPRETER_FILE"
_TOKEN_ENV = "KINOCUT_MCPB_INTERPRETER_TOKEN"  # noqa: S105 - transient test nonce, not a credential.
_OWNER_READY_ENV = "KINOCUT_MCPB_OWNER_READY"
_TOKEN = re.compile(r"[0-9a-f]{64}")
_MARKER_MAX_BYTES = 512
_PATH_MAX_BYTES = 4096


def _observation_error() -> MCPVideoError:
    return MCPVideoError(
        "MCP process observation failed.",
        error_type="processing_error",
        code="mcpb_observation_failed",
    )


def _marker_path(raw_path: str, owner_ready: str) -> Path:
    try:
        oversized = (
            len(raw_path.encode("utf-8")) > _PATH_MAX_BYTES or len(owner_ready.encode("utf-8")) > _PATH_MAX_BYTES
        )
    except UnicodeError as error:
        raise _observation_error() from error
    if oversized:
        raise _observation_error()
    marker = Path(raw_path)
    ready = Path(owner_ready)
    if not marker.is_absolute() or not ready.is_absolute() or marker.parent != ready.parent:
        raise _observation_error()
    try:
        parent = marker.parent
        mode = parent.lstat().st_mode
        if not stat.S_ISDIR(mode) or parent.is_symlink() or marker.exists() or marker.is_symlink():
            raise _observation_error()
    except OSError as error:
        raise _observation_error() from error
    return marker


def observe_mcp_run_boundary() -> None:
    """Publish the actual interpreter identity for an explicit supervised probe."""

    if os.environ.get(_SUPERVISED_ENV) != "1":
        return
    raw_path = os.environ.get(_MARKER_ENV, "").strip()
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not raw_path and not token:
        return
    if not raw_path or not token or not _TOKEN.fullmatch(token):
        raise _observation_error()
    marker = _marker_path(raw_path, os.environ.get(_OWNER_READY_ENV, ""))
    payload = json.dumps(
        {"token": token, "pid": os.getpid(), "role": "mcp_interpreter", "phase": "mcp_run_boundary"},
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > _MARKER_MAX_BYTES:
        raise _observation_error()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(marker, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError) as error:
        raise _observation_error() from error
