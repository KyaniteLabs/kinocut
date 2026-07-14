"""Subtitle burn-in operation for the FFmpeg engine.

Authored ASS is burned verbatim (its PlayRes/styles/positions are preserved and
its source bytes are never rewritten); SRT/VTT is converted to a dimensioned ASS
whose single PlayResX/Y equals the probed display size so captions render
correctly across vertical/horizontal/square. A user ``style`` is optional and is
validated through the closed ``force_style`` parser before being applied.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile

from .engine_runtime_utils import (
    _build_edit_result,
    _require_filter,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .defaults import DEFAULT_SUBTITLE_STYLE
from .errors import MCPVideoError
from .models import EditResult
from .subtitles_common import (
    _subtitle_format,
    parse_force_style,
    probe_display_dimensions,
    synthesize_dimensioned_ass,
)


def _synthesis_workdir(output_path: str) -> str:
    """Directory for the transient dimensioned ASS (kept next to the output)."""
    return os.path.dirname(os.path.abspath(output_path))


def _fill_burn_source(fd: int, subtitle_format: str, subtitle_path: str, input_path: str) -> None:
    """Write the subtitle content burned by the filter into the open temp-ASS ``fd``.

    Authored ASS is copied byte-for-byte so a hostile subtitle filename never
    reaches the filtergraph (the FFmpeg subtitles filter cannot reliably consume a
    quote or other filter metacharacters in its path) and the source is never
    modified; SRT/VTT is converted to a dimensioned ASS. The temp file itself is
    owned (and cleaned up) by the caller, but this helper always closes ``fd`` on
    every path — including when probe/synthesis fails before it is wrapped by
    ``os.fdopen`` — and wraps any staging ``OSError`` (either format) as a private
    ``subtitle_prepare_failed``. Custom ``MCPVideoError`` from probe/synthesis is
    preserved unchanged.
    """
    try:
        if subtitle_format == "ass":
            with os.fdopen(fd, "wb") as dst, open(subtitle_path, "rb") as src:
                shutil.copyfileobj(src, dst)
        else:
            width, height = probe_display_dimensions(input_path)
            content = synthesize_dimensioned_ass(subtitle_path, (width, height))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
    except OSError as exc:
        raise MCPVideoError(
            "failed to prepare the subtitle file for burn-in",
            error_type="processing_error",
            code="subtitle_prepare_failed",
        ) from exc
    finally:
        # Own fd closure on every path; harmless (suppressed) after os.fdopen has
        # already closed it, and essential when probe/synthesis raised first.
        with contextlib.suppress(OSError):
            os.close(fd)


def subtitles(
    input_path: str,
    subtitle_path: str,
    output_path: str | None = None,
    style: str | None = None,
) -> EditResult:
    """Burn subtitles (SRT/VTT/authored ASS) into a video.

    Args:
        input_path: Input video.
        subtitle_path: ``.srt``, ``.vtt`` or ``.ass`` subtitle file.
        output_path: Output path (auto-generated if omitted).
        style: Optional ``force_style`` override (``Key=Value,...``). Omitted by
            default so authored ASS styling is preserved; when given it is
            validated through the closed style parser.
    """
    input_path = _validate_input_path(input_path)
    subtitle_path = _validate_input_path(subtitle_path)
    subtitle_format = _subtitle_format(subtitle_path)
    _require_filter("subtitles", "Subtitle burn-in")
    output = output_path or _auto_output(input_path, "subtitled")
    _validate_output_path(output)

    # An explicit style always wins and is validated (an explicit empty/hostile
    # style is rejected, never silently treated as "omitted"). When style is
    # omitted (None), SRT/VTT keep the legacy safe default so plain captions stay
    # readable, while authored ASS gets no force_style so its own PlayRes/styles/
    # positions are preserved.
    if style is not None:
        force_style = parse_force_style(style)
    elif subtitle_format != "ass":
        force_style = parse_force_style(DEFAULT_SUBTITLE_STYLE)
    else:
        force_style = None

    workdir = _synthesis_workdir(output)
    temp_ass: str | None = None
    try:
        try:
            fd, temp_ass = tempfile.mkstemp(suffix=".ass", dir=workdir)
        except OSError as exc:
            raise MCPVideoError(
                "failed to prepare the subtitle file for burn-in",
                error_type="processing_error",
                code="subtitle_prepare_failed",
            ) from exc
        _fill_burn_source(fd, subtitle_format, subtitle_path, input_path)
        video_filter = f"subtitles={_escape_ffmpeg_filter_value(temp_ass)}"
        if force_style:
            video_filter += f":force_style='{force_style}'"

        with _timed_operation() as timing:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
                    video_filter=video_filter,
                    audio_codec="copy",
                )
            )
    finally:
        if temp_ass is not None and os.path.exists(temp_ass):
            with contextlib.suppress(OSError):
                os.remove(temp_ass)

    return _build_edit_result(
        output,
        "subtitles",
        timing,
    )
