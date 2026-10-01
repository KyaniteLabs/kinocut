"""Preview generation operation for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _atomic_output
from .ffmpeg_helpers import _build_ffmpeg_cmd, _validate_input_path, _validate_output_path
from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError
from .models import PREVIEW_PRESETS, EditResult


def preview(
    input_path: str,
    output_path: str | None = None,
    scale_factor: int = 4,
) -> EditResult:
    """Generate a fast low-resolution preview for quick review."""
    input_path = _validate_input_path(input_path)
    if type(scale_factor) is not int or scale_factor < 1:
        raise MCPVideoError(
            "scale_factor must be a positive integer", error_type="validation_error", code="invalid_scale_factor"
        )
    info = probe(input_path)

    w = max(info.width // scale_factor, 320)
    h = max(info.height // scale_factor, 240)

    output = output_path or _auto_output(input_path, "preview")
    _validate_output_path(output)

    with _timed_operation() as timing, _atomic_output(output) as staged:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=staged,
                video_filter=f"scale={w}:{h}",
                crf=PREVIEW_PRESETS["crf"],
                preset=PREVIEW_PRESETS["preset"],
                audio_bitrate="64k",
                extra=["-ac", "2"],
            )
        )

        result = _build_edit_result(
            staged,
            "preview",
            timing,
        )
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result
