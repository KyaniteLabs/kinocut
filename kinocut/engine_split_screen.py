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
from .ffmpeg_helpers import _atomic_output
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult, SplitLayout
from .errors import MCPVideoError

logger = logging.getLogger(__name__)


def _warn_split_screen_guardrails(left_info: object, right_info: object) -> None:
    try:
        if abs(left_info.duration - right_info.duration) > 1.0:
            _warnings.warn(
                f"[SPLIT GUARDRAIL] Input durations differ significantly: "
                f"left={left_info.duration:.1f}s, right={right_info.duration:.1f}s. "
                f"Output will be truncated to the shorter.",
                stacklevel=3,
            )
        left_fps = getattr(left_info, "fps", None)
        right_fps = getattr(right_info, "fps", None)
        if left_fps and right_fps and abs(left_fps - right_fps) > 1.0:
            _warnings.warn(
                f"[SPLIT GUARDRAIL] Input frame rates differ: "
                f"left={left_fps:.1f}fps, right={right_fps:.1f}fps. "
                f"Output may stutter.",
                stacklevel=3,
            )
        left_has_audio = getattr(left_info, "audio_codec", None) is not None
        right_has_audio = getattr(right_info, "audio_codec", None) is not None
        if right_has_audio and not left_has_audio:
            _warnings.warn(
                "[SPLIT GUARDRAIL] Right video has audio but left does not. "
                "Only left audio is mapped; right audio will be lost.",
                stacklevel=3,
            )
    except Exception as e:
        message = f"[SPLIT GUARDRAIL] Could not validate split-screen inputs: {e}"
        logger.warning(message, exc_info=True)
        _warnings.warn(message, stacklevel=3)


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
    _warn_split_screen_guardrails(left_info, right_info)

    left_w = getattr(left_info, "display_width", left_info.width) or left_info.width
    left_h = getattr(left_info, "display_height", left_info.height) or left_info.height
    right_w = getattr(right_info, "display_width", right_info.width) or right_info.width
    right_h = getattr(right_info, "display_height", right_info.height) or right_info.height
    filter_complex = _split_filter(left_w, left_h, right_w, right_h, layout)

    with _timed_operation() as timing, _atomic_output(output) as staged:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                left_path,
                right_path,
                output_path=staged,
                extra=[
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[v]",
                    "-map",
                    "0:a?",
                    "-pix_fmt",
                    "yuv420p",
                ],
            )
        )

        result = _build_edit_result(staged, f"split_screen_{layout}", timing)
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result


def _even_dim(value: int) -> int:
    return max(2, value + (value % 2))


def _split_filter(left_width: int, left_height: int, right_width: int, right_height: int, layout: SplitLayout) -> str:
    if layout not in ("side-by-side", "top-bottom"):
        raise MCPVideoError("Unknown split-screen layout", error_type="validation_error", code="invalid_layout")
    if layout == "side-by-side":
        target_h = _safe_dimension(_even_dim(max(left_height, right_height)), "target_h")
        needs_scale = left_height != right_height or left_height % 2 != 0 or left_width % 2 != 0 or right_width % 2 != 0
        if needs_scale:
            return (
                f"[0:v]scale='max(2,trunc(iw*sar/2)*2)':ih,setsar=1,scale=-2:{target_h},setsar=1[left];"
                f"[1:v]scale='max(2,trunc(iw*sar/2)*2)':ih,setsar=1,scale=-2:{target_h},setsar=1[right];"
                r"[left][right]hstack=inputs=2,pad=iw+mod(iw\,2):ih+mod(ih\,2)[v]"
            )
        return "[0:v][1:v]hstack=inputs=2[v]"

    target_w = _safe_dimension(_even_dim(max(left_width, right_width)), "target_w")
    needs_scale = left_width != right_width or left_width % 2 != 0 or left_height % 2 != 0 or right_height % 2 != 0
    if needs_scale:
        return (
            f"[0:v]scale='max(2,trunc(iw*sar/2)*2)':ih,setsar=1,scale={target_w}:-2,setsar=1[top];"
            f"[1:v]scale='max(2,trunc(iw*sar/2)*2)':ih,setsar=1,scale={target_w}:-2,setsar=1[bottom];"
            r"[top][bottom]vstack=inputs=2,pad=iw+mod(iw\,2):ih+mod(ih\,2)[v]"
        )
    return "[0:v][1:v]vstack=inputs=2[v]"


def _safe_dimension(value: int, name: str) -> str:
    return _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, name)))
