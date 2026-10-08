"""Probe helpers for the FFmpeg engine."""

from __future__ import annotations

import contextlib
import math
import os
import threading
from typing import Any, NamedTuple

from .errors import InputFileError, MCPVideoError, ProcessingError
from .defaults import DEFAULT_FPS
from .ffmpeg_helpers import _run_ffprobe_json, _validate_input_path
from .models import ExactVideoInfo, VideoInfo
from .engine_runtime_utils import _get_audio_stream, _get_video_stream
from .limits import FFPROBE_EXACT_TIMEOUT, MAX_FILE_SIZE_MB, MAX_VIDEO_DURATION

# ---------------------------------------------------------------------------
# Probe cache — source identity includes replacements and nanosecond changes.
# ---------------------------------------------------------------------------


class _ProbeCacheEntry(NamedTuple):
    info: VideoInfo
    has_video: bool


_probe_cache: dict[tuple[str, int, int, int, int, int], _ProbeCacheEntry] = {}
_MAX_PROBE_CACHE = 256
_probe_cache_lock = threading.Lock()


def _cache_key(path: str) -> tuple[str, int, int, int, int, int]:
    try:
        stat = os.stat(path)
    except OSError as exc:
        raise InputFileError(path, "Cannot inspect media identity") from exc
    return (path, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _cached_info(path: str, key: tuple, *, require_video: bool) -> VideoInfo | None:
    with _probe_cache_lock:
        cached = _probe_cache.get(key)
    if cached is None:
        return None
    if _cache_key(path) != key:
        raise InputFileError(path, "Media changed while reading cached metadata")
    if require_video and not cached.has_video:
        raise InputFileError(path, "No video stream found")
    return cached.info.model_copy(deep=True)


def _cache_info(path: str, key: tuple, info: VideoInfo, *, has_video: bool) -> None:
    if _cache_key(path) != key:
        raise InputFileError(path, "Media changed while probing; retry with a stable source")
    with _probe_cache_lock:
        if len(_probe_cache) >= _MAX_PROBE_CACHE:
            _probe_cache.pop(next(iter(_probe_cache)))
        _probe_cache[key] = _ProbeCacheEntry(info.model_copy(deep=True), has_video)


def _parse_probe_duration(value: Any) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return duration if math.isfinite(duration) and duration >= 0 else None


def _build_video_info(path: str, data: dict) -> VideoInfo:
    """Construct a VideoInfo from raw ffprobe JSON data."""
    vs = _get_video_stream(data)
    if vs is None:
        raise InputFileError(path, "No video stream found")

    # Duration: prefer container duration, then fall back to the video stream.
    duration = _parse_probe_duration(data.get("format", {}).get("duration"))
    if duration is None:
        duration = _parse_probe_duration(vs.get("duration")) or 0.0
    if duration > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            f"Video duration ({duration:.0f}s) exceeds maximum of {MAX_VIDEO_DURATION}s",
            error_type="validation_error",
            code="duration_too_long",
        )

    # Resolution
    try:
        width = int(vs.get("width", 0))
        height = int(vs.get("height", 0))
    except (ValueError, TypeError):
        width = height = 0

    # FPS — r_frame_rate is "num/den"
    rfr = vs.get("r_frame_rate", str(DEFAULT_FPS))
    try:
        if "/" in rfr:
            num, den = rfr.split("/")
            den_val = float(den)
            fps = float(num) / den_val if den_val != 0 else float(DEFAULT_FPS)
        else:
            fps = float(rfr) if float(rfr) != 0 else float(DEFAULT_FPS)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        fps = float(DEFAULT_FPS)
    if not math.isfinite(fps) or fps <= 0:
        # ffprobe reports r_frame_rate as "0/1" for some attached-pic and
        # audio-derived video streams; 0 fps poisons all downstream frame math.
        fps = float(DEFAULT_FPS)

    # Codecs
    codec = vs.get("codec_name", "unknown")
    audio_s = _get_audio_stream(data)
    audio_codec = audio_s.get("codec_name") if audio_s else None
    audio_sr = int(audio_s.get("sample_rate", 0)) if audio_s else None

    # Rotation from side_data_list
    rotation = 0
    for side in vs.get("side_data_list", []):
        rot = side.get("rotation")
        if rot is not None:
            with contextlib.suppress(ValueError, TypeError):
                rotation = int(rot)
            break

    # Bitrate / size
    fmt = data.get("format", {})
    try:
        bitrate_raw = fmt.get("bit_rate", 0)
        bitrate = int(bitrate_raw) if bitrate_raw and 0 < int(bitrate_raw) <= 1_000_000_000 else None
        size_raw = fmt.get("size", 0)
        size_bytes = int(size_raw) if size_raw and 0 < int(size_raw) <= MAX_FILE_SIZE_MB * 1024 * 1024 else None
    except (ValueError, TypeError):
        bitrate = size_bytes = None
    fmt_name = fmt.get("format_name")

    return VideoInfo(
        path=path,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        codec=codec,
        audio_codec=audio_codec,
        audio_sample_rate=audio_sr,
        bitrate=bitrate,
        size_bytes=size_bytes,
        format=fmt_name,
        rotation=rotation,
    )


def probe(path: str) -> VideoInfo:
    """Get metadata about a video file using ffprobe.

    Results are cached by filesystem identity and copied for each caller.
    Changing a source during a probe fails instead of returning mixed metadata.
    """
    path = _validate_input_path(path)
    key = _cache_key(path)

    cached = _cached_info(path, key, require_video=True)
    if cached is not None:
        return cached

    try:
        data = _run_ffprobe_json(path)
    except ProcessingError as exc:
        raise InputFileError(path, "Not a valid video file") from exc
    info = _build_video_info(path, data)

    _cache_info(path, key, info, has_video=True)
    return info


def _raw_rational_rate(value: object) -> str | None:
    """Return ffprobe's rate string unchanged when it is a usable positive rate, else ``None``."""
    if not isinstance(value, str):
        return None
    try:
        if "/" in value:
            num_text, den_text = value.split("/", 1)
            num, den = float(num_text), float(den_text)
            usable = den != 0 and num > 0
        else:
            usable = float(value) > 0
    except (ValueError, OverflowError):
        return None
    return value if usable else None


def _exact_stream_fields(video_stream: dict) -> dict[str, object]:
    """Exact facts taken from ffprobe's video stream entry; unmeasured values stay ``None``."""
    frame_count: int | None = None
    raw_count = video_stream.get("nb_read_frames")
    if raw_count is not None:
        try:
            parsed = int(raw_count)
        except (ValueError, TypeError):
            parsed = -1
        if parsed >= 0:
            frame_count = parsed
    return {
        "frame_count": frame_count,
        "frame_count_source": "decoded" if frame_count is not None else None,
        "r_frame_rate": _raw_rational_rate(video_stream.get("r_frame_rate")),
        "avg_frame_rate": _raw_rational_rate(video_stream.get("avg_frame_rate")),
    }


def probe_exact(path: str) -> ExactVideoInfo:
    """Probe a video and also report the decoded frame count and raw rational frame rates.

    Opt-in and uncached: ffprobe decodes the whole video stream (``-count_frames``), so this
    is slower than :func:`probe`. Values that cannot be measured are ``None``, never defaults.
    """
    path = _validate_input_path(path)
    try:
        data = _run_ffprobe_json(path, count_frames=True, timeout=FFPROBE_EXACT_TIMEOUT)
    except ProcessingError as exc:
        raise InputFileError(path, "Not a valid video file, or decoding it for an exact probe failed") from exc
    info = _build_video_info(path, data)
    video_stream = _get_video_stream(data) or {}
    return ExactVideoInfo(**info.model_dump(), **_exact_stream_fields(video_stream))


def probe_audio_input(path: str) -> VideoInfo:
    """Probe an input that may be audio-only, for audio-mix guardrails.

    Calls ``_run_ffprobe_json`` **once** and handles both video and audio-only
    inputs from the same result. Previously this function called ``probe()``
    first (which internally calls ffprobe), then on failure called
    ``_run_ffprobe_json`` again — double-probing every audio-only input.

    Raises:
        InputFileError: if the file is not a valid media file at all, or has
            neither a video nor an audio stream.
    """
    path = _validate_input_path(path)
    key = _cache_key(path)

    cached = _cached_info(path, key, require_video=False)
    if cached is not None:
        return cached

    try:
        data = _run_ffprobe_json(path)
    except ProcessingError as exc:
        raise InputFileError(path, "Not a valid media file") from exc

    # Try video first — reuses the same ffprobe data (no second subprocess)
    try:
        info = _build_video_info(path, data)
    except InputFileError:
        # No video stream — check for audio using the same ffprobe data
        audio_s = _get_audio_stream(data)
        if audio_s is None:
            raise InputFileError(path, "No video or audio stream found") from None

        fmt = data.get("format", {})
        duration = _parse_probe_duration(fmt.get("duration"))
        if duration is None:
            duration = _parse_probe_duration(audio_s.get("duration")) or 0.0
        if duration > MAX_VIDEO_DURATION:
            raise MCPVideoError(
                f"Audio duration ({duration:.0f}s) exceeds maximum of {MAX_VIDEO_DURATION}s",
                error_type="validation_error",
                code="duration_too_long",
            ) from None

        try:
            audio_sr = int(audio_s.get("sample_rate", 0)) or None
        except (ValueError, TypeError):
            audio_sr = None

        info = VideoInfo(
            path=path,
            duration=duration,
            width=0,
            height=0,
            fps=0.0,
            codec="none",
            audio_codec=audio_s.get("codec_name"),
            audio_sample_rate=audio_sr,
            format=fmt.get("format_name"),
        )

    _cache_info(path, key, info, has_video=_get_video_stream(data) is not None)
    return info


def invalidate_probe_cache(path: str | None = None) -> None:
    """Drop cached probe data. Pass a path to evict one entry, or None for all."""
    with _probe_cache_lock:
        if path is None:
            _probe_cache.clear()
        else:
            path = os.path.realpath(path)
            keys_to_remove = [k for k in _probe_cache if k[0] == path]
            for k in keys_to_remove:
                del _probe_cache[k]


def get_duration(path: str) -> float:
    """Get duration of a video in seconds."""
    return probe(path).duration
