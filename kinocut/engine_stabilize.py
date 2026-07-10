"""Video stabilization operation for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .engine_runtime_utils import (
    _build_edit_result,
    _ffmpeg,
    _require_filter,
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
from .errors import MCPVideoError, ProcessingError, parse_ffmpeg_error
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .limits import DEFAULT_FFMPEG_TIMEOUT
from .models import EditResult


def stabilize(
    input_path: str,
    smoothing: float = 15,
    zooming: float = 0,
    output_path: str | None = None,
) -> EditResult:
    """Stabilize a shaky video with FFmpeg vidstab detect/transform passes.

    Args:
        input_path: Path to the input video.
        smoothing: Smoothing strength (higher is more stable).
        zooming: Zoom percentage to avoid black borders.
        output_path: Optional output video path.
    """
    input_path = _validate_input_path(input_path)
    _require_filter("vidstabdetect", "Video stabilization")
    output = output_path or _auto_output(input_path, "stabilized")
    _validate_output_path(output)

    safe_smoothing = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(smoothing, "smoothing")))
    safe_zooming = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(zooming, "zooming")))

    with _timed_operation() as timing:
        tmpdir = tempfile.mkdtemp(prefix="mcp_video_stab_")
        try:
            vectors_file = os.path.join(tmpdir, "vectors.trf")
            _detect_motion_vectors(input_path, vectors_file)

            safe_vectors_file = _escape_ffmpeg_filter_value(vectors_file)
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
                    video_filter=f"vidstabtransform=input={safe_vectors_file}:smoothing={safe_smoothing}:zoom={safe_zooming}:crop=black",
                )
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return _build_edit_result(
        output,
        "stabilize",
        timing,
    )


def _detect_motion_vectors(input_path: str, vectors_file: str) -> None:
    if not os.path.isabs(vectors_file):
        raise MCPVideoError(
            f"Vectors file path must be absolute, got: {vectors_file!r}",
            error_type="validation_error",
            code="invalid_path",
        )
    safe_vectors_file = _escape_ffmpeg_filter_value(vectors_file)
    try:
        result = subprocess.run(  # noqa: S603
            [
                _ffmpeg(),
                "-y",
                "-i",
                input_path,
                "-vf",
                "vidstabdetect=shakiness=10:accuracy=15:result=" + safe_vectors_file,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            # Some FFmpeg builds (e.g. Debian 5.1 vidstab) emit raw binary on
            # stderr; strict UTF-8 decoding would crash the whole operation.
            encoding="utf-8",
            errors="replace",
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(
            f"ffmpeg -i {os.path.basename(input_path)} -vf vidstabdetect",
            -1,
            f"Video stabilization analysis timed out after {DEFAULT_FFMPEG_TIMEOUT} seconds",
        ) from exc
    if result.returncode != 0:
        raise parse_ffmpeg_error(result.stderr)
