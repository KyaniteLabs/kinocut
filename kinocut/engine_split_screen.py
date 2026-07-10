"""Split-screen composition operation for the FFmpeg engine."""

from __future__ import annotations

import logging
import warnings as _warnings

from .engine_probe import probe
from .engine_runtime_utils import (
    _build_edit_result,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult, SplitLayout

logger = logging.getLogger(__name__)


def split_screen(
    left_path: str,
    right_path: str,
    layout: SplitLayout = "side-by-side",
    output_path: str | None = None,
) -> EditResult:
    """Place two videos side by side or top/bottom.

    Args:
        left_path: Path to the first video.
        right_path: Path to the second video.
        layout: 'side-by-side' or 'top-bottom'.
        output_path: Where to save the output.
    """
    left_path = _validate_input_path(left_path)
    right_path = _validate_input_path(right_path)
    output = output_path or _auto_output(left_path, f"split_{layout}")
    _validate_output_path(output)

    left_info = probe(left_path)
    right_info = probe(right_path)

    # --- Guardrails: duration, FPS, audio mismatch ---
    try:
        if abs(left_info.duration - right_info.duration) > 1.0:
            _warnings.warn(
                f"[SPLIT GUARDRAIL] Input durations differ significantly: "
                f"left={left_info.duration:.1f}s, right={right_info.duration:.1f}s. "
                f"Output will be truncated to the shorter.",
                stacklevel=2,
            )
        left_fps = getattr(left_info, "fps", None)
        right_fps = getattr(right_info, "fps", None)
        if left_fps and right_fps and abs(left_fps - right_fps) > 1.0:
            _warnings.warn(
                f"[SPLIT GUARDRAIL] Input frame rates differ: "
                f"left={left_fps:.1f}fps, right={right_fps:.1f}fps. "
                f"Output may stutter.",
                stacklevel=2,
            )
        left_has_audio = getattr(left_info, "audio_codec", None) is not None
        right_has_audio = getattr(right_info, "audio_codec", None) is not None
        if right_has_audio and not left_has_audio:
            _warnings.warn(
                "[SPLIT GUARDRAIL] Right video has audio but left does not. "
                "Only left audio is mapped; right audio will be lost.",
                stacklevel=2,
            )
    except Exception as e:
        message = f"[SPLIT GUARDRAIL] Could not validate split-screen inputs: {e}"
        logger.warning(message, exc_info=True)
        _warnings.warn(message, stacklevel=2)
    # --- End guardrails ---

    filter_complex = _split_filter(left_info.width, left_info.height, right_info.width, right_info.height, layout)

    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                left_path,
                right_path,
                output_path=output,
                extra=[
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[v]",
                    "-map",
                    "0:a?",
                ],
            )
        )

    return _build_edit_result(
        output,
        f"split_screen_{layout}",
        timing,
    )


def _split_filter(left_width: int, left_height: int, right_width: int, right_height: int, layout: SplitLayout) -> str:
    if layout == "side-by-side":
        target_h = _safe_dimension(max(left_height, right_height), "target_h")
        if left_height != right_height:
            return (
                f"[0:v]scale=-2:{target_h},setsar=1[left];"
                f"[1:v]scale=-2:{target_h},setsar=1[right];"
                f"[left][right]hstack=inputs=2[v]"
            )
        return "[0:v][1:v]hstack=inputs=2[v]"

    target_w = _safe_dimension(max(left_width, right_width), "target_w")
    if left_width != right_width:
        return (
            f"[0:v]scale={target_w}:-2,setsar=1[top];"
            f"[1:v]scale={target_w}:-2,setsar=1[bottom];"
            f"[top][bottom]vstack=inputs=2[v]"
        )
    return "[0:v][1:v]vstack=inputs=2[v]"


def _safe_dimension(value: int, name: str) -> str:
    return _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, name)))
