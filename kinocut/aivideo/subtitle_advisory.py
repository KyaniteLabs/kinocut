"""Compact advisory QA of caption timings and profile-estimated layout, not rendered pixels."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_ffmpeg, _validate_input_path
from .subtitle_qa import SubtitleQaReport, subtitle_qa


def _report(media: str, captions: str, profile: str | None) -> SubtitleQaReport:
    if Path(captions).suffix.lower() != ".ass":
        return subtitle_qa(media, captions, project_id="local-captions", profile=profile)
    with TemporaryDirectory(prefix="kc_ass_qa_") as work:
        srt = str(Path(work) / "dialogue.srt")
        _run_ffmpeg(["-f", "ass", "-i", _validate_input_path(captions), "-map", "0:s:0", srt])
        return subtitle_qa(media, srt, project_id="local-captions", profile=profile)


def subtitle_advisory(media: str, captions: str, *, profile: str | None = None) -> dict[str, Any]:
    """Never claim a pass when cues are absent or the format/probe could not be inspected."""
    try:
        report = _report(media, captions, profile)
    except (MCPVideoError, ValueError, OSError, OverflowError):
        return {"status": "unavailable", "passed": None, "profile": profile}
    counts = Counter(finding.detector.rsplit(":", 1)[-1] for finding in report.findings)
    passed = bool(report.cue_count) and not counts
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "profile": report.profile_name,
        "cue_count": report.cue_count,
        "max_cps": round(report.max_cps, 3),
        "overlap_count": counts["overlap"],
        "safe_area_violations": counts["safe_area"],
        "findings": dict(sorted(counts.items())),
    }
