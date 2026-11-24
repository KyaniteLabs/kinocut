"""Compact advisory QA of caption timings and profile-estimated layout, not rendered pixels."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_ffmpeg, _validate_input_path
from .subtitle_qa import SubtitleQaReport, subtitle_qa


class SubtitleAdvisoryStatus(StrEnum):
    """Typed status values for advisory subtitle QA summaries."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


def _convert_and_qa(media: str, source: str, input_format: str | None, profile: str | None) -> SubtitleQaReport:
    with TemporaryDirectory(prefix="kc_sub_qa_") as work:
        srt = str(Path(work) / "dialogue.srt")
        cmd = ["-f", input_format] if input_format else []
        cmd.extend(["-i", _validate_input_path(source), "-map", "0:s:0", srt])
        _run_ffmpeg(cmd)
        return subtitle_qa(media, srt, project_id="local-captions", profile=profile)


def _report(media: str, captions: str, profile: str | None, burn_ass: str | None = None) -> SubtitleQaReport:
    suffix = Path(captions).suffix.lower()
    if suffix == ".ass":
        return _convert_and_qa(media, burn_ass or captions, "ass", profile)
    if suffix == ".vtt" and burn_ass:
        return _convert_and_qa(media, burn_ass, "ass", profile)
    try:
        report = subtitle_qa(media, captions, project_id="local-captions", profile=profile)
        if report.cue_count or not (burn_ass or suffix == ".vtt"):
            return report
    except (MCPVideoError, ValueError, OSError, OverflowError):
        if not (burn_ass or suffix == ".vtt"):
            raise
    if burn_ass:
        return _convert_and_qa(media, burn_ass, "ass", profile)
    return _convert_and_qa(media, captions, "webvtt", profile)


def subtitle_advisory(
    media: str,
    captions: str,
    *,
    profile: str | None = None,
    burn_ass: str | None = None,
) -> dict[str, Any]:
    """Never claim a pass when cues are absent or the format/probe could not be inspected."""
    try:
        report = _report(media, captions, profile, burn_ass=burn_ass)
    except (MCPVideoError, ValueError, OSError, OverflowError):
        return {"status": SubtitleAdvisoryStatus.UNAVAILABLE.value, "passed": None, "profile": profile}
    counts = Counter(finding.detector.rsplit(":", 1)[-1] for finding in report.findings)
    passed = bool(report.cue_count) and not counts
    status = SubtitleAdvisoryStatus.PASSED if passed else SubtitleAdvisoryStatus.FAILED
    return {
        "status": status.value,
        "passed": passed,
        "profile": report.profile_name,
        "cue_count": report.cue_count,
        "max_cps": round(report.max_cps, 3),
        "overlap_count": counts["overlap"],
        "safe_area_violations": counts["safe_area"],
        "findings": dict(sorted(counts.items())),
    }
