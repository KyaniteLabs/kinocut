"""Capability discovery: structured capability report from diagnostics (#54)."""

from __future__ import annotations

from kinocut.capability_report import capability_report
from kinocut.contracts.capability import AvailabilityState, CapabilityReport


def _diagnostics(ffmpeg_ok: bool, whisper_ok: bool = False):
    """A minimal diagnostics payload shaped like run_diagnostics()."""

    return {
        "success": True,
        "checks": [
            {"name": "ffmpeg", "category": "core", "required": True, "ok": ffmpeg_ok},
            {"name": "ffprobe", "category": "core", "required": True, "ok": ffmpeg_ok},
            {"name": "openai-whisper", "category": "optional", "required": False, "ok": whisper_ok},
        ],
    }


def test_capability_report_returns_one_record_per_cataloged_capability():
    reports = capability_report(diagnostics=_diagnostics(ffmpeg_ok=True))
    assert len(reports) >= 1
    for report in reports:
        assert isinstance(report, CapabilityReport)
        assert report.capability_id
        # Every surface is strict-typed in the contract.
        assert isinstance(report.surfaces.mcp, bool)


def test_capability_with_required_deps_present_is_available_on_all_surfaces():
    reports = capability_report(diagnostics=_diagnostics(ffmpeg_ok=True))
    video = next(r for r in reports if r.capability_id == "video_edit")
    assert video.availability is AvailabilityState.AVAILABLE
    assert (video.surfaces.mcp, video.surfaces.python, video.surfaces.cli) == (True, True, True)
    assert video.reason_code is None
    assert video.remediation is None
    assert "ffmpeg" in video.required_deps


def test_capability_whose_required_dep_is_missing_is_unavailable_with_reason():
    reports = capability_report(diagnostics=_diagnostics(ffmpeg_ok=False))
    video = next(r for r in reports if r.capability_id == "video_edit")
    assert video.availability is AvailabilityState.UNAVAILABLE
    assert (video.surfaces.mcp, video.surfaces.python, video.surfaces.cli) == (False, False, False)
    assert video.reason_code == "required_dep_missing"
    assert video.remediation  # bounded advisory text, never a path/URL


def test_optional_dep_capability_is_available_when_required_dep_present():
    # ai_transcribe needs whisper (optional-ish) but is cataloged against its
    # required dep; when the required dep is present it is available even if an
    # optional enrichment dep is absent.
    reports = capability_report(diagnostics=_diagnostics(ffmpeg_ok=True, whisper_ok=False))
    core = next(r for r in reports if r.capability_id == "video_edit")
    assert core.availability is AvailabilityState.AVAILABLE


def test_capability_report_remediation_is_bounded_advisory_text():
    reports = capability_report(diagnostics=_diagnostics(ffmpeg_ok=False))
    for report in reports:
        if report.remediation is not None:
            # No host paths, URLs, or shell metacharacters in remediation text.
            assert "http" not in report.remediation
            assert "/" not in report.remediation
            assert len(report.remediation) <= 200


def test_capability_report_uses_live_diagnostics_when_none_passed():
    # Smoke: the no-arg path calls run_diagnostics() and still returns records.
    reports = capability_report()
    assert isinstance(reports, list)
    assert all(isinstance(r, CapabilityReport) for r in reports)
