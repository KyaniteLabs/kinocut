"""Resource admission for caller-selected local JSON artifacts."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .errors import MCPVideoError
from .limits import MAX_JSON_ARTIFACT_DEPTH


def _admit_json_depth(raw: str, error_code: str) -> None:
    """Bound structural nesting while ignoring JSON strings and escapes."""
    depth = 0
    in_string = False
    escaped = False
    for character in raw:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_ARTIFACT_DEPTH:
                raise MCPVideoError(
                    "JSON artifact exceeds its nesting limit.", error_type="validation_error", code=error_code
                )
        elif character in "]}":
            depth -= 1


def parse_json_artifact(raw: str | bytes, *, max_bytes: int, error_code: str = "invalid_json_artifact") -> Any:
    """Parse bounded inline or already-admitted JSON without echoing content."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise MCPVideoError(
            "JSON artifact byte limit must be positive.", error_type="validation_error", code=error_code
        )
    try:
        if not isinstance(raw, (str, bytes)):
            raise TypeError
        if len(raw) > max_bytes or (isinstance(raw, str) and len(raw.encode("utf-8")) > max_bytes):
            raise MCPVideoError("JSON artifact exceeds its byte limit.", error_type="validation_error", code=error_code)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        _admit_json_depth(text, error_code)
        return json.loads(text)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise MCPVideoError(
            "JSON artifact could not be read as valid UTF-8 JSON.", error_type="validation_error", code=error_code
        ) from None


def load_json_artifact(path: str | Path, *, max_bytes: int, error_code: str = "invalid_json_artifact") -> Any:
    """Read at most cap+1 bytes from a regular file and return decoded JSON.

    Symlinks to regular files remain supported. Nonblocking open and descriptor
    admission reject FIFOs/devices before reading; size admission alone cannot
    protect against a file growing after fstat, so the read is also bounded.
    Errors deliberately omit caller paths, content and underlying exceptions.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise MCPVideoError(
            "JSON artifact byte limit must be positive.", error_type="validation_error", code=error_code
        )
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        handle = os.fdopen(descriptor, "rb")
        descriptor = None  # The handle owns closing it from this point onward.
        with handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise MCPVideoError(
                    "JSON artifact must be a regular file.", error_type="validation_error", code=error_code
                )
            if info.st_size > max_bytes:
                raise MCPVideoError(
                    "JSON artifact exceeds its byte limit.", error_type="validation_error", code=error_code
                )
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise MCPVideoError("JSON artifact exceeds its byte limit.", error_type="validation_error", code=error_code)
        return parse_json_artifact(raw, max_bytes=max_bytes, error_code=error_code)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        raise MCPVideoError(
            "JSON artifact could not be read as valid UTF-8 JSON.", error_type="validation_error", code=error_code
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
