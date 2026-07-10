"""Format conversion operation for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable

from .defaults import DEFAULT_AUDIO_BITRATE
from .engine_probe import probe
from .engine_runtime_utils import (
    _generate_thumbnail_base64,
    _movflags_args,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _run_ffmpeg,
    _run_ffmpeg_with_progress,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .errors import MCPVideoError
from .models import QUALITY_PRESETS, EditResult, ExportFormat, QualityLevel


def convert(
    input_path: str,
    format: ExportFormat = "mp4",
    quality: QualityLevel = "high",
    output_path: str | None = None,
    on_progress: Callable[[float], None] | None = None,
    two_pass: bool = False,
    target_bitrate: int | None = None,
) -> EditResult:
    """Convert a video to a different format (e.g. mp4 → webm, mp4 → gif).

    Use this when you need to change the container or codec.  For final
    delivery with quality tuning, prefer :func:`export_video`.
    """
    input_path = _validate_input_path(input_path)

    valid_formats = {"mp4", "webm", "gif", "mov", "hevc", "av1", "prores"}
    if format not in valid_formats:
        raise MCPVideoError(
            f"format must be one of {sorted(valid_formats)}, got {format}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if quality not in QUALITY_PRESETS:
        raise MCPVideoError(
            f"quality must be one of {sorted(QUALITY_PRESETS)}, got {quality}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    if two_pass and format not in ("mp4", "mov"):
        raise MCPVideoError(
            f"Two-pass encoding is only supported for mp4 and mov formats, got '{format}'",
            error_type="validation_error",
            code="two_pass_unsupported_format",
        )
    if two_pass and target_bitrate is None:
        raise MCPVideoError(
            "Two-pass encoding requires target_bitrate to be set",
            error_type="validation_error",
            code="two_pass_needs_bitrate",
        )

    preset = QUALITY_PRESETS[quality]
    ext_map = {"hevc": ".mp4", "av1": ".webm", "prores": ".mov"}
    ext = ext_map.get(format, f".{format}") if not format.startswith(".") else format
    output = output_path or _auto_output(input_path, format, ext=ext)
    _validate_output_path(output)
    input_info = probe(input_path)

    with _timed_operation() as timing:
        if two_pass and target_bitrate:
            _convert_two_pass(input_path, output, target_bitrate, preset["preset"])
        elif format == "mp4":
            _convert_mp4(input_path, output, preset, input_info.duration, on_progress)
        elif format == "webm":
            _convert_webm(input_path, output, preset, input_info.duration, on_progress)
        elif format == "mov":
            _convert_mov(input_path, output, preset, input_info.duration, on_progress)
        elif format == "gif":
            _convert_gif(input_path, output, quality, input_info.duration, on_progress)
        elif format == "hevc":
            _convert_hevc(input_path, output, preset, input_info.duration, on_progress)
        elif format == "av1":
            _convert_av1(input_path, output, preset, input_info.duration, on_progress)
        elif format == "prores":
            _convert_prores(input_path, output, preset, input_info.duration, on_progress)
        else:
            raise MCPVideoError(f"Unsupported format: {format}", code="unsupported_format")

    return _convert_result(output, format, timing["elapsed_ms"])


def _convert_two_pass(input_path: str, output: str, target_bitrate: int, preset: str) -> None:
    passlogdir = tempfile.mkdtemp(prefix="mcp_video_2pass_")
    try:
        passlogfile = os.path.join(passlogdir, "pass")
        _run_ffmpeg(
            [
                "-i",
                input_path,
                "-c:v",
                "libx264",
                "-b:v",
                f"{target_bitrate}k",
                "-pass",
                "1",
                "-passlogfile",
                passlogfile,
                "-an",
                "-f",
                "null",
                os.devnull,
            ]
        )
        _run_ffmpeg(
            [
                "-i",
                input_path,
                "-c:v",
                "libx264",
                "-b:v",
                f"{target_bitrate}k",
                "-pass",
                "2",
                "-passlogfile",
                passlogfile,
                "-preset",
                preset,
                "-c:a",
                "aac",
                "-b:a",
                DEFAULT_AUDIO_BITRATE,
                *_movflags_args(output),
                output,
            ]
        )
    finally:
        shutil.rmtree(passlogdir, ignore_errors=True)


def _convert_mp4(
    input_path: str, output: str, preset: dict, duration: float, on_progress: Callable[[float], None] | None
) -> None:
    _run_ffmpeg_with_progress(
        [
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-crf",
            str(preset["crf"]),
            "-preset",
            preset["preset"],
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            DEFAULT_AUDIO_BITRATE,
            "-movflags",
            "+faststart",
            output,
        ],
        estimated_duration=duration,
        on_progress=on_progress,
    )


def _convert_webm(
    input_path: str, output: str, preset: dict, duration: float, on_progress: Callable[[float], None] | None
) -> None:
    _run_ffmpeg_with_progress(
        [
            "-i",
            input_path,
            "-c:v",
            "libvpx-vp9",
            "-crf",
            str(preset["crf"]),
            "-b:v",
            "0",
            "-c:a",
            "libopus",
            output,
        ],
        estimated_duration=duration,
        on_progress=on_progress,
    )


def _convert_mov(
    input_path: str, output: str, preset: dict, duration: float, on_progress: Callable[[float], None] | None
) -> None:
    _run_ffmpeg_with_progress(
        [
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-crf",
            str(preset["crf"]),
            "-preset",
            preset["preset"],
            "-c:a",
            "pcm_s16le",
            output,
        ],
        estimated_duration=duration,
        on_progress=on_progress,
    )


def _convert_gif(
    input_path: str, output: str, quality: QualityLevel, duration: float, on_progress: Callable[[float], None] | None
) -> None:
    gif_scale = {"low": 320, "medium": 480, "high": 640, "ultra": 800}
    gif_fps = {"low": 10, "medium": 12, "high": 15, "ultra": 20}
    width = gif_scale.get(quality, 480)
    fps = gif_fps.get(quality, 15)
    tmpdir = tempfile.mkdtemp(prefix="mcp_video_gif_")
    try:
        palette = os.path.join(tmpdir, "palette.png")
        _run_ffmpeg(
            [
                "-i",
                input_path,
                "-vf",
                f"fps={fps},scale={width}:-1:flags=lanczos,palettegen=max_colors=128",
                "-y",
                palette,
            ]
        )
        _run_ffmpeg_with_progress(
            [
                "-i",
                input_path,
                "-i",
                palette,
                "-lavfi",
                f"fps={fps},scale={width}:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer",
                "-y",
                output,
            ],
            estimated_duration=duration,
            on_progress=on_progress,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _convert_hevc(
    input_path: str, output: str, preset: dict, duration: float, on_progress: Callable[[float], None] | None
) -> None:
    _run_ffmpeg_with_progress(
        [
            "-i",
            input_path,
            "-c:v",
            "libx265",
            "-crf",
            str(preset["crf"]),
            "-preset",
            preset["preset"],
            "-c:a",
            "aac",
            "-b:a",
            DEFAULT_AUDIO_BITRATE,
            "-tag:v",
            "hvc1",
            "-movflags",
            "+faststart",
            output,
        ],
        estimated_duration=duration,
        on_progress=on_progress,
    )


def _convert_av1(
    input_path: str, output: str, preset: dict, duration: float, on_progress: Callable[[float], None] | None
) -> None:
    _run_ffmpeg_with_progress(
        [
            "-i",
            input_path,
            "-c:v",
            "libsvtav1",
            "-crf",
            str(preset["crf"]),
            "-preset",
            preset["preset"],
            "-c:a",
            "libopus",
            output,
        ],
        estimated_duration=duration,
        on_progress=on_progress,
    )


def _convert_prores(
    input_path: str, output: str, preset: dict, duration: float, on_progress: Callable[[float], None] | None
) -> None:
    _run_ffmpeg_with_progress(
        [
            "-i",
            input_path,
            "-c:v",
            "prores_ks",
            "-profile:v",
            "2",
            "-c:a",
            "pcm_s16le",
            output,
        ],
        estimated_duration=duration,
        on_progress=on_progress,
    )


def _convert_result(output: str, format: ExportFormat, elapsed_ms: float | None = None) -> EditResult:
    thumb_b64 = _generate_thumbnail_base64(output) if format != "gif" else None
    if os.path.isfile(output):
        size_mb = os.path.getsize(output) / (1024 * 1024)
        if format != "gif":
            info = probe(output)
            return EditResult(
                output_path=output,
                duration=info.duration,
                resolution=info.resolution,
                size_mb=round(size_mb, 2),
                format=format,
                operation="convert",
                progress=100.0,
                thumbnail_base64=thumb_b64,
                elapsed_ms=elapsed_ms,
            )
    else:
        size_mb = None

    return EditResult(
        output_path=output,
        size_mb=round(size_mb, 2) if size_mb else None,
        format=format,
        operation="convert",
        progress=100.0,
        thumbnail_base64=thumb_b64,
        elapsed_ms=elapsed_ms,
    )
