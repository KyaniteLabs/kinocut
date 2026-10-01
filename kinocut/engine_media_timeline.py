"""Bounded presentation timelines for selected media streams."""

from __future__ import annotations

import math
import io
import os
import tempfile
from pathlib import Path

from .engine_probe import _parse_probe_duration
from .errors import MCPVideoError
from .ffmpeg_helpers import _run_command
from .limits import FFPROBE_TIMEOUT, MAX_AUDIO_MIX_TIMELINE_METADATA_BYTES, MAX_AUDIO_MIX_TIMELINE_PACKETS


def _timeline_error(message: str, code: str = "invalid_media_duration") -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _source_identity(path: str) -> tuple:
    try:
        stat = Path(path).stat()
    except OSError:
        raise _timeline_error(
            "Source became unavailable while measuring its timeline", "media_source_changed"
        ) from None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _timestamp(value: object) -> float | None:
    """Presentation origins may be negative; durations may not."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _produce_timeline(runner, command, **options):
    try:
        return runner(command, **options)
    except MCPVideoError as error:
        if error.code == "command_stdout_limit_exceeded":
            raise _timeline_error(
                "Stream timeline metadata exceeds the supported limit", "audio_mix_timeline_over_limit"
            ) from error
        raise


def _packet_extent(
    path: str,
    selector: str,
    *,
    runner=_run_command,
    packet_limit: int = MAX_AUDIO_MIX_TIMELINE_PACKETS,
    metadata_limit: int = MAX_AUDIO_MIX_TIMELINE_METADATA_BYTES,
    audio_sample_rate: float | None = None,
) -> tuple[float, float]:
    """Measure PTS extent with a producer sentinel and constant-memory parsing.

    The shared runner checks the byte ceiling before every metadata sink write.
    The packet sentinel and deadline independently bound producer work. Source
    changes during the measurement fail closed; metadata has no producer path.
    """
    identity = _source_identity(path)
    entries = "packet=pts_time,duration_time"
    decoded = []
    if audio_sample_rate is not None:
        entries, decoded = "packet=pts_time:frame=pts_time,nb_samples", ["-show_frames"]
    with tempfile.TemporaryFile() as metadata, tempfile.TemporaryFile() as diagnostics:
        _produce_timeline(
            runner,
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                selector,
                "-read_intervals",
                f"%+#{packet_limit + 1}",
                "-show_packets",
                *decoded,
                "-show_entries",
                entries,
                "-of",
                "compact=p=1" if decoded else "compact=p=0",
                path,
            ],
            timeout=FFPROBE_TIMEOUT,
            stderr_sink=diagnostics,
            stdout_sink=metadata,
            stdout_limit=metadata_limit,
        )
        metadata.flush()
        if _source_identity(path) != identity:
            raise _timeline_error("Source changed while measuring its timeline", "media_source_changed")
        diagnostics.seek(0)
        if diagnostics.read(1):
            raise _timeline_error("Selected stream timeline could not be read cleanly")
        if os.fstat(metadata.fileno()).st_size > metadata_limit:
            raise _timeline_error(
                "Stream timeline metadata exceeds the supported limit", "audio_mix_timeline_over_limit"
            )
        metadata.seek(0)
        with io.TextIOWrapper(metadata, encoding="utf-8") as records:
            if audio_sample_rate is not None:
                return _read_audio_frame_extent(records, packet_limit, audio_sample_rate)
            return _read_packet_extent(records, packet_limit)


def _read_audio_frame_extent(records, packet_limit: int, sample_rate: float) -> tuple[float, float]:
    """Count every producer packet, measuring decoded audio rather than priming metadata."""
    start, end, packets, frames = math.inf, -math.inf, 0, 0
    for line in records:
        parts = line.strip().split("|")
        if parts[0] == "packet":
            packets += 1
            if packets > packet_limit:
                raise _timeline_error("Stream timeline packet limit reached", "audio_mix_timeline_over_limit")
        elif parts[0] == "frame":
            frames += 1
            if frames > packet_limit:
                raise _timeline_error("Stream timeline frame limit reached", "audio_mix_timeline_over_limit")
            fields = dict(part.split("=", 1) for part in parts[1:] if "=" in part)
            pts, samples = _timestamp(fields.get("pts_time")), _parse_probe_duration(fields.get("nb_samples"))
            if pts is None or samples is None or samples <= 0 or not samples.is_integer():
                raise _timeline_error("Selected audio has an unmeasurable frame timeline")
            start, end = min(start, pts), max(end, pts + samples / sample_rate)
        else:
            raise _timeline_error("Selected audio has malformed timeline metadata")
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise _timeline_error("Selected audio has no measurable frame timeline")
    return start, end - start


def _read_packet_extent(packets, packet_limit: int) -> tuple[float, float]:
    start, end = math.inf, -math.inf
    for count, line in enumerate(packets, 1):
        if count > packet_limit:
            raise _timeline_error("Stream timeline packet limit reached", "audio_mix_timeline_over_limit")
        fields = dict(part.split("=", 1) for part in line.strip().split("|") if "=" in part)
        pts = _timestamp(fields.get("pts_time"))
        width = _parse_probe_duration(fields.get("duration_time"))
        if pts is None or not math.isfinite(pts) or width is None or not math.isfinite(width) or width <= 0:
            raise _timeline_error("Selected stream has an unmeasurable packet timeline")
        start, end = min(start, pts), max(end, pts + width)
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise _timeline_error("Selected stream has no measurable packet timeline")
    return start, end - start


def _primary_audio_timeline(path: str, probe: dict) -> tuple[float, float]:
    """Use the same primary audio stream as explicit ``a:0`` filter mappings."""
    audio = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if audio is None:
        raise _timeline_error("Input has no audio stream", "missing_audio_stream")
    start = _timestamp(audio.get("start_time"))
    duration = _parse_probe_duration(audio.get("duration"))
    if duration is not None and math.isfinite(duration) and duration > 0:
        return (start if start is not None and math.isfinite(start) else 0.0), duration
    rate = _parse_probe_duration(audio.get("sample_rate"))
    if rate is None or rate <= 0:
        raise _timeline_error("Selected audio has no usable sample rate")
    # Matroska AAC priming packets may have duration=N/A. A bounded decoded
    # frame extent avoids guessing their width or using a longer video tail.
    return _packet_extent(path, "a:0", audio_sample_rate=rate)
