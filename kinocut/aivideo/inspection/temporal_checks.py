"""Deterministic temporal-defect checks over decoded frame truth."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import statistics
from collections.abc import Iterable
from itertools import pairwise

from pydantic import Field, field_validator, model_validator

from kinocut.contracts._common import AssetId, Sha256, ValueObject
from kinocut.contracts.defect import DefectCode, DefectFinding, Measurement, Severity
from kinocut.defaults import (
    DEFAULT_FPS,
    DEFAULT_TEMPORAL_ANALYSIS_HEIGHT,
    DEFAULT_TEMPORAL_ANALYSIS_WIDTH,
    DEFAULT_TEMPORAL_BLACK_LUMA_MAX,
    DEFAULT_TEMPORAL_BROKEN_LOOP_DIFFERENCE_MIN,
    DEFAULT_TEMPORAL_FROZEN_DIFFERENCE_MAX,
    DEFAULT_TEMPORAL_LATE_FRAME_GAP_MULTIPLIER,
    DEFAULT_TEMPORAL_TEXT_DRIFT_DIFFERENCE_MIN,
)
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_command, _run_ffmpeg_bytes, _validate_input_path
from kinocut.limits import (
    FFPROBE_TIMEOUT,
    MAX_TEMPORAL_INSPECTION_FRAMES,
    MAX_VIDEO_DURATION,
)

_REASON_CODES = frozenset({"decode_error", "missing_frame", "invalid_timestamp"})
_REGION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHOWINFO_TIME_RE = re.compile(r"\[Parsed_showinfo_[^]]+].*\bpts_time:(?P<start>-?[0-9.]+)")
_SHOWINFO_DURATION_RE = re.compile(r"duration_time:(?P<duration>[0-9.]+)")
_DECODER_COMPONENT_RE = re.compile(r"^\[[^]@]+ @ 0x[0-9a-fA-F]+]\s*(?P<message>.*)$")
_CORRUPT_DECODED_FRAME_RE = re.compile(r":\s*(?P<message>corrupt decoded frame in stream \d+)\s*$", re.I)
_STREAM_DECODE_ERROR_RE = re.compile(r"^(?P<message>error while decoding stream #\d+:\d+.*)$", re.I)
_CORRUPTION_MARKERS = (
    "corrupt decoded frame",
    "error while decoding",
    "ac-tex damaged",
    "header damaged",
    "slice damaged",
    "concealing ",
    "invalid frame",
)
logger = logging.getLogger(__name__)


def _invalid_observations(message: str) -> MCPVideoError:
    return MCPVideoError(
        message,
        error_type="validation_error",
        code="invalid_temporal_observations",
    )


class TemporalFrameObservation(ValueObject):
    """Metrics for one actually decoded frame at its real media timestamp."""

    timestamp: float = Field(ge=0.0)
    mean_luma: float = Field(ge=0.0, le=255.0)
    difference_from_previous: float = Field(ge=0.0, le=255.0)
    signature: Sha256


class CorruptInterval(ValueObject):
    """A bounded decoder failure carrying only a closed privacy-safe reason."""

    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    reason_code: str

    @field_validator("reason_code")
    @classmethod
    def _reason_is_closed(cls, value: str) -> str:
        if value not in _REASON_CODES:
            raise ValueError("reason_code must be an approved decoder reason")
        return value

    @model_validator(mode="after")
    def _range_is_ordered(self) -> CorruptInterval:
        if self.end <= self.start:
            raise ValueError("corrupt interval end must follow start")
        return self


class RegionDifferenceObservation(ValueObject):
    """Difference metric for one declared text region at a decoded timestamp."""

    timestamp: float = Field(ge=0.0)
    region_name: str
    difference: float = Field(ge=0.0, le=255.0)

    @field_validator("region_name")
    @classmethod
    def _region_name_is_bounded(cls, value: str) -> str:
        if _REGION_NAME_RE.fullmatch(value) is None:
            raise ValueError("region_name must be a bounded lowercase code")
        return value


class TemporalInspectionResult(ValueObject):
    """Stable temporal metrics and suspected findings, ordered deterministically."""

    decoded_timestamps: tuple[float, ...]
    playable_end: float = Field(gt=0.0, le=MAX_VIDEO_DURATION)
    opening_closing_difference: float = Field(ge=0.0)
    findings: tuple[DefectFinding, ...]


def _measurement(name: str, value: float, unit: str) -> Measurement:
    return Measurement(name=name, value=round(value, 6), unit=unit)


def _finding(
    *,
    code: DefectCode,
    time_range: tuple[float, float],
    target_id: AssetId,
    project_id: str,
    detector: str,
    measurements: tuple[Measurement, ...],
    severity: Severity = Severity.MEDIUM,
) -> DefectFinding:
    return DefectFinding(
        project_id=project_id,
        created_by="tool:temporal_checks",
        defect_code=code,
        target_id=target_id,
        time_range=time_range,
        severity=severity,
        confidence=1.0,
        detector=detector,
        measurements=measurements,
    )


def _coalesce(ranges: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    ordered = sorted(ranges)
    if not ordered:
        return ()
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _frame_ranges(frames: tuple[TemporalFrameObservation, ...], expected_end: float) -> tuple[tuple[float, float], ...]:
    ends = (*tuple(frame.timestamp for frame in frames[1:]), expected_end)
    return tuple((frame.timestamp, end) for frame, end in zip(frames, ends, strict=True))


def _black_findings(
    frames: tuple[TemporalFrameObservation, ...],
    expected_end: float,
    target_id: AssetId,
    project_id: str,
) -> list[DefectFinding]:
    spans = _frame_ranges(frames, expected_end)
    ranges = _coalesce(
        span for frame, span in zip(frames, spans, strict=True) if frame.mean_luma <= DEFAULT_TEMPORAL_BLACK_LUMA_MAX
    )
    return [
        _finding(
            code=DefectCode.BLACK_FRAMES,
            time_range=span,
            target_id=target_id,
            project_id=project_id,
            detector="temporal.black_interval.v1",
            measurements=(_measurement("maximum_mean_luma", DEFAULT_TEMPORAL_BLACK_LUMA_MAX, "luma"),),
        )
        for span in ranges
    ]


def _frozen_findings(
    frames: tuple[TemporalFrameObservation, ...],
    expected_end: float,
    target_id: AssetId,
    project_id: str,
) -> list[DefectFinding]:
    ranges: list[tuple[float, float]] = []
    for index, (previous, current) in enumerate(pairwise(frames), start=1):
        if current.difference_from_previous <= DEFAULT_TEMPORAL_FROZEN_DIFFERENCE_MAX:
            end = frames[index + 1].timestamp if index + 1 < len(frames) else expected_end
            span = (previous.timestamp, end)
            ranges.append(span)
    merged = _coalesce(ranges)
    findings: list[DefectFinding] = []
    for start, end in merged:
        relevant = [
            current
            for previous, current in pairwise(frames)
            if previous.timestamp >= start
            and current.timestamp <= end
            and current.difference_from_previous <= DEFAULT_TEMPORAL_FROZEN_DIFFERENCE_MAX
        ]
        exact = sum(
            int(previous.signature == current.signature)
            for previous, current in pairwise(frames)
            if previous.timestamp >= start
            and current.timestamp <= end
            and current.difference_from_previous <= DEFAULT_TEMPORAL_FROZEN_DIFFERENCE_MAX
        )
        findings.append(
            _finding(
                code=DefectCode.FROZEN_FRAMES,
                time_range=(start, end),
                target_id=target_id,
                project_id=project_id,
                detector="temporal.frozen_duplicate_interval.v1",
                measurements=(
                    _measurement("maximum_frame_difference", max(f.difference_from_previous for f in relevant), "luma"),
                    _measurement("exact_duplicate_transitions", float(exact), "count"),
                ),
            )
        )
    return findings


def _corrupt_findings(
    intervals: tuple[CorruptInterval, ...], target_id: AssetId, project_id: str
) -> list[DefectFinding]:
    return [
        _finding(
            code=DefectCode.CORRUPT_FRAMES,
            time_range=span,
            target_id=target_id,
            project_id=project_id,
            detector="temporal.decode_integrity.v1",
            measurements=(_measurement("corrupt_interval_duration", span[1] - span[0], "seconds"),),
            severity=Severity.HIGH,
        )
        for span in _coalesce((item.start, item.end) for item in intervals)
    ]


def _late_decode_finding(
    frames: tuple[TemporalFrameObservation, ...], expected_end: float, target_id: AssetId, project_id: str
) -> DefectFinding | None:
    if len(frames) < 2:
        return None
    deltas = [current.timestamp - previous.timestamp for previous, current in pairwise(frames)]
    tolerance = statistics.median(deltas) * DEFAULT_TEMPORAL_LATE_FRAME_GAP_MULTIPLIER
    gap = expected_end - frames[-1].timestamp
    if gap <= tolerance:
        return None
    return _finding(
        code=DefectCode.LATE_FRAME_DEGRADATION,
        time_range=(frames[-1].timestamp, expected_end),
        target_id=target_id,
        project_id=project_id,
        detector="temporal.late_decode.v1",
        measurements=(_measurement("undecoded_tail", gap, "seconds"),),
        severity=Severity.HIGH,
    )


def _text_drift_findings(
    observations: tuple[RegionDifferenceObservation, ...],
    expected_end: float,
    target_id: AssetId,
    project_id: str,
) -> list[DefectFinding]:
    findings: list[DefectFinding] = []
    for region in sorted({item.region_name for item in observations}):
        values = sorted((item for item in observations if item.region_name == region), key=lambda item: item.timestamp)
        flagged = [item for item in values if item.difference >= DEFAULT_TEMPORAL_TEXT_DRIFT_DIFFERENCE_MIN]
        if not flagged:
            continue
        findings.append(
            _finding(
                code=DefectCode.TEXT_DRIFT,
                time_range=(flagged[0].timestamp, expected_end),
                target_id=target_id,
                project_id=project_id,
                detector="temporal.text_region_difference.v1",
                measurements=(
                    _measurement("maximum_region_difference", max(item.difference for item in flagged), "luma"),
                ),
            )
        )
    return findings


def _validated_frames(
    frames: tuple[TemporalFrameObservation, ...], expected_end: float
) -> tuple[TemporalFrameObservation, ...]:
    ordered = tuple(sorted(frames, key=lambda frame: frame.timestamp))
    timestamps = tuple(frame.timestamp for frame in ordered)
    if not ordered or len(set(timestamps)) != len(timestamps) or expected_end <= timestamps[-1]:
        raise _invalid_observations("inspection requires unique decoded frame observations before the media end")
    return ordered


def _validate_evidence_ranges(
    corrupt_intervals: tuple[CorruptInterval, ...],
    region_differences: tuple[RegionDifferenceObservation, ...],
    expected_end: float,
) -> None:
    if any(item.end > expected_end for item in corrupt_intervals):
        raise _invalid_observations("corrupt evidence must stay within the media duration")
    region_keys = [(item.region_name, item.timestamp) for item in region_differences]
    if any(item.timestamp >= expected_end for item in region_differences) or len(set(region_keys)) != len(region_keys):
        raise _invalid_observations("region evidence must be unique and precede the media end")


def analyze_temporal_observations(
    frames: tuple[TemporalFrameObservation, ...],
    *,
    target_id: AssetId,
    project_id: str,
    expected_end: float,
    corrupt_intervals: tuple[CorruptInterval, ...] = (),
    region_differences: tuple[RegionDifferenceObservation, ...] = (),
    opening_closing_difference: float | None = None,
) -> TemporalInspectionResult:
    """Return deterministic suspected findings from bounded decoded observations."""

    if not math.isfinite(expected_end) or expected_end <= 0.0:
        raise _invalid_observations("inspection requires a finite positive media end")
    ordered = _validated_frames(frames, expected_end)
    _validate_evidence_ranges(corrupt_intervals, region_differences, expected_end)
    opening_closing = (
        abs(ordered[-1].mean_luma - ordered[0].mean_luma)
        if opening_closing_difference is None
        else opening_closing_difference
    )
    if not math.isfinite(opening_closing) or opening_closing < 0.0:
        raise _invalid_observations("inspection requires a finite opening and closing difference")
    found = _black_findings(ordered, expected_end, target_id, project_id)
    found.extend(_frozen_findings(ordered, expected_end, target_id, project_id))
    found.extend(_corrupt_findings(corrupt_intervals, target_id, project_id))
    late = _late_decode_finding(ordered, expected_end, target_id, project_id)
    if late is not None:
        found.append(late)
    found.extend(_text_drift_findings(region_differences, expected_end, target_id, project_id))
    if opening_closing >= DEFAULT_TEMPORAL_BROKEN_LOOP_DIFFERENCE_MIN:
        found.append(
            _finding(
                code=DefectCode.BROKEN_LOOP,
                time_range=(ordered[0].timestamp, expected_end),
                target_id=target_id,
                project_id=project_id,
                detector="temporal.loop_integrity.v1",
                measurements=(_measurement("opening_closing_difference", opening_closing, "luma"),),
            )
        )
    found.sort(key=lambda item: (item.time_range, item.defect_code.value, item.detector))
    return TemporalInspectionResult(
        decoded_timestamps=tuple(item.timestamp for item in ordered),
        playable_end=expected_end,
        opening_closing_difference=round(opening_closing, 6),
        findings=tuple(found),
    )


def _decoded_frame_metadata(path: str) -> tuple[tuple[float, float], ...]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-read_intervals",
        f"%+#{MAX_TEMPORAL_INSPECTION_FRAMES + 1}",
        "-show_frames",
        "-show_entries",
        "frame=best_effort_timestamp_time,duration_time",
        "-of",
        "json",
        path,
    ]
    payload = json.loads(_run_command(command, timeout=FFPROBE_TIMEOUT).stdout)
    frames = payload.get("frames", ())
    if not isinstance(frames, list) or not frames or len(frames) > MAX_TEMPORAL_INSPECTION_FRAMES:
        raise _invalid_observations("inspection frame count is invalid or exceeds its limit")
    metadata = []
    origin = float(frames[0]["best_effort_timestamp_time"])
    for frame in frames:
        timestamp = float(frame["best_effort_timestamp_time"]) - origin
        duration = float(frame.get("duration_time", 0.0))
        metadata.append((timestamp, duration))
    return tuple(metadata)


def _playable_video_end(metadata: tuple[tuple[float, float], ...]) -> float:
    timestamps = tuple(item[0] for item in metadata)
    positive_durations = tuple(item[1] for item in metadata if item[1] > 0.0)
    if positive_durations:
        last_duration = metadata[-1][1] or statistics.median(positive_durations)
    elif len(timestamps) > 1:
        last_duration = statistics.median(current - previous for previous, current in pairwise(timestamps))
    else:
        last_duration = 1.0 / DEFAULT_FPS
    return timestamps[-1] + last_duration


def _video_packet_end(path: str) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-read_intervals",
        f"%+#{MAX_TEMPORAL_INSPECTION_FRAMES + 1}",
        "-show_packets",
        "-show_entries",
        "packet=pts_time,dts_time,duration_time",
        "-of",
        "json",
        path,
    ]
    payload = json.loads(_run_command(command, timeout=FFPROBE_TIMEOUT).stdout)
    packets = payload.get("packets", ())
    if not isinstance(packets, list) or not packets or len(packets) > MAX_TEMPORAL_INSPECTION_FRAMES:
        raise _invalid_observations("inspection video packet timeline is invalid or exceeds its limit")
    starts = [float(packet.get("pts_time", packet["dts_time"])) for packet in packets]
    origin = min(starts)
    return max(
        start - origin + float(packet.get("duration_time", 0.0)) for start, packet in zip(starts, packets, strict=True)
    )


def _pixel_frames(path: str) -> tuple[bytes, ...]:
    frame_size = DEFAULT_TEMPORAL_ANALYSIS_WIDTH * DEFAULT_TEMPORAL_ANALYSIS_HEIGHT
    output = _run_ffmpeg_bytes(
        [
            "-i",
            path,
            "-vf",
            f"scale={DEFAULT_TEMPORAL_ANALYSIS_WIDTH}:{DEFAULT_TEMPORAL_ANALYSIS_HEIGHT}:flags=area,format=gray",
            "-frames:v",
            str(MAX_TEMPORAL_INSPECTION_FRAMES + 1),
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ]
    )
    if not output or len(output) % frame_size:
        raise _invalid_observations("inspection returned invalid decoded pixel output")
    frames = tuple(output[index : index + frame_size] for index in range(0, len(output), frame_size))
    if len(frames) > MAX_TEMPORAL_INSPECTION_FRAMES:
        raise _invalid_observations("temporal inspection frame limit exceeded")
    return frames


def _pixel_frame_difference(first: bytes, second: bytes) -> float:
    if not first or len(first) != len(second):
        raise _invalid_observations("pixel frames must have equal nonzero size")
    return sum(abs(left - right) for left, right in zip(first, second, strict=True)) / len(first)


def _probe_frames(
    path: str,
) -> tuple[tuple[TemporalFrameObservation, ...], float, float]:
    metadata = _decoded_frame_metadata(path)
    timestamps = tuple(item[0] for item in metadata)
    pixels = _pixel_frames(path)
    if len(timestamps) != len(pixels):
        raise _invalid_observations("decoded timestamps and pixels do not align")
    frames = tuple(
        TemporalFrameObservation(
            timestamp=timestamp,
            mean_luma=sum(pixel_frame) / len(pixel_frame),
            difference_from_previous=(0.0 if index == 0 else _pixel_frame_difference(pixels[index - 1], pixel_frame)),
            signature="sha256:" + hashlib.sha256(pixel_frame).hexdigest(),
        )
        for index, (timestamp, pixel_frame) in enumerate(zip(timestamps, pixels, strict=True))
    )
    return (
        frames,
        _pixel_frame_difference(pixels[0], pixels[-1]),
        _playable_video_end(metadata),
    )


def _decoder_diagnostic_message(line: str) -> str:
    for pattern in (_DECODER_COMPONENT_RE, _CORRUPT_DECODED_FRAME_RE, _STREAM_DECODE_ERROR_RE):
        match = pattern.search(line)
        if match is not None:
            return match.group("message").lower()
    return ""


def _integrity_scan(path: str, decoded_end: float, expected_end: float) -> tuple[CorruptInterval, ...]:
    command = [
        "ffmpeg",
        "-v",
        "info",
        "-i",
        path,
        "-map",
        "0:v:0",
        "-vf",
        "showinfo",
        "-frames:v",
        str(MAX_TEMPORAL_INSPECTION_FRAMES + 1),
        "-f",
        "null",
        "-",
    ]
    stderr = _run_command(command).stderr
    pending = False
    intervals: list[CorruptInterval] = []
    for line in stderr.splitlines():
        diagnostic = _decoder_diagnostic_message(line)
        pending = pending or any(diagnostic.startswith(marker) for marker in _CORRUPTION_MARKERS)
        match = _SHOWINFO_TIME_RE.search(line)
        if pending and match is not None:
            start = float(match.group("start"))
            duration_match = _SHOWINFO_DURATION_RE.search(line)
            duration = float(duration_match.group("duration")) if duration_match is not None else 1.0 / DEFAULT_FPS
            end = min(start + duration, expected_end)
            if start >= 0.0 and end > start:
                intervals.append(
                    CorruptInterval(
                        start=start,
                        end=end,
                        reason_code="decode_error",
                    )
                )
            pending = False
    if pending and expected_end > decoded_end:
        intervals.append(
            CorruptInterval(
                start=decoded_end,
                end=expected_end,
                reason_code="decode_error",
            )
        )
    return tuple(intervals)


def _expected_video_end(path: str, decoded_end: float, trusted_expected_video_end: float | None) -> float:
    packet_end = _video_packet_end(path)
    if trusted_expected_video_end is not None and (
        not math.isfinite(trusted_expected_video_end)
        or trusted_expected_video_end <= 0.0
        or trusted_expected_video_end > MAX_VIDEO_DURATION
        or trusted_expected_video_end < decoded_end
    ):
        raise _invalid_observations("trusted video end is outside the inspected media bounds")
    return max(decoded_end, packet_end, trusted_expected_video_end or 0.0)


def inspect_temporal_media(
    path: str,
    *,
    target_id: AssetId,
    project_id: str,
    region_differences: tuple[RegionDifferenceObservation, ...] = (),
    trusted_expected_video_end: float | None = None,
) -> TemporalInspectionResult:
    """Probe one local video and run deterministic checks on decoded frames."""

    try:
        validated = _validate_input_path(path)
        frames, opening_closing, decoded_end = _probe_frames(validated)
        expected_end = _expected_video_end(validated, decoded_end, trusted_expected_video_end)
        corrupt_intervals = _integrity_scan(validated, decoded_end, expected_end)
        return analyze_temporal_observations(
            frames,
            target_id=target_id,
            project_id=project_id,
            expected_end=expected_end,
            corrupt_intervals=corrupt_intervals,
            region_differences=region_differences,
            opening_closing_difference=opening_closing,
        )
    except Exception as exc:
        logger.warning("temporal media probe failed: %s", type(exc).__name__)
        if isinstance(exc, MCPVideoError) and exc.code == "invalid_temporal_observations":
            raise
        raise MCPVideoError(
            "inspection could not decode temporal observations",
            error_type="input_error",
            code="temporal_probe_failed",
        ) from exc
