"""Deterministic subtitle temporal and safe-area QA (Plan 02 Task 8 / PR 5.1).

Reports cue overlap, meaningful gaps, reading-speed (chars/sec) violations,
missing lines, and EOF overflow as typed :class:`DefectFinding` records, and
flags subtitle/overlay safe-area collisions at the platform's full display
resolution across vertical, horizontal, and square profiles.

Reuses the canonical EOF clamp (:func:`clamp_segments_to_eof`), the rescue
verifier's subtitle parser (``_caption_segments``), and the FFprobe helpers
(``_get_video_duration``, ``_run_ffprobe_json``) — no duplicate utilities.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from kinocut.aivideo.subtitle_qa_validation import (
    normalized_overlay as _normalized_overlay,
    qa_error as _qa_error,
    validate_created_by as _validate_created_by,
    validate_project_id as _validate_project_id,
    validate_safe_area_profile as _validate_safe_area_profile,
    validate_target_id as _validate_target_id,
    validate_threshold as _validate_threshold,
)
from kinocut.contracts.defect import DefectCode, DefectFinding, Severity
from kinocut.defaults import (
    DEFAULT_SUBTITLE_QA_CHAR_WIDTH_FACTOR as _CHAR_WIDTH_FACTOR,
    DEFAULT_SUBTITLE_QA_DETECTOR_CONFIDENCE as _DETECTOR_CONFIDENCE,
    DEFAULT_SUBTITLE_QA_GAP_SECONDS_THRESHOLD as DEFAULT_GAP_SECONDS_THRESHOLD,
    DEFAULT_SUBTITLE_QA_LINE_HEIGHT_FACTOR as _LINE_HEIGHT_FACTOR,
    DEFAULT_SUBTITLE_QA_READING_SPEED_CPS as DEFAULT_READING_SPEED_CPS,
)
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import (
    _get_video_duration,
    _run_ffprobe_json,
    _validate_input_path,
)
from kinocut.subtitles_eof import ClampWarning, clamp_segments_to_eof
from kinocut.validation import SUBTITLE_SAFE_AREA_PROFILES

# --------------------------------------------------------------------------- #
# Module-local identifiers (not tunable defaults — see AGENTS.md Rule 12)
# --------------------------------------------------------------------------- #
#
# The five numeric defaults above (reading-speed ceiling, gap threshold,
# glyph/line-height heuristic factors, and detector confidence) live in
# ``defaults.py`` per AGENTS.md Rule 12 and are re-bound here under stable
# names so public signatures stay backward-compatible. The identifiers below
# are NOT defaults: they are this module's unique namespace name, its stable
# validation error code, the measurement-protocol encoding for
# ``ClampWarning``, and the deterministic-detector agent identity.  None is a
# magic number or a tunable value, so they stay at point of use.

_DETECTOR_PREFIX = "deterministic:subtitle_qa"

_AGENT_IDENTITY = "agent:subtitle_qa"

#: Numeric encoding for clamp warnings (Measurement.value must be float).
_CLAMP_CODE: dict[ClampWarning, float] = {
    ClampWarning.CLAMPED: 0.0,
    ClampWarning.DROPPED: 1.0,
}


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SubtitleCue:
    """One parsed subtitle cue with 0-based index, timing, and text."""

    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SafeAreaProfile:
    """Deterministic platform safe-area profile at full display resolution.

    Each profile pins the exact display dimensions, title-safe margin percentage,
    subtitle font size, anchor position, and line/character constraints so the
    safe-area collision check is deterministic and reproducible.
    """

    platform: str
    display_width: int
    display_height: int
    title_safe_margin_pct: float
    subtitle_font_size_px: int
    subtitle_anchor_x_pct: float
    subtitle_anchor_y_pct: float
    max_chars_per_line: int
    max_lines: int


@dataclass(frozen=True)
class SubtitleQaReport:
    """Immutable result of a full subtitle QA pass."""

    findings: tuple[DefectFinding, ...]
    cue_count: int
    eof_seconds: float
    profile_name: str | None


# --------------------------------------------------------------------------- #
# Platform profiles — built deterministically from shared immutable data
# --------------------------------------------------------------------------- #
#
# The immutable source-of-truth profile data (dimensions, margins, font size,
# anchor, line constraints) lives in ``kinocut.validation`` per AGENTS.md
# Rule 13.  This dict is built from that data so there is exactly one source
# of truth and no opportunity for the two surfaces to diverge.

PLATFORM_PROFILES: dict[str, SafeAreaProfile] = {
    data.platform: SafeAreaProfile(
        platform=data.platform,
        display_width=data.display_width,
        display_height=data.display_height,
        title_safe_margin_pct=data.title_safe_margin_pct,
        subtitle_font_size_px=data.subtitle_font_size_px,
        subtitle_anchor_x_pct=data.subtitle_anchor_x_pct,
        subtitle_anchor_y_pct=data.subtitle_anchor_y_pct,
        max_chars_per_line=data.max_chars_per_line,
        max_lines=data.max_lines,
    )
    for data in SUBTITLE_SAFE_AREA_PROFILES
}


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _compute_target_id(cues: Sequence[SubtitleCue]) -> str:
    """Deterministic sha256 asset id from cue content (never echoes raw text)."""
    payload = json.dumps(
        [[c.start, c.end, c.text, c.index] for c in cues],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _make_finding(
    *,
    defect_code: DefectCode,
    target_id: str,
    project_id: str,
    created_by: str,
    time_range: tuple[float, float],
    severity: Severity,
    detector: str,
    measurements: tuple[dict[str, object], ...],
    confidence: float = _DETECTOR_CONFIDENCE,
) -> DefectFinding:
    """Construct one typed DefectFinding from the common field set."""
    return DefectFinding(
        project_id=project_id,
        created_by=created_by,
        defect_code=defect_code,
        target_id=target_id,
        time_range=time_range,
        severity=severity,
        confidence=confidence,
        detector=detector,
        measurements=tuple(  # type: ignore[arg-type]
            {"name": m["name"], "value": m["value"], "unit": m["unit"]} for m in measurements
        ),
    )


def _validate_cues(cues: object) -> tuple[SubtitleCue, ...]:
    """Validate the cue container and each cue's timing; fail closed."""
    if not isinstance(cues, (list, tuple)):
        raise _qa_error("cues must be a list or tuple of SubtitleCue records")
    validated: list[SubtitleCue] = []
    for item in cues:
        if not isinstance(item, SubtitleCue):
            raise _qa_error("each cue must be a SubtitleCue instance")
        times = (item.start, item.end)
        if (
            any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in times
            )
            or item.start < 0.0
            or item.end <= item.start
        ):
            raise _qa_error("each cue time_range must be positive and non-negative")
        if not isinstance(item.text, str):
            raise _qa_error("cue text must be a string")
        validated.append(item)
    return tuple(validated)


def _resolve_target_id(cues: Sequence[SubtitleCue], target_id: str | None) -> str:
    """Use the caller-provided target_id or compute one deterministically."""
    if target_id is not None:
        _validate_target_id(target_id)
        return target_id
    return _compute_target_id(cues)


# --------------------------------------------------------------------------- #
# Cue parsing (reuses rescue verifier _caption_segments)
# --------------------------------------------------------------------------- #


def parse_subtitle_cues(path: str) -> tuple[SubtitleCue, ...]:
    """Parse an SRT or VTT file into indexed :class:`SubtitleCue` records.

    Delegates to the rescue verifier's canonical ``_caption_segments`` parser
    (handles both SRT and VTT timing) and wraps each tuple into a typed cue.
    """
    from kinocut.rescue.verifier import _caption_segments

    path = _validate_input_path(path)
    suffix = _suffix_lower(path)
    if suffix not in (".srt", ".vtt"):
        raise MCPVideoError(
            "unsupported subtitle format; expected a .srt or .vtt file",
            error_type="validation_error",
            code="unsupported_subtitle_format",
        )
    raw = _caption_segments(path)
    cues = tuple(SubtitleCue(index=i, start=start, end=end, text=text) for i, (start, end, text) in enumerate(raw))
    return cues


def _suffix_lower(path: str) -> str:
    """Return the lowercase file extension including the dot."""
    import os

    return os.path.splitext(path)[1].lower()


# --------------------------------------------------------------------------- #
# Temporal QA
# --------------------------------------------------------------------------- #


def qa_subtitle_temporal(
    cues: Sequence[SubtitleCue],
    *,
    eof_seconds: float,
    project_id: str,
    target_id: str | None = None,
    created_by: str = _AGENT_IDENTITY,
    reading_speed_cps_threshold: float = DEFAULT_READING_SPEED_CPS,
    gap_seconds_threshold: float = DEFAULT_GAP_SECONDS_THRESHOLD,
) -> tuple[DefectFinding, ...]:
    """Run deterministic temporal QA: overlap, gap, reading-speed, missing, EOF.

    Returns a tuple of typed :class:`DefectFinding` records covering cue
    overlap, meaningful gaps, reading-speed violations, missing/empty text, and
    EOF overflow (using the canonical :func:`clamp_segments_to_eof` logic).
    """
    valid = _validate_cues(cues)
    eof = _validate_eof(eof_seconds)
    _validate_threshold(reading_speed_cps_threshold, "reading_speed_cps_threshold")
    _validate_threshold(gap_seconds_threshold, "gap_seconds_threshold", allow_zero=True)
    _validate_created_by(created_by)
    _validate_project_id(project_id)
    tid = _resolve_target_id(valid, target_id)

    findings: list[DefectFinding] = []
    findings.extend(_eof_findings(valid, eof, project_id, tid, created_by))
    findings.extend(_overlap_findings(valid, project_id, tid, created_by))
    findings.extend(_gap_findings(valid, gap_seconds_threshold, project_id, tid, created_by))
    findings.extend(_reading_speed_findings(valid, reading_speed_cps_threshold, project_id, tid, created_by))
    findings.extend(_missing_text_findings(valid, project_id, tid, created_by))
    return tuple(findings)


def _validate_eof(eof_seconds: object) -> float:
    """Validate the eof_seconds parameter."""
    if isinstance(eof_seconds, bool) or not isinstance(eof_seconds, (int, float)):
        raise _qa_error("eof_seconds must be a real number")
    val = float(eof_seconds)
    if not math.isfinite(val) or val <= 0.0:
        raise _qa_error("eof_seconds must be a positive, finite number")
    return val


def _eof_time_range(cue: SubtitleCue, eof: float) -> tuple[float, float]:
    """Return a valid (start < end) time range for an EOF-overflow finding.

    A dropped cue (start >= eof) cannot use a clamped range; the original cue
    range carries the positional evidence. A clamped cue uses its clamped range.
    """
    if cue.start >= eof:
        return (cue.start, cue.end)
    return (cue.start, min(cue.end, eof))


def _eof_findings(
    cues: Sequence[SubtitleCue],
    eof: float,
    project_id: str,
    target_id: str,
    created_by: str,
) -> list[DefectFinding]:
    """Detect EOF overflow using the canonical :func:`clamp_segments_to_eof`.

    Each cue is clamped individually via the canonical clamp (which requires
    non-overlapping segments) so overlapping cues are still checked correctly.
    """
    results: list[DefectFinding] = []
    for cue in cues:
        warning = _cue_eof_warning(cue, eof)
        if warning is None:
            continue
        overflow_seconds = max(0.0, cue.end - eof)
        severity = Severity.CRITICAL if warning is ClampWarning.DROPPED else Severity.HIGH
        results.append(
            _make_finding(
                defect_code=DefectCode.SUBTITLE_OVERFLOW,
                target_id=target_id,
                project_id=project_id,
                created_by=created_by,
                time_range=_eof_time_range(cue, eof),
                severity=severity,
                detector=f"{_DETECTOR_PREFIX}:eof_overflow",
                measurements=(
                    {"name": "clamp_warning", "value": _CLAMP_CODE[warning], "unit": f"code:{warning.value}"},
                    {"name": "eof_overflow_seconds", "value": overflow_seconds, "unit": "s"},
                    {"name": "cue_index", "value": cue.index, "unit": "index"},
                ),
            )
        )
    return results


def _cue_eof_warning(cue: SubtitleCue, eof: float) -> ClampWarning | None:
    """Use the canonical clamp on one cue; return its warning or None."""
    try:
        result = clamp_segments_to_eof([(cue.start, cue.end)], eof)
    except MCPVideoError:
        return None
    if not result.warnings:
        return None
    return result.warnings[0]


def _overlap_findings(
    cues: Sequence[SubtitleCue],
    project_id: str,
    target_id: str,
    created_by: str,
) -> list[DefectFinding]:
    """Detect consecutive cue time-range overlaps."""
    results: list[DefectFinding] = []
    for prev, curr in pairwise(cues):
        if curr.start < prev.end:
            overlap = prev.end - curr.start
            results.append(
                _make_finding(
                    defect_code=DefectCode.SUBTITLE_TIMING,
                    target_id=target_id,
                    project_id=project_id,
                    created_by=created_by,
                    time_range=(curr.start, prev.end),
                    severity=Severity.MEDIUM,
                    detector=f"{_DETECTOR_PREFIX}:overlap",
                    measurements=(
                        {"name": "overlap_seconds", "value": overlap, "unit": "s"},
                        {"name": "cue_index_a", "value": prev.index, "unit": "index"},
                        {"name": "cue_index_b", "value": curr.index, "unit": "index"},
                    ),
                )
            )
    return results


def _gap_findings(
    cues: Sequence[SubtitleCue],
    threshold: float,
    project_id: str,
    target_id: str,
    created_by: str,
) -> list[DefectFinding]:
    """Detect meaningful gaps between consecutive cues."""
    results: list[DefectFinding] = []
    for prev, curr in pairwise(cues):
        gap = curr.start - prev.end
        if gap > threshold:
            results.append(
                _make_finding(
                    defect_code=DefectCode.SUBTITLE_TIMING,
                    target_id=target_id,
                    project_id=project_id,
                    created_by=created_by,
                    time_range=(prev.end, curr.start),
                    severity=Severity.LOW,
                    detector=f"{_DETECTOR_PREFIX}:gap",
                    measurements=(
                        {"name": "gap_seconds", "value": gap, "unit": "s"},
                        {"name": "gap_threshold_seconds", "value": threshold, "unit": "s"},
                        {"name": "cue_index_a", "value": prev.index, "unit": "index"},
                        {"name": "cue_index_b", "value": curr.index, "unit": "index"},
                    ),
                )
            )
    return results


def _reading_speed_findings(
    cues: Sequence[SubtitleCue],
    threshold: float,
    project_id: str,
    target_id: str,
    created_by: str,
) -> list[DefectFinding]:
    """Detect reading-speed (chars/sec) violations above the threshold."""
    results: list[DefectFinding] = []
    for cue in cues:
        text = cue.text.strip()
        if not text:
            continue
        duration = cue.end - cue.start
        if duration <= 0.0:
            continue
        chars = len(text)
        cps = chars / duration
        if cps > threshold:
            results.append(
                _make_finding(
                    defect_code=DefectCode.SUBTITLE_TIMING,
                    target_id=target_id,
                    project_id=project_id,
                    created_by=created_by,
                    time_range=(cue.start, cue.end),
                    severity=Severity.MEDIUM,
                    detector=f"{_DETECTOR_PREFIX}:reading_speed",
                    measurements=(
                        {"name": "reading_speed_cps", "value": cps, "unit": "chars/s"},
                        {"name": "threshold_cps", "value": threshold, "unit": "chars/s"},
                        {"name": "text_length_chars", "value": chars, "unit": "chars"},
                        {"name": "duration_seconds", "value": duration, "unit": "s"},
                        {"name": "cue_index", "value": cue.index, "unit": "index"},
                    ),
                )
            )
    return results


def _missing_text_findings(
    cues: Sequence[SubtitleCue],
    project_id: str,
    target_id: str,
    created_by: str,
) -> list[DefectFinding]:
    """Detect cues whose text body is empty or whitespace-only."""
    results: list[DefectFinding] = []
    for cue in cues:
        if cue.text.strip():
            continue
        results.append(
            _make_finding(
                defect_code=DefectCode.SUBTITLE_TIMING,
                target_id=target_id,
                project_id=project_id,
                created_by=created_by,
                time_range=(cue.start, cue.end),
                severity=Severity.MEDIUM,
                detector=f"{_DETECTOR_PREFIX}:missing_text",
                measurements=(
                    {"name": "text_length_chars", "value": 0, "unit": "chars"},
                    {"name": "cue_index", "value": cue.index, "unit": "index"},
                ),
            )
        )
    return results


# --------------------------------------------------------------------------- #
# Safe-area QA
# --------------------------------------------------------------------------- #


def qa_subtitle_safe_area(
    cues: Sequence[SubtitleCue],
    *,
    profile: SafeAreaProfile,
    project_id: str,
    target_id: str | None = None,
    created_by: str = _AGENT_IDENTITY,
    overlay_regions: Sequence[Mapping[str, float]] = (),
) -> tuple[DefectFinding, ...]:
    """Flag subtitle/overlay safe-area collisions at full display resolution.

    For each cue, estimates the text bounding box in pixels at the platform's
    full display resolution, checks whether it fits within the title-safe area,
    and checks whether it collides with any provided overlay region.
    """
    valid = _validate_cues(cues)
    _validate_project_id(project_id)
    if not isinstance(profile, SafeAreaProfile):
        raise _qa_error("profile must be a SafeAreaProfile instance")
    _validate_safe_area_profile(profile)
    _validate_created_by(created_by)
    tid = _resolve_target_id(valid, target_id)

    findings: list[DefectFinding] = []
    for cue in valid:
        box = _estimate_subtitle_box(cue.text, profile)
        finding = _safe_area_overflow_finding(cue, box, profile, project_id, tid, created_by)
        if finding is not None:
            findings.append(finding)
        findings.extend(_overlay_collision_findings(cue, box, profile, overlay_regions, project_id, tid, created_by))
    return tuple(findings)


@dataclass(frozen=True)
class _PixelBox:
    """Estimated subtitle bounding box in full-resolution pixels."""

    x: int
    y: int

    width: int
    height: int


def _estimate_subtitle_box(text: str, profile: SafeAreaProfile) -> _PixelBox:
    """Estimate the subtitle bounding box at full display resolution.

    Approximates glyph width as ``font_size * 0.6`` and line height as
    ``font_size * 1.2``, matching the shipped design-guardrails heuristic so the
    check is deterministic without rendering.
    """
    stripped = text.strip()
    chars = len(stripped)
    if chars == 0:
        chars = 1
    effective_lines = min(math.ceil(chars / profile.max_chars_per_line), profile.max_lines)
    chars_in_longest_line = min(chars, profile.max_chars_per_line)
    box_w = math.ceil(chars_in_longest_line * profile.subtitle_font_size_px * _CHAR_WIDTH_FACTOR)
    box_h = math.ceil(effective_lines * profile.subtitle_font_size_px * _LINE_HEIGHT_FACTOR)
    center_x = round(profile.subtitle_anchor_x_pct * profile.display_width)
    bottom_y = round(profile.subtitle_anchor_y_pct * profile.display_height)
    x = center_x - box_w // 2
    y = bottom_y - box_h
    return _PixelBox(x=x, y=y, width=box_w, height=box_h)


def _safe_area_overflow_finding(
    cue: SubtitleCue,
    box: _PixelBox,
    profile: SafeAreaProfile,
    project_id: str,
    target_id: str,
    created_by: str,
) -> DefectFinding | None:
    """Return a finding if the box exceeds any safe-area boundary, else None."""
    margin_x = round(profile.title_safe_margin_pct * profile.display_width)
    margin_y = round(profile.title_safe_margin_pct * profile.display_height)
    safe_left = margin_x
    safe_top = margin_y
    safe_right = profile.display_width - margin_x
    safe_bottom = profile.display_height - margin_y

    overflow_left = max(0, safe_left - box.x)
    overflow_right = max(0, (box.x + box.width) - safe_right)
    overflow_top = max(0, safe_top - box.y)
    overflow_bottom = max(0, (box.y + box.height) - safe_bottom)

    if not any((overflow_left, overflow_right, overflow_top, overflow_bottom)):
        return None

    return _make_finding(
        defect_code=DefectCode.SUBTITLE_OVERFLOW,
        target_id=target_id,
        project_id=project_id,
        created_by=created_by,
        time_range=(cue.start, cue.end),
        severity=Severity.MEDIUM,
        detector=f"{_DETECTOR_PREFIX}:safe_area",
        measurements=(
            {"name": "display_width_px", "value": profile.display_width, "unit": "px"},
            {"name": "display_height_px", "value": profile.display_height, "unit": "px"},
            {"name": "subtitle_box_x_px", "value": box.x, "unit": "px"},
            {"name": "subtitle_box_y_px", "value": box.y, "unit": "px"},
            {"name": "subtitle_box_width_px", "value": box.width, "unit": "px"},
            {"name": "subtitle_box_height_px", "value": box.height, "unit": "px"},
            {"name": "overflow_left_px", "value": overflow_left, "unit": "px"},
            {"name": "overflow_right_px", "value": overflow_right, "unit": "px"},
            {"name": "overflow_top_px", "value": overflow_top, "unit": "px"},
            {"name": "overflow_bottom_px", "value": overflow_bottom, "unit": "px"},
            {"name": "cue_index", "value": cue.index, "unit": "index"},
        ),
    )


def _overlay_collision_findings(
    cue: SubtitleCue,
    box: _PixelBox,
    profile: SafeAreaProfile,
    overlay_regions: Sequence[Mapping[str, float]],
    project_id: str,
    target_id: str,
    created_by: str,
) -> list[DefectFinding]:
    """Detect pixel-level collisions between the subtitle box and overlay regions."""
    results: list[DefectFinding] = []
    for index, region in enumerate(overlay_regions):
        if not isinstance(region, Mapping):
            raise _qa_error("each overlay region must be a mapping")
        normalized = _normalized_overlay(region)
        ox = round(normalized.x * profile.display_width)
        oy = round(normalized.y * profile.display_height)
        ow = round(normalized.width * profile.display_width)
        oh = round(normalized.height * profile.display_height)
        overlap_w = max(0, min(box.x + box.width, ox + ow) - max(box.x, ox))
        overlap_h = max(0, min(box.y + box.height, oy + oh) - max(box.y, oy))
        if overlap_w > 0 and overlap_h > 0:
            overlap_area = overlap_w * overlap_h
            results.append(
                _make_finding(
                    defect_code=DefectCode.SUBTITLE_OVERFLOW,
                    target_id=target_id,
                    project_id=project_id,
                    created_by=created_by,
                    time_range=(cue.start, cue.end),
                    severity=Severity.MEDIUM,
                    detector=f"{_DETECTOR_PREFIX}:overlay_collision",
                    measurements=(
                        {
                            "name": "display_width_px",
                            "value": profile.display_width,
                            "unit": "px",
                        },
                        {
                            "name": "display_height_px",
                            "value": profile.display_height,
                            "unit": "px",
                        },
                        {
                            "name": "overlap_width_px",
                            "value": overlap_w,
                            "unit": "px",
                        },
                        {
                            "name": "overlap_height_px",
                            "value": overlap_h,
                            "unit": "px",
                        },
                        {
                            "name": "overlap_area_px2",
                            "value": overlap_area,
                            "unit": "px^2",
                        },
                        {"name": "overlay_index", "value": index, "unit": "index"},
                        {"name": "cue_index", "value": cue.index, "unit": "index"},
                    ),
                )
            )
    return results


# --------------------------------------------------------------------------- #
# Main entry — media + subtitle combined QA
# --------------------------------------------------------------------------- #


def subtitle_qa(
    media_path: str,
    subtitle_path: str,
    *,
    project_id: str,
    profile: str | None = None,
    created_by: str = _AGENT_IDENTITY,
    reading_speed_cps_threshold: float = DEFAULT_READING_SPEED_CPS,
    gap_seconds_threshold: float = DEFAULT_GAP_SECONDS_THRESHOLD,
    overlay_regions: Sequence[Mapping[str, float]] = (),
) -> SubtitleQaReport:
    """Probe media, parse subtitles, and run temporal + safe-area QA.

    Args:
        media_path: Input video (probed for duration and display dimensions).
        subtitle_path: ``.srt`` or ``.vtt`` subtitle file.
        project_id: The project this QA runs under.
        profile: Platform profile name (``vertical``/``horizontal``/``square``).
            If omitted, the profile is derived deterministically from the
            probed display dimensions.
        overlay_regions: Optional normalized overlay regions for collision checks.
    """
    _validate_created_by(created_by)
    _validate_project_id(project_id)
    media_path = _validate_input_path(media_path)
    subtitle_path = _validate_input_path(subtitle_path)
    eof_seconds = _get_video_duration(media_path)
    cues = parse_subtitle_cues(subtitle_path)
    tid = _resolve_target_id(cues, None)
    profile_obj = _resolve_profile(profile, media_path)

    findings = list(
        qa_subtitle_temporal(
            cues,
            eof_seconds=eof_seconds,
            project_id=project_id,
            target_id=tid,
            created_by=created_by,
            reading_speed_cps_threshold=reading_speed_cps_threshold,
            gap_seconds_threshold=gap_seconds_threshold,
        )
    )
    findings.extend(
        qa_subtitle_safe_area(
            cues,
            profile=profile_obj,
            project_id=project_id,
            target_id=tid,
            created_by=created_by,
            overlay_regions=overlay_regions,
        )
    )
    return SubtitleQaReport(
        findings=tuple(findings),
        cue_count=len(cues),
        eof_seconds=eof_seconds,
        profile_name=profile_obj.platform,
    )


def _resolve_profile(profile: str | None, media_path: str) -> SafeAreaProfile:
    """Return the named profile or infer one from the media's display size."""
    if profile is not None:
        if profile not in PLATFORM_PROFILES:
            raise _qa_error("profile must be one of: vertical, horizontal, square")
        return PLATFORM_PROFILES[profile]
    raw = _run_ffprobe_json(media_path)
    video = next(
        (s for s in raw.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    if width == 0 or height == 0:
        raise _qa_error("could not determine display dimensions for profile inference")
    if width < height:
        return PLATFORM_PROFILES["vertical"]
    if width > height:
        return PLATFORM_PROFILES["horizontal"]
    return PLATFORM_PROFILES["square"]
