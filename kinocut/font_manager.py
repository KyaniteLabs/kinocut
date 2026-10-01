"""Font management — download Google Fonts for use in video overlays."""

from __future__ import annotations

import os
import subprocess
import sys

from .errors import MCPVideoError
from .defaults import DEFAULT_FONT_DOWNLOAD_DEADLINE
from .limits import MAX_FONT_DOWNLOAD_BYTES, MAX_FONT_IDENTIFIER_CHARACTERS, MAX_FONT_DOWNLOAD_DIAGNOSTIC_BYTES
from .atomic_publication import anchored_output
from .staged_writers import open_staged_writer
from .bounded_process import run_bounded
from .font_download_worker import _GOOGLE_FONT_URLS, DOWNLOAD_INVALID, DOWNLOAD_OVER_LIMIT
from .font_validation import validate_font_stream

_FONT_CACHE_DIR = os.path.expanduser("~/.cache/mcp-video/fonts")


def resolve_font(font_name: str) -> str:
    """Return a local path to a font, downloading from Google Fonts if needed.

    Args:
        font_name: Font family name (e.g. "Roboto", "Open Sans").

    Returns:
        Absolute path to the local TTF file.

    Raises:
        MCPVideoError: If the font cannot be downloaded or found.
    """
    if not isinstance(font_name, str) or not font_name.strip() or len(font_name) > MAX_FONT_IDENTIFIER_CHARACTERS:
        raise MCPVideoError("Font must be a bounded nonempty name or path", code="invalid_font")
    normalized = font_name.lower().replace(" ", "").replace("-", "")

    # Already a local file path?
    if os.path.isfile(font_name):
        return os.path.abspath(font_name)

    if normalized not in _GOOGLE_FONT_URLS:
        raise MCPVideoError(
            f"Unknown font. Available: {list(_GOOGLE_FONT_URLS.keys())}",
            error_type="validation_error",
            code="unknown_font",
        )

    local_path = os.path.join(_FONT_CACHE_DIR, f"{normalized}.ttf")

    if os.path.islink(local_path):
        raise MCPVideoError("Font cache entry must not be a symlink", code="unsafe_path")
    if os.path.isfile(local_path) and _cached_font_valid(local_path):
        return local_path

    with anchored_output(local_path, os.path.abspath) as staged:
        _download_font(normalized, staged)
    return local_path


def _download_font(key: str, staged: str) -> None:
    """Keep all network work in an owned, deadline-limited child process."""
    with open_staged_writer(staged) as output:
        try:
            result = run_bounded(
                [sys.executable, "-m", "kinocut.font_download_worker", key],
                timeout=DEFAULT_FONT_DOWNLOAD_DEADLINE,
                text=False,
                stdout_sink=output,
                stdout_limit=MAX_FONT_DOWNLOAD_BYTES,
                stderr_limit=MAX_FONT_DOWNLOAD_DIAGNOSTIC_BYTES,
            )
        except subprocess.TimeoutExpired as exc:
            raise MCPVideoError(
                "Failed to download font: TimeoutError", error_type="processing_error", code="font_download_failed"
            ) from exc
        except OSError as exc:
            raise MCPVideoError(
                "Failed to download font: worker unavailable",
                error_type="processing_error",
                code="font_download_failed",
            ) from exc
        except MCPVideoError as exc:
            if exc.code == "command_stdout_limit_exceeded":
                raise MCPVideoError("Font download exceeds byte limit", code="font_download_over_limit") from exc
            raise MCPVideoError(
                "Failed to download font: worker output failed",
                error_type="processing_error",
                code="font_download_failed",
            ) from exc
        _check_download_result(result.returncode)
        output.flush()
        with os.fdopen(os.dup(output.fileno()), "rb") as source:
            if not validate_font_stream(source):
                raise MCPVideoError("Downloaded font has invalid or incomplete tables", code="font_download_invalid")


def _check_download_result(returncode: int) -> None:
    if returncode == DOWNLOAD_OVER_LIMIT:
        raise MCPVideoError("Font download exceeds byte limit", code="font_download_over_limit")
    if returncode == DOWNLOAD_INVALID:
        raise MCPVideoError("Downloaded font was incomplete or invalid", code="font_download_invalid")
    if returncode != 0:
        raise MCPVideoError("Failed to download font", error_type="processing_error", code="font_download_failed")


def _cached_font_valid(path: str) -> bool:
    try:
        with open(path, "rb") as source:
            return validate_font_stream(source)
    except OSError:
        return False


def list_available_fonts() -> list[str]:
    """Return the list of built-in downloadable font names."""
    return list(_GOOGLE_FONT_URLS.keys())
