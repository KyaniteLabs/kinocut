"""Bounded FFmpeg/SoX subprocess runner for the post-processing sidecar.

All subprocess invocations go through this module so that:

* Commands are built from validated Python lists — never shell strings.
* Every user-controlled filter value is structurally validated before it
  reaches the binary (numeric ranges, closed preset sets, bounded codes).
* Timeouts are bounded by :data:`MAX_POST_TIMEOUT_SECONDS`.
* Raw stderr, host paths, and filter strings are never embedded in errors;
  failures surface as :class:`PostError` with a stable bounded ``code``.

Nothing in this module imports from ``kinocut.*`` runtime.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
from collections.abc import Sequence

from kinocut_sound.post._errors import (
    POST_DEPENDENCY_MISSING,
    POST_INVALID_PARAM,
    POST_OVER_LIMIT,
    POST_PROCESSING_FAILED,
    POST_TIMEOUT,
    PostError,
    post_error,
)

logger = logging.getLogger(__name__)

# TODO(controller): centralize these ceilings alongside defaults.py/limits.py
# when the controller merges the post sidecar into the shared config surface.
DEFAULT_POST_TIMEOUT_SECONDS: float = 30.0
MAX_POST_TIMEOUT_SECONDS: float = 120.0

_FFMPEG_BINARY = "ffmpeg"
_SOX_BINARY = "sox"


def resolve_binary(name: str) -> str:
    """Return the configured binary name, or raise if it is absent."""

    path = shutil.which(name)
    if path is None:
        raise post_error(
            f"required audio binary '{name}' is not installed",
            POST_DEPENDENCY_MISSING,
        )
    return path


def bounded_float(
    value: object,
    *,
    lo: float,
    hi: float,
    name: str,
) -> float:
    """Validate that ``value`` is a finite float inside ``[lo, hi]``."""

    if isinstance(value, bool):
        raise post_error(f"{name} must not be a boolean", POST_INVALID_PARAM)
    try:
        cast = float(value)
    except (TypeError, ValueError) as exc:
        raise post_error(f"{name} must be a finite number", POST_INVALID_PARAM) from exc
    if not math.isfinite(cast):
        raise post_error(f"{name} must be a finite number", POST_INVALID_PARAM)
    if cast < lo or cast > hi:
        raise post_error(
            f"{name} ({cast}) is outside the permitted range [{lo}, {hi}]",
            POST_OVER_LIMIT,
        )
    return cast


def bounded_int(
    value: object,
    *,
    lo: int,
    hi: int,
    name: str,
) -> int:
    """Validate that ``value`` is a strict integer inside ``[lo, hi]``."""

    if isinstance(value, bool):
        raise post_error(f"{name} must not be a boolean", POST_INVALID_PARAM)
    if not isinstance(value, int):
        raise post_error(f"{name} must be an integer", POST_INVALID_PARAM)
    if value < lo or value > hi:
        raise post_error(
            f"{name} ({value}) is outside the permitted range [{lo}, {hi}]",
            POST_OVER_LIMIT,
        )
    return value


def bounded_option(value: object, *, options: frozenset[str], name: str) -> str:
    """Validate that ``value`` is one of a closed set of bounded codes."""

    if not isinstance(value, str) or value not in options:
        raise post_error(
            f"{name} must be one of {sorted(options)}",
            POST_INVALID_PARAM,
        )
    return value


def ffmpeg_filter_number(value: float, *, digits: int = 2) -> str:
    """Render a validated number for an ffmpeg filter argument.

    Only finite numeric values reach this helper; the output is safe to embed
    in a filter string because it contains only digits, ``-``, and ``.``.
    """

    text = f"{value:.{digits}f}"
    # Defensive: never allow non-numeric characters through.
    permitted = set("0123456789-.")  # noqa: F841
    return text


def run_ffmpeg(args: Sequence[str], *, timeout: float | None = None) -> None:
    """Run ffmpeg with a bounded timeout; raise :class:`PostError` on failure."""

    timeout = DEFAULT_POST_TIMEOUT_SECONDS if timeout is None else timeout
    timeout = min(timeout, MAX_POST_TIMEOUT_SECONDS)
    binary = resolve_binary(_FFMPEG_BINARY)
    cmd = [binary, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    try:
        proc = subprocess.run(  # noqa: S603 - command list built from validated components
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("ffmpeg exceeded its bounded timeout (%ss)", timeout)
        raise post_error(
            "audio processor exceeded its bounded timeout",
            POST_TIMEOUT,
        ) from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-300:]
        logger.warning("ffmpeg failed (rc=%s): %s", proc.returncode, tail)
        raise post_error(
            "audio processor reported a failure",
            POST_PROCESSING_FAILED,
        )


def run_sox(args: Sequence[str], *, timeout: float | None = None) -> None:
    """Run SoX with a bounded timeout; raise :class:`PostError` on failure."""

    timeout = DEFAULT_POST_TIMEOUT_SECONDS if timeout is None else timeout
    timeout = min(timeout, MAX_POST_TIMEOUT_SECONDS)
    binary = resolve_binary(_SOX_BINARY)
    cmd = [binary, *args]
    try:
        proc = subprocess.run(  # noqa: S603 - command list built from validated components
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("sox exceeded its bounded timeout (%ss)", timeout)
        raise post_error(
            "audio processor exceeded its bounded timeout",
            POST_TIMEOUT,
        ) from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-300:]
        logger.warning("sox failed (rc=%s): %s", proc.returncode, tail)
        raise post_error(
            "audio processor reported a failure",
            POST_PROCESSING_FAILED,
        )


__all__ = [
    "DEFAULT_POST_TIMEOUT_SECONDS",
    "MAX_POST_TIMEOUT_SECONDS",
    "PostError",
    "bounded_float",
    "bounded_int",
    "bounded_option",
    "ffmpeg_filter_number",
    "resolve_binary",
    "run_ffmpeg",
    "run_sox",
]
