"""Probe helpers for the FFmpeg engine."""

from __future__ import annotations

import contextlib
import math
import os
import threading
from typing import Any, NamedTuple

from .errors import InputFileError, MCPVideoError, ProcessingError
from .engine_media_timeline import _parse_probe_duration
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
    aliases: frozenset[str] = frozenset()


_probe_cache: dict[tuple[Any, ...], _ProbeCacheEntry] = {}
_MAX_PROBE_CACHE = 256
_probe_cache_lock = threading.Lock()


def _norm_alias(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _cache_key(path: str) -> tuple[Any, ...]:
    try:
        stat = os.stat(path)
    except OSError as exc:
        raise InputFileError(path, "Cannot inspect media identity") from exc
    if stat.st_ino:
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return (path, stat.st_dev, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _cached_info(path: str, key: tuple, *, require_video: bool, alias: str | None = None) -> VideoInfo | None:
    cache_id = (os.path.normcase(path), key)
    with _probe_cache_lock:
        cached = _probe_cache.get(cache_id)
        if cached is not None and alias and alias not in cached.aliases:
            cached = cached._replace(aliases=cached.aliases | {alias})
            _probe_cache[cache_id] = cached
    if cached is None:
        return None
    if _cache_key(path) != key:
        raise InputFileError(path, "Media changed while reading cached metadata")
    if require_video and not cached.has_video:
        raise InputFileError(path, "No video stream found")
    return cached.info.model_copy(deep=True, update={"path": path})


def _cache_info(path: str, key: tuple, info: VideoInfo, *, has_video: bool, alias: str | None = None) -> None:
    if _cache_key(path) != key:
        raise InputFileError(path, "Media changed while probing; retry with a stable source")
    cache_id = (os.path.normcase(path), key)
    aliases = frozenset({os.path.normcase(path), *({alias} if alias else ())})
    with _probe_cache_lock:
        existing = _probe_cache.get(cache_id)
        if existing is not None:
            aliases |= existing.aliases
        elif len(_probe_cache) >= _MAX_PROBE_CACHE:
            _probe_cache.pop(next(iter(_probe_cache)))
        _probe_cache[cache_id] = _ProbeCacheEntry(info.model_copy(deep=True), has_video, aliases)


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

    # Codecs & stream geometry metadata
    codec = vs.get("codec_name", "unknown")
    audio_s = _get_audio_stream(data)
    audio_codec = audio_s.get("codec_name") if audio_s else None
    audio_sr = int(audio_s.get("sample_rate", 0)) if audio_s else None
    audio_channels: int | None = None
    if audio_s:
        try:
            ch_val = int(audio_s.get("channels", 0))
            audio_channels = ch_val if ch_val > 0 else None
        except (ValueError, TypeError):
            audio_channels = None
    audio_stream_count = sum(1 for s in data.get("streams", []) if s.get("codec_type") == "audio")

    raw_sar = vs.get("sample_aspect_ratio")
    sample_aspect_ratio = (
        str(raw_sar)
        if isinstance(raw_sar, str)
        and raw_sar.strip()
        and raw_sar.strip() not in ("N/A", "unknown", "0:1", "0/1", "0:0", "0/0")
        else None
    )
    raw_pix_fmt = vs.get("pix_fmt")
    pix_fmt = str(raw_pix_fmt) if isinstance(raw_pix_fmt, str) and raw_pix_fmt.strip() else None
    avg_frame_rate = _raw_rational_rate(vs.get("avg_frame_rate"))

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
        audio_channels=audio_channels,
        audio_stream_count=audio_stream_count,
        bitrate=bitrate,
        size_bytes=size_bytes,
        format=fmt_name,
        rotation=rotation,
        sample_aspect_ratio=sample_aspect_ratio,
        pix_fmt=pix_fmt,
        avg_frame_rate=avg_frame_rate,
    )


def _is_probe_timeout(exc: ProcessingError) -> bool:
    return "timed out" in str(exc).lower() or exc.code == "timeout"


def probe(path: str) -> VideoInfo:
    """Get metadata about a video file using ffprobe.

    Results are cached by filesystem identity and copied for each caller.
    Changing a source during a probe fails instead of returning mixed metadata.
    """
    raw_alias = _norm_alias(path)
    path = _validate_input_path(path)
    key = _cache_key(path)

    cached = _cached_info(path, key, require_video=True, alias=raw_alias)
    if cached is not None:
        return cached

    data = _read_input_metadata(path, require_video=True)
    info = _build_video_info(path, data)

    _cache_info(path, key, info, has_video=True, alias=raw_alias)
    return info


def _read_input_metadata(path: str, *, require_video: bool = False) -> dict:
    key = _cache_key(path)
    try:
        data = _run_ffprobe_json(path)
    except ProcessingError as exc:
        if _is_probe_timeout(exc):
            raise
        kind = "video" if require_video else "media"
        raise InputFileError(path, f"Not a valid {kind} file") from exc
    if _cache_key(path) != key:
        raise InputFileError(path, "Media changed while probing; retry with a stable source")
    return data


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


def _exact_stream_fields(video_stream: dict) -> dict[str, Any]:
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
        if _is_probe_timeout(exc):
            raise
        raise InputFileError(path, "Not a valid video file, or decoding it for an exact probe failed") from exc
    info = _build_video_info(path, data)
    video_stream = _get_video_stream(data) or {}
    return ExactVideoInfo(**{**info.model_dump(), **_exact_stream_fields(video_stream)})


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
    raw_alias = _norm_alias(path)
    path = _validate_input_path(path)
    key = _cache_key(path)

    cached = _cached_info(path, key, require_video=False, alias=raw_alias)
    if cached is not None:
        return cached

    data = _read_input_metadata(path)
    info = _build_audio_input_info(path, data)
    _cache_info(path, key, info, has_video=_get_video_stream(data) is not None, alias=raw_alias)
    return info


def _build_audio_input_info(path: str, data: dict) -> VideoInfo:
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
        try:
            ch_val = int(audio_s.get("channels", 0))
            audio_channels = ch_val if ch_val > 0 else None
        except (ValueError, TypeError):
            audio_channels = None
        audio_stream_count = sum(1 for s in data.get("streams", []) if s.get("codec_type") == "audio")

        info = VideoInfo(
            path=path,
            duration=duration,
            width=0,
            height=0,
            fps=0.0,
            codec="none",
            audio_codec=audio_s.get("codec_name"),
            audio_sample_rate=audio_sr,
            audio_channels=audio_channels,
            audio_stream_count=audio_stream_count,
            format=fmt.get("format_name"),
        )

    return info


def invalidate_probe_cache(path: str | None = None) -> None:
    """Drop cached probe data. Pass a path to evict one entry, or None for all."""
    with _probe_cache_lock:
        if path is None:
            _probe_cache.clear()
        else:
            targets = {_norm_alias(path), os.path.normcase(os.path.realpath(path))}
            keys_to_remove = [
                k for k, entry in _probe_cache.items() if k[0] in targets or bool(entry.aliases & targets)
            ]
            for k in keys_to_remove:
                del _probe_cache[k]


def get_duration(path: str) -> float:
    """Get duration of a video in seconds."""
    return probe(path).duration
