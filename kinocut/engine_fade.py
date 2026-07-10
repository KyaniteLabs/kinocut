"""Fade operation for the FFmpeg engine."""

from __future__ import annotations

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
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .errors import MCPVideoError
from .models import EditResult


def fade(
    input_path: str,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
) -> EditResult:
    """Add fade in/out effect to a video."""
    input_path = _validate_input_path(input_path)
    fade_in = _sanitize_ffmpeg_number(fade_in, "fade_in")
    fade_out = _sanitize_ffmpeg_number(fade_out, "fade_out")
    if fade_in <= 0 and fade_out <= 0:
        raise MCPVideoError("Specify fade_in and/or fade_out > 0", code="no_fade")

    output = output_path or _auto_output(input_path, "faded")
    _validate_output_path(output)
    info = probe(input_path)

    vf_parts: list[str] = []
    if fade_in > 0:
        vf_parts.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        fade_start = max(0, info.duration - fade_out)
        vf_parts.append(f"fade=t=out:st={fade_start:.3f}:d={fade_out}")

    vf = ",".join(vf_parts)

    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=output,
                video_filter=vf,
                audio_codec="copy",
                crf=crf,
                preset=preset,
            )
        )

    return _build_edit_result(
        output,
        "fade",
        timing,
    )
