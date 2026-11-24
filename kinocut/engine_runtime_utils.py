"""Runtime helper utilities for the FFmpeg engine."""

from __future__ import annotations

import base64
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar

from .bounded_process import run_bounded
from .errors import (
    FFmpegNotFoundError,
    FFprobeNotFoundError,
    MCPVideoError,
    ProcessingError,
)
from .limits import DEFAULT_CRF, DEFAULT_PRESET, DOCTOR_COMMAND_TIMEOUT, resolve_ffmpeg_timeout
from .models import EditResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FFmpeg / FFprobe availability
# ---------------------------------------------------------------------------


def _find_executable(name: str) -> str:
    env_name = {
        "ffmpeg": "KINOCUT_FFMPEG_EXECUTABLE",
        "ffprobe": "KINOCUT_FFPROBE_EXECUTABLE",
    }.get(name)
    if env_name:
        configured = os.environ.get(env_name, "").strip()
        if configured:
            expected = f"{name}.exe" if os.name == "nt" else name
            if (
                os.path.basename(configured).lower() == expected
                and os.path.isfile(configured)
                and os.access(configured, os.X_OK)
            ):
                return configured
            raise FFmpegNotFoundError() if name == "ffmpeg" else FFprobeNotFoundError()
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
        timeout = resolve_ffmpeg_timeout(default=10)
        try:
            proc = run_bounded([_ffmpeg(), "-filters"], timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ProcessingError(
                "ffmpeg -filters", -1, "", reason=f"FFmpeg filter probe timed out after {timeout:g}s"
            ) from None
        if proc.returncode != 0:
            return False
        parsed = set()
        for line in proc.stdout.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 3 and "->" in parts[2]:
                parsed.add(parts[1])
        if parsed:
            _AVAILABLE_FILTERS = parsed
        return name in parsed
    return name in _AVAILABLE_FILTERS


def _require_filter(name: str, feature: str) -> None:
    """Raise an error if a required FFmpeg filter is not available.

    The feature is a shipped label, so it is published. The filter's own
    name is not: one caller reaches it through the filter table it was
    given, so the name is not provably ours at every call site.
    """
    if not _check_filter_available(name):
        raise MCPVideoError(
            f"{feature} needs an FFmpeg filter that this build does not have.\n"
            f"Install with: brew install ffmpeg (macOS) or rebuild FFmpeg with "
            f"libfreetype/libass support.",
            error_type="dependency_error",
            code="missing_filter",
            suggested_action={
                "auto_fix": False,
                "description": f"Reinstall FFmpeg with the filters {feature} needs. On macOS: brew reinstall ffmpeg",
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
    format: str | None = None,
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
    resolved_format = format or os.path.splitext(output_path)[1].lstrip(".").lower() or info.format or "mp4"
    return EditResult(
        output_path=output_path,
        duration=info.duration,
        resolution=None if audio_only else info.resolution,
        size_mb=info.size_mb,
        format=resolved_format,
        operation=operation,
        elapsed_ms=timing["elapsed_ms"],
        progress=progress,
        thumbnail_base64=thumbnail_base64,
    )


def _transactional_edit(
    output: str,
    operation: str,
    render: Callable[[str], None],
    *,
    build_result: Callable[[str], EditResult] | None = None,
) -> EditResult:
    """Render and probe the staged media before publishing a finalized result."""
    from .ffmpeg_helpers import _atomic_output, _validate_output_path

    with _timed_operation() as timing, _atomic_output(output) as staged:
        _validate_output_path(staged)
        render(staged)
        result = _build_edit_result(staged, operation, timing) if build_result is None else build_result(staged)
    return result.model_copy(update={"output_path": output, "elapsed_ms": timing["elapsed_ms"]})


class StagedProgress:
    """Map local 0-100 percentages onto weighted parts of an operation."""

    def __init__(self, callback: Callable[[float], None] | None, *weights: float):
        total = sum(weights)
        if not weights or not math.isfinite(total) or any(weight <= 0 for weight in weights):
            raise ValueError("Progress stages need positive, finite weights")
        self._callback = callback
        self._bounds = [0.0]
        self._highest = 0.0
        cumulative = 0.0
        for weight in weights:
            cumulative += weight
            self._bounds.append(100 * (cumulative / total))

    def stage(self, index: int) -> Callable[[float], None] | None:
        if not 0 <= index < len(self._bounds) - 1:
            raise IndexError("Progress stage out of range")
        callback = self._callback
        if callback is None:
            return None
        start, end = self._bounds[index : index + 2]

        def report(percent: float) -> None:
            mapped = end if percent >= 100 else start + (end - start) * max(0.0, percent) / 100
            if mapped < self._highest:
                mapped = self._highest
            else:
                self._highest = mapped
            callback(mapped)

        return report


_PROCESS_OWNERSHIP_ERROR_CODES = frozenset({"process_ownership_unavailable", "process_cleanup_failed"})


def _generate_thumbnail_base64(video_path: str) -> str | None:
    """Generate a base64-encoded JPEG thumbnail from the first frame of a video.

    Returns base64 string or None if generation fails.
    """
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        proc = run_bounded(
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
            timeout=resolve_ffmpeg_timeout(default=DOCTOR_COMMAND_TIMEOUT),
        )

        if proc.returncode != 0 or not os.path.isfile(tmp_path):
            return None

        with open(tmp_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("ascii")
    except MCPVideoError as exc:
        if exc.code in _PROCESS_OWNERSHIP_ERROR_CODES:
            raise
        logger.warning("Thumbnail generation failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Thumbnail generation failed: %s", exc)
        return None
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            os.unlink(tmp_path)


_intermediate_dir: ContextVar[str | None] = ContextVar("intermediate_mux_dir", default=None)


@contextmanager
def _intermediate_outputs(directory: str):
    """Skip progressive-download layout only for files in this private workdir."""
    token = _intermediate_dir.set(os.path.realpath(directory))
    try:
        yield
    finally:
        _intermediate_dir.reset(token)


_AUDIO_COPY_MUX_REJECT_MARKERS = (
    "codec not currently supported in container",
    "could not find tag for codec",
    "codec frame size is not set",
    "incompatible with output codec",
)


_AVI_CODEC_HEADER_REASONS = (
    "invalid argument",
    "not implemented",
    "invalid data found when processing input",
    "operation not permitted",
)


def _is_audio_copy_mux_rejection(stderr_lower: str) -> bool:
    if "out#0/avi" in stderr_lower:
        header_lines = [line for line in stderr_lower.splitlines() if "could not write header" in line]
        if header_lines:
            return any(
                any(marker in line.rsplit(":", 1)[-1].strip() for marker in _AVI_CODEC_HEADER_REASONS)
                for line in header_lines
            )
    return any(marker in stderr_lower for marker in _AUDIO_COPY_MUX_REJECT_MARKERS)


def _command_has_audio_input(args: list[str]) -> bool:
    from .engine_probe import probe

    for idx, arg in enumerate(args[:-1]):
        if arg != "-i":
            continue
        try:
            if probe(args[idx + 1]).audio_codec:
                return True
        except Exception:
            return True
    return False


def _run_video_only(runner, args: list[str], *progress) -> None:
    """Keep the selected audio packets unless the output muxer rejects their codec."""
    try:
        runner(args, *progress)
    except ProcessingError as exc:
        stderr_lower = exc.full_stderr.lower()
        if "-c:a" not in args or not _is_audio_copy_mux_rejection(stderr_lower) or not _command_has_audio_input(args):
            raise
        codec = args.index("-c:a") + 1
        if codec >= len(args) or args[codec] != "copy":
            raise
        from .defaults import DEFAULT_AUDIO_BITRATE

        try:
            runner([*args[:codec], "aac", "-b:a", DEFAULT_AUDIO_BITRATE, *args[codec + 1 :]], *progress)
        except ProcessingError as retry_exc:
            if _is_audio_copy_mux_rejection(retry_exc.full_stderr.lower()):
                raise exc from None
            raise


def _movflags_args(output_path: str) -> list[str]:
    """Return -movflags +faststart only for MP4/MOV containers."""
    ext = os.path.splitext(output_path)[1].lower()
    directory = _intermediate_dir.get()
    if ext in (".mp4", ".mov") and (directory is None or os.path.realpath(os.path.dirname(output_path)) != directory):
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


_SCALABLE_FONT_EXTS = (".ttf", ".otf", ".ttc")


def _fontconfig_sans_font() -> str | None:
    """Ask fontconfig for its sans-serif match; only a scalable file FFmpeg can load (#696)."""
    import subprocess

    try:
        out = subprocess.run(
            ["fc-match", "--format=%{file}", "sans-serif"],  # noqa: S607
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    candidate = out.stdout.strip()
    if out.returncode == 0 and candidate.lower().endswith(_SCALABLE_FONT_EXTS) and os.path.isfile(candidate):
        return candidate
    return None


def _default_font() -> str:
    """Return a verified default font file or raise a typed dependency error."""
    import platform

    system = platform.system()
    if system == "Darwin":
        candidates = ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf")
    elif system == "Windows":
        windows = os.environ.get("WINDIR", "C:/Windows").replace("\\", "/")
        candidates = (f"{windows}/Fonts/arial.ttf", f"{windows}/Fonts/segoeui.ttf")
    else:
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    if system not in {"Darwin", "Windows"}:
        fallback = _fontconfig_sans_font()
        if fallback:
            return fallback
    raise MCPVideoError(
        "No suitable font file found. Install a TrueType/OpenType font or specify a font path.",
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
