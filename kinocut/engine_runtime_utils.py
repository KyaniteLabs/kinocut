"""Runtime helper utilities for the FFmpeg engine."""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager

from .errors import (
    FFmpegNotFoundError,
    FFprobeNotFoundError,
    MCPVideoError,
)
from .limits import DEFAULT_CRF, DEFAULT_PRESET, DOCTOR_COMMAND_TIMEOUT
from .models import EditResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FFmpeg / FFprobe availability
# ---------------------------------------------------------------------------


def _find_executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FFmpegNotFoundError() if name == "ffmpeg" else FFprobeNotFoundError()
    return path


_FFMPEG = _FFPROBE = ""
_AVAILABLE_FILTERS: set[str] | None = None


def _ffmpeg() -> str:
    global _FFMPEG
    if not _FFMPEG:
        _FFMPEG = _find_executable("ffmpeg")
    return _FFMPEG


def _ffprobe() -> str:
    global _FFPROBE
    if not _FFPROBE:
        _FFPROBE = _find_executable("ffprobe")
    return _FFPROBE


def _check_filter_available(name: str) -> bool:
    """Check if an FFmpeg filter is available."""
    global _AVAILABLE_FILTERS
    if _AVAILABLE_FILTERS is None:
        proc = subprocess.run(  # noqa: S603
            [_ffmpeg(), "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _AVAILABLE_FILTERS = set()
        for line in proc.stdout.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 3 and "->" in parts[2]:
                _AVAILABLE_FILTERS.add(parts[1])
    return name in _AVAILABLE_FILTERS


def _require_filter(name: str, feature: str) -> None:
    """Raise an error if a required FFmpeg filter is not available."""
    if not _check_filter_available(name):
        raise MCPVideoError(
            f"FFmpeg filter '{name}' is not available. {feature} requires FFmpeg "
            f"to be compiled with additional libraries.\n"
            f"Install with: brew install ffmpeg (macOS) or rebuild FFmpeg with "
            f"libfreetype/libass support.",
            error_type="dependency_error",
            code=f"missing_filter_{name}",
            suggested_action={
                "auto_fix": False,
                "description": f"Reinstall FFmpeg with {name} support. On macOS: brew reinstall ffmpeg",
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _timed_operation() -> Generator[dict[str, float | None]]:
    """Context manager that measures wall-clock elapsed time in ms.

    Usage::

        with _timed_operation() as timing:
            _run_ffmpeg([...])
        result = EditResult(..., elapsed_ms=timing["elapsed_ms"])
    """
    timing: dict[str, float | None] = {"elapsed_ms": None}
    start = time.monotonic()
    try:
        yield timing
    finally:
        timing["elapsed_ms"] = (time.monotonic() - start) * 1000


def _build_edit_result(
    output_path: str,
    operation: str,
    timing: dict[str, float | None],
    format: str = "mp4",
    *,
    audio_only: bool = False,
    progress: float | None = None,
    thumbnail_base64: str | None = None,
) -> EditResult:
    """Build an EditResult by probing the output and filling standard fields.

    Eliminates the repeated ``info = probe(output); return EditResult(...)``
    pattern found in ~25 engine functions.
    """
    from .engine_probe import probe, probe_audio_input

    info = probe_audio_input(output_path) if audio_only else probe(output_path)
    return EditResult(
        output_path=output_path,
        duration=info.duration,
        resolution=None if audio_only else info.resolution,
        size_mb=info.size_mb,
        format=format,
        operation=operation,
        elapsed_ms=timing["elapsed_ms"],
        progress=progress,
        thumbnail_base64=thumbnail_base64,
    )


def _generate_thumbnail_base64(video_path: str) -> str | None:
    """Generate a base64-encoded JPEG thumbnail from the first frame of a video.

    Returns base64 string or None if generation fails.
    """
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        proc = subprocess.run(  # noqa: S603
            [
                _ffmpeg(),
                "-y",
                "-i",
                video_path,
                "-vframes",
                "1",
                "-q:v",
                "5",
                "-vf",
                "scale=320:-1",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=DOCTOR_COMMAND_TIMEOUT,
        )

        if proc.returncode != 0 or not os.path.isfile(tmp_path):
            return None

        with open(tmp_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("ascii")
    except Exception as exc:
        logger.warning("Thumbnail generation failed: %s", exc)
        return None
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            os.unlink(tmp_path)


def _movflags_args(output_path: str) -> list[str]:
    """Return -movflags +faststart only for MP4/MOV containers."""
    ext = os.path.splitext(output_path)[1].lower()
    if ext in (".mp4", ".mov"):
        return ["-movflags", "+faststart"]
    return []


def _quality_args(
    crf: int | None = None,
    preset: str | None = None,
    default_crf: int = DEFAULT_CRF,
    default_preset: str = DEFAULT_PRESET,
) -> list[str]:
    """Build FFmpeg quality args [-preset, X, -crf, Y].

    If crf or preset are provided, they override the defaults.
    """
    return ["-preset", preset or default_preset, "-crf", str(crf if crf is not None else default_crf)]


def _default_font() -> str:
    """Return a sensible default font path for the current OS."""
    import platform

    system = platform.system()
    if system == "Darwin":
        return "/System/Library/Fonts/Helvetica.ttc"
    elif system == "Windows":
        return r"C:/Windows/Fonts/arial.ttf"
    else:
        # Linux — check common locations
        for p in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ]:
            if os.path.isfile(p):
                return p
        raise MCPVideoError(
            "No suitable font file found on Linux. Install DejaVu fonts or specify a font path.",
            error_type="dependency_error",
            code="font_not_found",
        )


def _get_video_stream(data: dict) -> dict | None:
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None


def _get_audio_stream(data: dict) -> dict | None:
    for s in data.get("streams", []):
        if s.get("codec_type") == "audio":
            return s
    return None


def _has_audio(data: dict) -> bool:
    return _get_audio_stream(data) is not None
