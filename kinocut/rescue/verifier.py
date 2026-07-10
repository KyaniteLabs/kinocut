"""Independent verification for rescue package artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_command, _run_ffprobe_json
from .models import Metric, VerificationCheck

CHECK_IDS = (
    "source_unchanged", "master_full_decode", "sharing_full_decode", "timeline_duration",
    "monotonic_timestamps", "source_stream_coverage", "audio_video_sync", "caption_sync",
    "spoken_content_coverage", "universal_mp4_contract", "metric_units", "persisted_hashes",
)


def _sha(path: str) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _metric(name: str, value: Any, unit: str, definition: str, available: bool = True) -> Metric:
    return Metric(name=name, value=value, unit=unit, definition=definition, available=available)


def _duration(raw: dict[str, Any]) -> float:
    try:
        return float(raw.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        return 0.0


def _fps(raw: dict[str, Any]) -> float:
    video = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1")
    try:
        num, den = rate.split("/", 1)
        return float(num) / float(den) if float(den) else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def _decode(path: str) -> tuple[bool, str]:
    try:
        _run_command(
            ["ffmpeg", "-v", "error", "-i", path, "-map", "0", "-f", "null", "-"],
            timeout=120,
        )
    except MCPVideoError as exc:
        return False, exc.code or type(exc).__name__
    except OSError as exc:
        return False, type(exc).__name__
    return True, ""


def _packets(path: str) -> list[dict[str, Any]]:
    try:
        result = _run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_packets",
                "-show_entries",
                "packet=stream_index,pts_time,dts_time,duration_time",
                "-of",
                "json",
                path,
            ],
            timeout=60,
        )
        return json.loads(result.stdout).get("packets", [])[:5000]
    except (MCPVideoError, OSError, json.JSONDecodeError):
        return []


def _monotonic(packets: list[dict[str, Any]]) -> bool:
    last: dict[int, float] = {}
    for packet in packets:
        value = packet.get("dts_time", packet.get("pts_time"))
        try:
            timestamp = float(0 if value is None else value)
            index = int(packet.get("stream_index", -1))
        except (TypeError, ValueError):
            continue
        if timestamp + 1e-6 < last.get(index, timestamp):
            return False
        last[index] = timestamp
    return bool(last)


def _stream_counts(raw: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stream in raw.get("streams", []):
        kind = str(stream.get("codec_type", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _av_end_delta(raw: dict[str, Any], packets: list[dict[str, Any]]) -> float | None:
    kinds = {int(s.get("index", -1)): s.get("codec_type") for s in raw.get("streams", [])}
    ends: dict[str, float] = {}
    for packet in packets:
        kind = kinds.get(int(packet.get("stream_index", -1)))
        if kind not in {"audio", "video"}:
            continue
        try:
            timestamp = packet.get("pts_time", packet.get("dts_time"))
            duration = packet.get("duration_time", 0)
            end = float(0 if timestamp is None else timestamp) + float(0 if duration is None else duration)
        except (TypeError, ValueError):
            continue
        ends[kind] = max(ends.get(kind, end), end)
    return abs(ends["video"] - ends["audio"]) if {"video", "audio"} <= ends.keys() else None


def _caption_segments(path: str | None) -> list[tuple[float, float, str]]:
    if not path or not Path(path).is_file():
        return []
    def seconds(value: str) -> float:
        hours, minutes, rest = value.replace(",", ".").split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)
    segments = []
    for block in re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8").strip()):
        lines = block.splitlines()
        timing_index = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if timing_index is None:
            continue
        start, end = lines[timing_index].split(" --> ", 1)
        segments.append((seconds(start), seconds(end), " ".join(lines[timing_index + 1:]).strip()))
    return segments


def verify_package(source: str, master: str, sharing_copy: str, caption_path: str | None = None,
                   transcript_path: str | None = None) -> list[VerificationCheck]:
    """Run independent media, timeline, package, and integrity checks."""
    source_before = _sha(source)
    source_raw, master_raw, share_raw = map(_run_ffprobe_json, (source, master, sharing_copy))
    master_decode, master_error = _decode(master)
    share_decode, share_error = _decode(sharing_copy)
    source_after = _sha(source)
    tolerance = max(0.10, 2 / max(_fps(source_raw), 1))
    delta = abs(_duration(master_raw) - _duration(source_raw))
    master_packets, share_packets = _packets(master), _packets(sharing_copy)
    monotonic = _monotonic(master_packets) and _monotonic(share_packets)
    source_counts, master_counts = _stream_counts(source_raw), _stream_counts(master_raw)
    coverage = all(master_counts.get(kind, 0) >= count for kind, count in source_counts.items() if kind != "subtitle")
    sync_delta = _av_end_delta(master_raw, master_packets)
    sync_ok = sync_delta is None or sync_delta <= tolerance
    segments = _caption_segments(caption_path)
    caption_ok = not caption_path or all(0 <= start < end <= _duration(master_raw) + tolerance for start, end, _ in segments)
    transcript = Path(transcript_path).read_text(encoding="utf-8") if transcript_path and Path(transcript_path).is_file() else None
    caption_text = " ".join(text for _, _, text in segments)
    spoken_ok = transcript is None or " ".join(transcript.split()) == " ".join(caption_text.split())
    video = next((s for s in share_raw.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in share_raw.get("streams", []) if s.get("codec_type") == "audio"), None)
    formats = str(share_raw.get("format", {}).get("format_name", "")).split(",")
    universal_ok = "mp4" in formats and video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p" and (audio is None or audio.get("codec_name") == "aac")
    checks = [
        VerificationCheck(id="source_unchanged", passed=source_before == source_after, message="Source hash remained unchanged.", metric=_metric("source_hash_match", source_before == source_after, "boolean", "Whether source SHA-256 matched before and after verification.")),
        VerificationCheck(id="master_full_decode", passed=master_decode, message="Master full decode completed." if master_decode else "Master full decode failed.", details={"error": master_error}),
        VerificationCheck(id="sharing_full_decode", passed=share_decode, message="Sharing full decode completed." if share_decode else "Sharing full decode failed.", details={"error": share_error}),
        VerificationCheck(id="timeline_duration", passed=delta <= tolerance, message="Master duration compared with source.", metric=_metric("duration_delta", delta, "seconds", "Absolute master-to-source container duration difference."), details={"tolerance_seconds": tolerance}),
        VerificationCheck(id="monotonic_timestamps", passed=monotonic, message="Bounded packet timestamps are monotonic."),
        VerificationCheck(id="source_stream_coverage", passed=coverage, message="Master covers source stream types and counts.", details={"source": source_counts, "master": master_counts}),
        VerificationCheck(id="audio_video_sync", passed=sync_ok, message="Audio/video packet ends are within tolerance.", metric=_metric("av_end_delta", sync_delta, "seconds", "Absolute difference between final audio and video packet end times.", sync_delta is not None)),
        VerificationCheck(id="caption_sync", passed=caption_ok, message="Caption segments are within master duration.", details={"status": "not_applicable" if not caption_path else "checked"}),
        VerificationCheck(id="spoken_content_coverage", passed=spoken_ok, message="Transcript and caption text coverage compared.", details={"status": "not_applicable" if transcript is None else "checked"}),
        VerificationCheck(id="universal_mp4_contract", passed=universal_ok, message="Sharing copy checked against universal MP4 contract.", metric=_metric("universal_contract_match", universal_ok, "boolean", "Whether container, codecs, and pixel format meet the sharing contract."), details={"required": {"container": "mp4", "video_codec": "h264", "pixel_format": "yuv420p", "audio_codec": "aac_or_absent"}}),
    ]
    units_ok = all(check.metric is None or bool(check.metric.unit and check.metric.definition) for check in checks)
    checks.append(VerificationCheck(id="metric_units", passed=units_ok, message="All numeric metrics have explicit units and definitions."))
    hashes = {"source": source_after, "master": _sha(master), "sharing_copy": _sha(sharing_copy)}
    checks.append(VerificationCheck(id="persisted_hashes", passed=True, message="Persisted artifacts were hashed after verification.", details=hashes))
    return checks
