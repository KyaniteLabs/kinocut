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
    _atomic_output,
    _build_ffmpeg_cmd,
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_path
from .defaults import DEFAULT_SUBTITLE_STYLE
from .errors import MCPVideoError
from .models import QUALITY_PRESETS, EditResult, QualityLevel
from .subtitles_common import (
    _has_renderable_ass_dialogue,
    _require_renderable_ass_dialogue,
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
            with os.fdopen(fd, "wb") as dst:
                fd = -1  # The stream now owns closure, including source-open failures.
                with open(subtitle_path, "rb") as src:
                    has_dialogue = any(
                        _has_renderable_ass_dialogue(line.decode("utf-8", errors="replace")) for line in src
                    )
                    if not has_dialogue:
                        _require_renderable_ass_dialogue("")
                    src.seek(0)
                    shutil.copyfileobj(src, dst)
        else:
            width, height = probe_display_dimensions(input_path)
            content = synthesize_dimensioned_ass(subtitle_path, (width, height))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(content)
    except OSError as exc:
        raise MCPVideoError(
            "failed to prepare the subtitle file for burn-in",
            error_type="processing_error",
            code="subtitle_prepare_failed",
        ) from exc
    finally:
        # Close only while ownership has not transferred to a stream. Closing
        # the old number again can close an unrelated, newly allocated file.
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)


def _burn_style(style: str | None, subtitle_format: str) -> str | None:
    if style is not None:
        return parse_force_style(style)
    if subtitle_format != "ass":
        return parse_force_style(DEFAULT_SUBTITLE_STYLE)
    return None


def subtitles(
    input_path: str,
    subtitle_path: str,
    output_path: str | None = None,
    style: str | None = None,
    *,
    quality: QualityLevel | None = None,
) -> EditResult:
    """Burn subtitles (SRT/VTT/authored ASS) into a video.

    Args:
        input_path: Input video.
        subtitle_path: ``.srt``, ``.vtt`` or ``.ass`` subtitle file.
        output_path: Output path (auto-generated if omitted).
        style: Optional ``force_style`` override (``Key=Value,...``). Omitted by
            default so authored ASS styling is preserved; when given it is
            validated through the closed style parser.
        quality: Optional encoding preset for the captioned delivery.
    """
    input_path = _validate_input_path(input_path)
    subtitle_path = _validate_input_path(subtitle_path)
    subtitle_format = _subtitle_format(subtitle_path)
    _require_filter("subtitles", "Subtitle burn-in")
    output = output_path or _auto_output(input_path, "subtitled")
    _validate_output_path(output)
    encoding = {}
    if quality is not None:
        if not isinstance(quality, str) or quality not in QUALITY_PRESETS:
            raise MCPVideoError(
                "Unknown encoding quality preset", error_type="validation_error", code="invalid_parameter"
            )
        encoding = QUALITY_PRESETS[quality]

    force_style = _burn_style(style, subtitle_format)
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
        video_filter = f"subtitles={_escape_ffmpeg_filter_path(temp_ass)}"
        if force_style:
            video_filter += f":force_style='{force_style}'"

        with _timed_operation() as timing, _atomic_output(output) as staged:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=staged,
                    video_filter=video_filter,
                    audio_codec="copy",
                    crf=encoding.get("crf"),
                    preset=encoding.get("preset"),
                )
            )
            result = _build_edit_result(staged, "subtitles", timing)
    finally:
        if temp_ass is not None and os.path.exists(temp_ass):
            with contextlib.suppress(OSError):
                os.remove(temp_ass)

    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result
