"""Text overlay operations for the FFmpeg engine."""

from __future__ import annotations

from typing import Any

from .engine_probe import probe
from .errors import MCPVideoError
from .engine_runtime_utils import (
    _default_font,
    _require_filter,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .models import (
    _position_coords,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .validation import (
    _validate_color,
)
from .ffmpeg_helpers import _escape_ffmpeg_filter_value, _validate_input_path, _validate_output_path
from .models import EditResult, Position
from .design_guardrails import (
    validate_single_text,
    validate_text_layout,
    calculate_stacked_positions,
    TextOverlaySpec,
)

import warnings as _warnings


def add_text(
    input_path: str,
    text: str,
    position: Position = "top-center",
    font: str | None = None,
    size: int = 48,
    color: str = "white",
    shadow: bool = True,
    start_time: float | None = None,
    duration: float | None = None,
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
) -> EditResult:
    """Overlay text on a video."""
    input_path = _validate_input_path(input_path)
    _require_filter("drawtext", "Text overlay")
    if not text or not text.strip():
        raise MCPVideoError(
            "Text cannot be empty",
            error_type="validation_error",
            code="invalid_parameter",
        )
    _validate_color(color)
    # Defense in depth: coerce fontsize to a finite integer BEFORE it is
    # interpolated into the drawtext filtergraph (a proven file-read primitive
    # if a non-numeric string reaches `fontsize=`). Fails closed on non-numbers.
    size = int(_sanitize_ffmpeg_number(size, "size"))
    output = output_path or _auto_output(input_path, "titled")
    _validate_output_path(output)

    vw, vh = _probe_video_dims(input_path)
    for w in validate_single_text(
        text=text,
        position=position,
        size=size,
        color=color,
        shadow=shadow,
        video_width=vw,
        video_height=vh,
        background_color="#000000",
    ):
        _warnings.warn(f"[{w.severity.upper()}] {w.code}: {w.message}", stacklevel=2)

    vf = _build_drawtext_filter(
        text, position, font, size, color, shadow, start_time, duration
    )

    return _render_text_overlay(input_path, output, vf, crf, preset, "add_text")


def add_texts(
    input_path: str,
    texts: list[dict[str, Any]],
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
    auto_layout: bool = True,
) -> EditResult:
    """Overlay multiple text elements on a video in a single FFmpeg pass.

    Args:
        input_path: Path to input video.
        texts: List of text overlay dicts. Each dict may contain:
            - text (str, required)
            - position (str|dict, default "center")
            - font (str|None)
            - size (int, default 48)
            - color (str, default "white")
            - shadow (bool, default True)
            - start_time (float|None)
            - duration (float|None)
        output_path: Output path. Auto-generated if omitted.
        crf: CRF override.
        preset: Preset override.
        auto_layout: If True, automatically distribute vertically stacked
            texts that share the same named position.

    Returns:
        EditResult with output metadata.
    """
    input_path = _validate_input_path(input_path)
    _require_filter("drawtext", "Text overlay")
    if not texts:
        raise MCPVideoError(
            "texts list cannot be empty",
            error_type="validation_error",
            code="invalid_parameter",
        )

    output = output_path or _auto_output(input_path, "titled")
    _validate_output_path(output)

    vw, vh = _probe_video_dims(input_path)
    overlays = _build_overlay_specs(texts)

    for w in validate_text_layout(
        overlays,
        video_width=vw,
        video_height=vh,
        background_color="#000000",
    ):
        _warnings.warn(f"[{w.severity.upper()}] {w.code}: {w.message}", stacklevel=2)

    # Auto-layout: vertically distribute texts at same named position
    if auto_layout:
        _apply_auto_layout(overlays, vw, vh)

    filter_parts: list[str] = []
    for t, overlay in zip(texts, overlays, strict=False):
        filter_parts.append(
            _build_drawtext_filter(
                overlay.text,
                overlay.position,
                t.get("font"),
                overlay.size,
                overlay.color,
                overlay.shadow,
                overlay.start_time,
                overlay.duration,
            )
        )
    vf = ",".join(filter_parts)

    return _render_text_overlay(input_path, output, vf, crf, preset, "add_texts")


def _probe_video_dims(input_path: str) -> tuple[int, int]:
    """Return ``(width, height)`` for *input_path*, falling back to 1080p."""
    try:
        video_info = probe(input_path)
        return video_info.width, video_info.height
    except Exception:
        return 1920, 1080


def _build_overlay_specs(texts: list[dict[str, Any]]) -> list[TextOverlaySpec]:
    """Validate raw text dicts and convert them into overlay specs."""
    overlays: list[TextOverlaySpec] = []
    for t in texts:
        text = t.get("text", "")
        if not text or not text.strip():
            raise MCPVideoError(
                "Text cannot be empty",
                error_type="validation_error",
                code="invalid_parameter",
            )
        color = t.get("color", "white")
        _validate_color(color)
        overlays.append(
            TextOverlaySpec(
                text=text,
                position=t.get("position", "center"),
                size=t.get("size", 48),
                color=color,
                shadow=t.get("shadow", True),
                start_time=t.get("start_time"),
                duration=t.get("duration"),
            )
        )
    return overlays


def _resolve_overlay_coords(position: Position | dict[str, Any]) -> str:
    """Resolve an overlay position to drawtext ``x``/``y`` coordinates."""
    if isinstance(position, dict) and "x" in position:
        return f"x={int(position['x'])}:y={int(position['y'])}"
    return _position_coords(position)


def _append_enable_timing(
    parts: list[str],
    start_time: float | None,
    duration: float | None,
) -> None:
    """Append the drawtext ``enable=`` timing sub-filter to *parts* in place."""
    if start_time is not None and duration is not None:
        safe_start = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(start_time, "start_time")))
        safe_end = _escape_ffmpeg_filter_value(
            str(_sanitize_ffmpeg_number(start_time + duration, "start_time + duration"))
        )
        parts.append(f"enable='between(t\\,{safe_start}\\,{safe_end})'")
    elif start_time is not None:
        safe_start = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(start_time, "start_time")))
        parts.append(f"enable='gte(t\\,{safe_start})'")


def _build_drawtext_filter(
    text: str,
    position: Position | dict[str, Any],
    font: str | None,
    size: int,
    color: str,
    shadow: bool,
    start_time: float | None,
    duration: float | None,
) -> str:
    """Build a single FFmpeg ``drawtext`` filter string."""
    coords = _resolve_overlay_coords(position)
    fontfile = font or _default_font()
    if font is not None:
        _validate_input_path(fontfile)

    escaped_fontfile = _escape_ffmpeg_filter_value(fontfile)
    escaped_text = _escape_ffmpeg_filter_value(text)
    escaped_color = _escape_ffmpeg_filter_value(color)

    parts = [
        f"drawtext=text='{escaped_text}'",
        # User text is literal — without this, drawtext interprets %{...} as
        # expansion tokens (e.g. "50%{off}" errors or renders timestamps).
        "expansion=none",
        f"fontsize={size}",
        f"fontcolor={escaped_color}",
        f"fontfile={escaped_fontfile}",
        coords,
    ]
    if shadow:
        parts.append("shadowcolor=black@0.5")
        parts.append("shadowx=2")
        parts.append("shadowy=2")
    _append_enable_timing(parts, start_time, duration)
    return ":".join(parts)


def _render_text_overlay(
    input_path: str,
    output: str,
    video_filter: str,
    crf: int | None,
    preset: str | None,
    operation: str,
) -> EditResult:
    """Run FFmpeg with the drawtext filtergraph and build the EditResult."""
    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=output,
                video_filter=video_filter,
                audio_codec="copy",
                crf=crf,
                preset=preset,
            )
        )

    info = probe(output)
    return EditResult(
        output_path=output,
        duration=info.duration,
        resolution=info.resolution,
        size_mb=info.size_mb,
        format="mp4",
        operation=operation,
        elapsed_ms=timing["elapsed_ms"],
    )


def _apply_auto_layout(
    overlays: list[TextOverlaySpec],
    video_width: int,
    video_height: int,
) -> None:
    """Vertically distribute overlays that share the same named position.

    Modifies overlay positions in-place.
    """
    from collections import defaultdict

    # Group by named position
    groups: dict[str, list[tuple[int, TextOverlaySpec]]] = defaultdict(list)
    for i, o in enumerate(overlays):
        if isinstance(o.position, str):
            groups[o.position].append((i, o))

    for position, items in groups.items():
        if len(items) <= 1:
            continue

        # Calculate stacked positions
        texts = [(o.text, o.size) for _, o in items]
        new_positions = calculate_stacked_positions(
            texts,
            base_position=position,
            video_height=video_height,
            line_spacing=1.4,
        )

        # Apply new positions
        for (idx, _), pos in zip(items, new_positions, strict=False):
            overlays[idx] = TextOverlaySpec(
                text=overlays[idx].text,
                position=pos,
                size=overlays[idx].size,
                color=overlays[idx].color,
                shadow=overlays[idx].shadow,
                start_time=overlays[idx].start_time,
                duration=overlays[idx].duration,
            )
