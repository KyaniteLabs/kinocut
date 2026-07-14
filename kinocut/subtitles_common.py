"""Shared subtitle render helpers (Plan 01 Task 4).

Centralizes the security-sensitive parts of subtitle burn-in so the burn engine
and the generator use one implementation:

* ``_subtitle_format`` — closed ``ass``/``srt``/``vtt`` suffix detection.
* ``parse_force_style`` — a closed-key ``force_style`` parser that escapes/validates
  every value and rejects hostile input with a stable ``invalid_subtitle_style``
  (whole-string escaping would break ASS grammar; strip-quotes silently corrupts).
* ``probe_display_dimensions`` — rotation-normalized display size via ``engine_probe``.
* ``synthesize_dimensioned_ass`` — converts SRT/VTT to ASS and pins exactly one
  ``PlayResX``/``PlayResY`` equal to the probed display dimensions so captions are
  dimension-aware across vertical/horizontal/square without positional breaks.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile

from .engine_probe import probe
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _validate_input_path,
)
from .validation import SUBTITLE_STYLE_KEYS, SUBTITLE_STYLE_VALUE_RE

_ASS_SUFFIXES = (".ass",)
_SRT_SUFFIXES = (".srt",)
_VTT_SUFFIXES = (".vtt",)

_PLAYRES_LINE = re.compile(r"(?i)^\s*PlayRes[XY]\s*:")
_SCRIPT_INFO_HEADER = re.compile(r"(?i)^\s*\[Script Info\]\s*$")


def _style_error() -> MCPVideoError:
    # Never echo the raw hostile value — only the closed, safe key list.
    return MCPVideoError(
        "invalid subtitle style; expected comma-separated Key=Value pairs from the allowed style keys with safe values",
        error_type="validation_error",
        code="invalid_subtitle_style",
    )


def _subtitle_format(subtitle_path: str) -> str:
    """Return ``ass`` | ``srt`` | ``vtt`` for a subtitle path; reject anything else."""

    suffix = os.path.splitext(subtitle_path)[1].lower()
    if suffix in _ASS_SUFFIXES:
        return "ass"
    if suffix in _SRT_SUFFIXES:
        return "srt"
    if suffix in _VTT_SUFFIXES:
        return "vtt"
    raise MCPVideoError(
        "unsupported subtitle format; expected a .srt, .vtt, or .ass file",
        error_type="validation_error",
        code="unsupported_subtitle_format",
    )


def parse_force_style(style: str) -> str:
    """Validate a user ``force_style`` string via a closed key parser.

    Returns a safe ``Key=Value,Key=Value`` string (embeddable inside
    ``force_style='...'``) or raises ``invalid_subtitle_style`` without echoing the
    offending value.
    """

    if not isinstance(style, str) or not style.strip():
        raise _style_error()
    # Reject control characters up front — .strip()/`$` would otherwise swallow a
    # trailing newline and make a hostile value look benign.
    if any(ord(char) < 0x20 for char in style):
        raise _style_error()
    pairs: list[str] = []
    for chunk in style.split(","):
        key, sep, value = chunk.partition("=")
        key = key.strip()
        value = value.strip()
        if not sep or not key or not value:
            raise _style_error()
        if key.lower() not in SUBTITLE_STYLE_KEYS:
            raise _style_error()
        if not SUBTITLE_STYLE_VALUE_RE.fullmatch(value):
            raise _style_error()
        # Defense in depth: FFmpeg-escape every validated value before it is
        # embedded in the subtitles filter's force_style option.
        pairs.append(f"{key}={_escape_ffmpeg_filter_value(value)}")
    if not pairs:
        raise _style_error()
    return ",".join(pairs)


def probe_display_dimensions(input_path: str) -> tuple[int, int]:
    """Return the rotation-normalized ``(width, height)`` a viewer actually sees."""

    info = probe(input_path)
    width, height = int(info.width), int(info.height)
    if abs(int(info.rotation)) % 180 == 90:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise MCPVideoError(
            "could not determine display dimensions for subtitle rendering",
            error_type="validation_error",
            code="no_video_stream",
        )
    return width, height


def _normalize_playres(ass_content: str, width: int, height: int) -> str:
    """Strip every existing PlayResX/Y and insert exactly one pair = ``(width, height)``."""

    kept = [line for line in ass_content.splitlines() if not _PLAYRES_LINE.match(line)]
    result: list[str] = []
    inserted = False
    for line in kept:
        result.append(line)
        if not inserted and _SCRIPT_INFO_HEADER.match(line):
            result.append(f"PlayResX: {width}")
            result.append(f"PlayResY: {height}")
            inserted = True
    if not inserted:
        result = ["[Script Info]", f"PlayResX: {width}", f"PlayResY: {height}", *result]
    return "\n".join(result) + "\n"


def synthesize_dimensioned_ass(subtitle_path: str, display_size: tuple[int, int]) -> str:
    """Convert an SRT/VTT file to ASS and pin one PlayResX/Y = ``display_size``.

    The temporary conversion file is always removed; only the ASS *content* is
    returned so the caller controls where (and whether) it is written to disk.
    """

    subtitle_path = _validate_input_path(subtitle_path)
    width, height = int(display_size[0]), int(display_size[1])
    fd, temp_ass = tempfile.mkstemp(suffix=".ass")
    os.close(fd)
    try:
        _run_ffmpeg(["-y", "-i", subtitle_path, temp_ass])
        with open(temp_ass, encoding="utf-8", errors="replace") as handle:
            converted = handle.read()
    finally:
        if os.path.exists(temp_ass):
            with contextlib.suppress(OSError):
                os.remove(temp_ass)
    return _normalize_playres(converted, width, height)
