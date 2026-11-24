"""Bounded presentation timelines for selected media streams."""

from __future__ import annotations

import math
import io
import os
import struct
from fractions import Fraction
import tempfile
from pathlib import Path

from .engine_runtime_utils import _get_video_stream
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


def _parse_probe_duration(value: object) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return duration if math.isfinite(duration) and duration >= 0 else None


def _matroska_picture_extent(stream: dict, start: float | None) -> tuple[float, float] | None:
    # FFmpeg's Matroska DURATION tag is an end timestamp, not a span.
    if start is None or not isinstance(tags := stream.get("tags"), dict):
        return None
    for key, value in tags.items():
        if str(key).upper().split("-", 1)[0] != "DURATION" or not isinstance(value, str):
            continue
        parts = value.strip().split(":")
        if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts[:2]):
            continue
        hours, minutes, seconds = _timestamp(parts[0]), _timestamp(parts[1]), _timestamp(parts[2])
        if hours is None or minutes is None or minutes >= 60 or seconds is None or not 0 <= seconds < 60:
            continue
        span = hours * 3600 + minutes * 60 + seconds - start
        if math.isfinite(span) and span > 0:
            return start, span
    return None


def _parse_rate(value: object) -> Fraction | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    num, den = value.split("/", 1)
    if not (num.isdigit() and den.isdigit()):
        return None
    n, d = int(num), int(den)
    return Fraction(n, d) if n > 0 and d > 0 else None


def _iter_iso_boxes(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", buf[pos : pos + 8])
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", buf[pos + 8 : pos + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        yield kind, pos + hdr, pos + size
        pos += size


def _read_mp4_moov(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            file_size = fh.tell()
            pos = 0
            for _ in range(256):
                if pos + 8 > file_size:
                    return None
                fh.seek(pos)
                hdr = fh.read(8)
                if len(hdr) < 8:
                    return None
                size, kind = struct.unpack(">I4s", hdr)
                hdr_len = 8
                if size == 1:
                    ext = fh.read(8)
                    if len(ext) < 8:
                        return None
                    size = struct.unpack(">Q", ext)[0]
                    hdr_len = 16
                elif size == 0:
                    size = file_size - pos
                if size < hdr_len or pos + size > file_size:
                    return None
                if kind == b"moov":
                    return None if size - hdr_len > 16 * 1024 * 1024 else fh.read(size - hdr_len)
                pos += size
    except OSError:
        return None
    return None


def _elst_exceeds_bframe_reorder(elst: bytes, max_allowed_media_time: int) -> bool:
    if len(elst) < 8:
        return True
    ver = elst[0]
    count = struct.unpack(">I", elst[4:8])[0]
    if count != 1:
        return True
    if ver == 1:
        if len(elst) < 24:
            return True
        _, media_time = struct.unpack(">Qq", elst[8:24])
    elif ver == 0:
        if len(elst) < 16:
            return True
        _, media_time = struct.unpack(">Ii", elst[8:16])
    else:
        return True
    return media_time < 0 or media_time > max_allowed_media_time


def _mp4_has_nontrivial_video_edit_list(path: str, stream: dict, fps: Fraction) -> bool:
    """Fail closed to packet scan if MP4/MOV video tracks carry trimming edit lists."""
    tb = _parse_rate(stream.get("time_base"))
    if tb is None:
        return True
    try:
        max_b = max(int(stream.get("has_b_frames") or 0), 0)
    except (TypeError, ValueError):
        return True
    frame_ticks = round(float(1 / (fps * tb)))
    max_allowed = max_b * max(frame_ticks, 0)
    moov = _read_mp4_moov(path)
    if moov is None:
        return True
    for kind, s, e in _iter_iso_boxes(moov, 0, len(moov)):
        if kind != b"trak":
            continue
        is_video = False
        elsts: list[bytes] = []
        for tk, ts, te in _iter_iso_boxes(moov, s, e):
            if tk == b"mdia":
                for mk, ms, me in _iter_iso_boxes(moov, ts, te):
                    if mk == b"hdlr" and me - ms >= 12 and moov[ms + 8 : ms + 12] == b"vide":
                        is_video = True
            elif tk == b"edts":
                for ek, es, ee in _iter_iso_boxes(moov, ts, te):
                    if ek == b"elst":
                        elsts.append(moov[es:ee])
        if is_video and any(_elst_exceeds_bframe_reorder(elst, max_allowed) for elst in elsts):
            return True
    return False


def _picture_extent(path: str, metadata: dict) -> tuple[float, float]:
    """Trust matching CFR headers; measure packets for VFR, edit lists, or ambiguous timelines."""
    container = metadata.get("format", {})
    stream = _get_video_stream(metadata)
    if stream is None:
        raise _timeline_error("Input has no video stream", "missing_video_stream")
    duration, total = _timestamp(stream.get("duration")), _timestamp(container.get("duration"))
    start, origin = _timestamp(stream.get("start_time")), _timestamp(container.get("start_time"))
    fps = _parse_rate(stream.get("avg_frame_rate"))
    nb_frames_raw = stream.get("nb_frames")
    try:
        nb_frames = int(nb_frames_raw) if nb_frames_raw is not None else 0
    except (TypeError, ValueError):
        nb_frames = 0
    fmt_names = {part.strip().lower() for part in str(container.get("format_name") or "").split(",")}
    if fmt_names & {"matroska", "webm"} and not duration:
        tagged = _matroska_picture_extent(stream, start)
        if tagged is not None:
            return tagged
    is_isobmff = bool(fmt_names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
    if (
        duration is not None
        and duration > 0
        and total is not None
        and abs(duration - total) <= 0.001
        and start is not None
        and origin is not None
        and abs(start - origin) <= 0.001
        and fps is not None
        and stream.get("avg_frame_rate") == stream.get("r_frame_rate")
        and nb_frames > 0
        and abs((nb_frames / float(fps)) - duration) <= 0.001
        and (not is_isobmff or not _mp4_has_nontrivial_video_edit_list(path, stream, fps))
    ):
        return start, duration
    return _packet_extent(path, "v:0")
