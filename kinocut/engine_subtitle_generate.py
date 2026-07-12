"""Subtitle file generation operation for the FFmpeg engine."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping

from .paths import (
    _auto_output_dir,
)
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _get_video_duration,
    _validate_input_path,
    _validate_output_path,
    _seconds_to_srt_time,
)
from .models import SubtitleResult
from .subtitles_eof import clamp_segments_to_eof


def generate_subtitles(
    entries: list[Mapping],
    input_path: str,
    output_path: str | None = None,
    burn: bool = False,
) -> SubtitleResult:
    """Generate SRT subtitles from text entries and optionally burn into video.

    Entries may be dicts or any Mapping (e.g. ``ClampedSegment`` ASR records) and
    are clamped to the real video EOF before writing, so cues that overshoot the
    media end are trimmed and cues wholly past it are dropped. When ``burn`` is
    set the write is delegated to the canonical, dimension-aware burn engine.
    """
    _validate_entries(entries)
    input_path = _validate_input_path(input_path)
    if output_path:
        _validate_output_path(output_path)

    eof_seconds = _get_video_duration(input_path)
    clamped = clamp_segments_to_eof(list(entries), eof_seconds)
    entries = list(clamped.segments)
    if not entries:
        raise MCPVideoError(
            "all subtitle entries fall at or after the video end",
            error_type="validation_error",
            code="empty_entries",
        )
    warnings = [str(code) for code in clamped.warnings]

    srt_file = _write_srt(entries, input_path, output_path)
    if burn:
        from .engine_subtitles import subtitles as _burn_subtitles

        video_out = os.path.join(os.path.dirname(srt_file), "subtitled.mp4")
        with _srt_burn_source(srt_file) as burn_source:
            result = _burn_subtitles(input_path, burn_source, output_path=video_out)
        return SubtitleResult(
            srt_path=srt_file,
            video_path=result.output_path,
            entry_count=len(entries),
            warnings=warnings,
        )

    return SubtitleResult(
        srt_path=srt_file,
        entry_count=len(entries),
        warnings=warnings,
    )


@contextlib.contextmanager
def _srt_burn_source(srt_file: str) -> Iterator[str]:
    """Yield a suffix-recognized subtitle path for the canonical burn engine.

    The written content is always SRT, but the engine detects format by suffix.
    Only a genuine ``.srt`` name may be burned in place; an extensionless name
    (".../burned") or a *misleading* ``.vtt``/``.ass`` name would be misread, so
    those get a collision-safe temporary ``.srt`` copy created with ``mkstemp``
    (which never overwrites an existing sibling file), always cleaned up.
    """
    if os.path.splitext(srt_file)[1].lower() == ".srt":
        yield srt_file
        return
    fd, temp_srt = tempfile.mkstemp(suffix=".srt", dir=os.path.dirname(srt_file) or ".")
    try:
        with os.fdopen(fd, "wb") as dst, open(srt_file, "rb") as src:
            shutil.copyfileobj(src, dst)
        yield temp_srt
    finally:
        if os.path.exists(temp_srt):
            with contextlib.suppress(OSError):
                os.remove(temp_srt)


def _is_real_number(value: object) -> bool:
    """True for a real int/float; booleans are rejected as a mistaken time type."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_entries(entries: list[Mapping]) -> None:
    if not entries:
        raise MCPVideoError(
            "entries cannot be empty",
            error_type="validation_error",
            code="empty_entries",
        )
    for i, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or "text" not in entry or "start" not in entry or "end" not in entry:
            raise MCPVideoError(
                f"Invalid subtitle entry {i}: must have 'start', 'end', 'text' keys",
                error_type="validation_error",
                code="invalid_parameter",
            )
        # Validate value *types* first (never echoing a possibly hostile raw
        # value); the EOF clamp still owns finiteness and cross-segment order.
        if not _is_real_number(entry["start"]) or not _is_real_number(entry["end"]):
            raise MCPVideoError(
                f"Invalid subtitle entry {i}: 'start' and 'end' must be numbers",
                error_type="validation_error",
                code="invalid_parameter",
            )
        if not isinstance(entry["text"], str):
            raise MCPVideoError(
                f"Invalid subtitle entry {i}: 'text' must be a string",
                error_type="validation_error",
                code="invalid_parameter",
            )
        # Backward-compatible per-entry range check with a generic no-value
        # message (kept after the type checks so it never compares mixed types).
        if entry["start"] >= entry["end"]:
            raise MCPVideoError(
                f"Invalid subtitle entry {i}: 'start' must be less than 'end'",
                error_type="validation_error",
                code="invalid_entry_range",
            )


def _write_srt(entries: list[Mapping], input_path: str, output_path: str | None) -> str:
    if output_path:
        if os.path.isdir(output_path) or output_path.endswith(os.sep):
            srt_dir = output_path
            srt_file = os.path.join(srt_dir, "subtitles.srt")
        else:
            srt_dir = os.path.dirname(output_path) or "."
            srt_file = output_path
        os.makedirs(srt_dir, exist_ok=True)
    else:
        srt_dir = _auto_output_dir(input_path, "subtitles")
        os.makedirs(srt_dir, exist_ok=True)
        srt_file = os.path.join(srt_dir, "subtitles.srt")

    with open(srt_file, "w", encoding="utf-8") as f:
        f.write(_build_srt_content(entries))
    return srt_file


def _build_srt_content(entries: list[Mapping]) -> str:
    srt_lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        start = entry["start"]
        end = entry["end"]
        text = entry["text"]
        # Normalize newlines to spaces so each text line stays within its SRT entry.
        # A literal "-->" is valid caption text; only timing lines are structural.
        text = text.replace("\n", " ")
        srt_lines.append(str(i))
        srt_lines.append(_seconds_to_srt_time(start) + " --> " + _seconds_to_srt_time(end))
        srt_lines.append(text)
        srt_lines.append("")
    return "\n".join(srt_lines)
