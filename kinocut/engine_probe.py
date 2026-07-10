"""Probe helpers for the FFmpeg engine."""

from __future__ import annotations

import contextlib
import os
import threading
from typing import Any

from .errors import InputFileError, MCPVideoError, ProcessingError
from .ffmpeg_helpers import _run_ffprobe_json, _validate_input_path
from .models import VideoInfo
from .engine_runtime_utils import _get_audio_stream, _get_video_stream
from .limits import MAX_FILE_SIZE_MB, MAX_VIDEO_DURATION

# ---------------------------------------------------------------------------
# Probe cache — keyed by (path, mtime, size) so stale data is never returned
# ---------------------------------------------------------------------------

_probe_cache: dict[tuple[str, float, int], VideoInfo] = {}
_MAX_PROBE_CACHE = 256
_probe_cache_lock = threading.Lock()


def _cache_key(path: str) -> tuple[str, float, int]:
    stat = os.stat(path)
    return (path, stat.st_mtime, stat.st_size)


def _parse_probe_duration(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    rfr = vs.get("r_frame_rate", "30/1")
    try:
        if "/" in rfr:
            num, den = rfr.split("/")
            den_val = float(den)
            fps = float(num) / den_val if den_val != 0 else 30.0
        else:
            fps = float(rfr) if float(rfr) != 0 else 30.0
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    if fps <= 0:
        # ffprobe reports r_frame_rate as "0/1" for some attached-pic and
        # audio-derived video streams; 0 fps poisons all downstream frame math.
        fps = 30.0

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

    Results are cached by (path, mtime, size) so repeated calls on the
    same unmodified file skip the ffprobe subprocess.
    """
    path = _validate_input_path(path)
    key = _cache_key(path)

    with _probe_cache_lock:
        cached = _probe_cache.get(key)
        if cached is not None:
            return cached

    try:
        data = _run_ffprobe_json(path)
    except ProcessingError as exc:
        raise InputFileError(path, "Not a valid video file") from exc
    info = _build_video_info(path, data)

    with _probe_cache_lock:
        # Evict oldest entries when cache is full
        if len(_probe_cache) >= _MAX_PROBE_CACHE:
            _probe_cache.pop(next(iter(_probe_cache)))
        _probe_cache[key] = info

    return info


def probe_audio_input(path: str) -> VideoInfo:
    """Probe an input that may be audio-only, for audio-mix guardrails.

    ``probe`` requires a video stream and raises ``InputFileError`` for valid
    audio-only files (e.g. a voiceover WAV), which made audio guardrails emit a
    misleading "No video stream found" warning (issue #7). This variant first
    tries the standard video probe; if no video stream is present but a valid
    audio stream is, it synthesizes a ``VideoInfo`` carrying the audio metadata
    (duration, codec, sample rate) that ``validate_audio_mix`` actually reads.
    Video-shaped fields are zeroed because the input genuinely has no video.

    Raises:
        InputFileError: if the file is not a valid media file at all, or has
            neither a video nor an audio stream.
    """
    path = _validate_input_path(path)

    try:
        return probe(path)
    except InputFileError:
        # No video stream (or not a valid *video*). Fall back to an audio-aware
        # probe before treating the input as broken.
        pass

    try:
        data = _run_ffprobe_json(path)
    except ProcessingError as exc:
        raise InputFileError(path, "Not a valid media file") from exc

    audio_s = _get_audio_stream(data)
    if audio_s is None:
        # Neither video nor audio — genuinely unusable input.
        raise InputFileError(path, "No video or audio stream found")

    fmt = data.get("format", {})
    duration = _parse_probe_duration(fmt.get("duration"))
    if duration is None:
        duration = _parse_probe_duration(audio_s.get("duration")) or 0.0
    if duration > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            f"Audio duration ({duration:.0f}s) exceeds maximum of {MAX_VIDEO_DURATION}s",
            error_type="validation_error",
            code="duration_too_long",
        )

    try:
        audio_sr = int(audio_s.get("sample_rate", 0)) or None
    except (ValueError, TypeError):
        audio_sr = None

    return VideoInfo(
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


def invalidate_probe_cache(path: str | None = None) -> None:
    """Drop cached probe data. Pass a path to evict one entry, or None for all."""
    with _probe_cache_lock:
        if path is None:
            _probe_cache.clear()
        else:
            keys_to_remove = [k for k in _probe_cache if k[0] == path]
            for k in keys_to_remove:
                del _probe_cache[k]


def get_duration(path: str) -> float:
    """Get duration of a video in seconds."""
    return probe(path).duration
