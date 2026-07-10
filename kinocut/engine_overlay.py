"""Video overlay operation for the FFmpeg engine."""

from __future__ import annotations

import logging
import warnings as _warnings

from .engine_runtime_utils import (
    _build_edit_result,
    _require_filter,
    _timed_operation,
)
from .engine_probe import probe
from .paths import (
    _auto_output,
)
from .models import (
    _resolve_position,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .validation import _validate_timing_against_duration
from .models import EditResult, NamedPosition, Position

logger = logging.getLogger(__name__)


def overlay_video(
    background_path: str,
    overlay_path: str,
    position: Position = "top-right",
    width: int | None = None,
    height: int | None = None,
    opacity: float = 0.8,
    start_time: float | None = None,
    duration: float | None = None,
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
) -> EditResult:
    """Picture-in-picture: overlay a video on top of another.

    Args:
        background_path: Path to the background video.
        overlay_path: Path to the overlay video.
        position: Position of the overlay on screen.
        width: Width to scale the overlay to.
        height: Height to scale the overlay to.
        opacity: Opacity of the overlay (0.0 to 1.0).
        start_time: When the overlay appears (seconds).
        duration: How long the overlay is visible (seconds).
        output_path: Where to save the output.
    """
    background_path = _validate_input_path(background_path)
    overlay_path = _validate_input_path(overlay_path)
    _require_filter("overlay", "Video overlay")
    _validate_dimensions(width, height)
    safe_opacity = _validate_opacity(opacity)
    output = output_path or _auto_output(background_path, "overlay")
    _validate_output_path(output)

    # --- Guardrail: timing validation ---
    try:
        bg_info = probe(background_path)
        timing_warnings = _validate_timing_against_duration(start_time, duration, bg_info.duration)
        for w in timing_warnings:
            _warnings.warn(f"[OVERLAY GUARDRAIL] {w}", stacklevel=2)
    except Exception as e:
        message = f"[OVERLAY GUARDRAIL] Could not validate timing: {e}"
        logger.warning(message, exc_info=True)
        _warnings.warn(message, stacklevel=2)
    # --- End guardrail ---

    scale_filter = _scale_filter(width, height)
    overlay_chain = _overlay_chain(scale_filter, safe_opacity)
    overlay_pos = _overlay_position(position)
    enable_expr = _enable_expression(start_time, duration)
    filter_complex = (
        f"[0:v]format=rgba[base];[1:v]{overlay_chain}[ov];[base][ov]overlay={overlay_pos}{enable_expr},format=yuv420p"
    )

    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                background_path,
                overlay_path,
                output_path=output,
                crf=crf,
                preset=preset,
                extra=["-filter_complex", filter_complex],
            )
        )

    return _build_edit_result(
        output,
        "overlay_video",
        timing,
    )


def _validate_dimensions(width: int | None, height: int | None) -> None:
    for name, value in (("width", width), ("height", height)):
        if value is not None and _sanitize_ffmpeg_number(value, name) <= 0:
            raise MCPVideoError(
                f"{name} must be positive, got {value}",
                error_type="validation_error",
                code="invalid_parameter",
            )


def _validate_opacity(opacity: float) -> str:
    opacity_num = _sanitize_ffmpeg_number(opacity, "opacity")
    if not 0.0 <= opacity_num <= 1.0:
        raise MCPVideoError(
            f"opacity must be between 0 and 1, got {opacity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return _escape_ffmpeg_filter_value(f"{opacity_num:.2f}")


def _scale_filter(width: int | None, height: int | None) -> str:
    if width is not None and height is not None:
        safe_width = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(width, "width")))
        safe_height = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(height, "height")))
        return f"scale={safe_width}:{safe_height}"
    if width is not None:
        safe_width = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(width, "width")))
        return f"scale={safe_width}:-1"
    if height is not None:
        safe_height = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(height, "height")))
        return f"scale=-1:{safe_height}"
    return ""


def _overlay_chain(scale_filter: str, safe_opacity: str) -> str:
    overlay_chain_parts = ["format=rgba", f"colorchannelmixer=aa={safe_opacity}"]
    if scale_filter:
        overlay_chain_parts.insert(0, scale_filter)
    return ",".join(overlay_chain_parts)


def _overlay_position(position: Position) -> str:
    position_map: dict[NamedPosition, str] = {
        "top-left": "0:0",
        "top-center": "(main_w-overlay_w)/2:0",
        "top-right": "main_w-overlay_w:0",
        "center-left": "0:(main_h-overlay_h)/2",
        "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        "center-right": "main_w-overlay_w:(main_h-overlay_h)/2",
        "bottom-left": "0:main_h-overlay_h",
        "bottom-center": "(main_w-overlay_w)/2:main_h-overlay_h",
        "bottom-right": "main_w-overlay_w:main_h-overlay_h",
    }
    return _resolve_position(position, position_map, "top-right")


def _enable_expression(start_time: float | None, duration: float | None) -> str:
    if start_time is None and duration is None:
        return ""
    safe_start = "0"
    safe_duration = "0"
    if start_time is not None:
        safe_start = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(start_time, "start_time")))
    if duration is not None:
        safe_duration = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(duration, "duration")))

    if start_time is not None and duration is not None:
        end = _sanitize_ffmpeg_number(start_time, "start_time") + _sanitize_ffmpeg_number(duration, "duration")
        safe_end = _escape_ffmpeg_filter_value(str(end))
        expression = f"between(t,{safe_start},{safe_end})"
    elif start_time is not None:
        expression = f"gte(t,{safe_start})"
    else:
        expression = f"lte(t,{safe_duration})"
    return f":enable='{expression}'"
