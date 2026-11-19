"""Evaluate a measured final-delivery quality report."""

from typing import Any

from .errors import MCPVideoError
from .quality_profiles import FILM_GRADE_PROFILE, VISUAL_PROFILE_CHECKS

NO_AUDIO_STREAM_REASON = "no_audio_stream"


def _report_missing_audio_stream(report: dict[str, Any]) -> bool:
    """Whether a quality report's audio_levels check failed for having no audio stream."""
    for check in report.get("checks", []):
        if check.get("name") != "audio_levels":
            continue
        details = check.get("details") or {}
        return details.get("reason") == NO_AUDIO_STREAM_REASON and check.get("passed") is not True
    return False


def _profile_gate_failures(report: dict[str, Any]) -> list[str]:
    """Visual checks that fail a profile which makes its bands hard limits."""
    if not (report.get("profile") or {}).get("visual_checks_gate"):
        return []
    return [
        check["name"]
        for check in report.get("checks", [])
        if check.get("name") in VISUAL_PROFILE_CHECKS and check.get("passed") is not True
    ]


def enforce_quality_gate(
    report: dict[str, Any],
    *,
    min_score: float,
    require_audio: bool,
    profile: str | None,
    profile_reason: str | None,
    require_clean_audio: bool,
    advisory_checks: tuple[str, ...],
) -> dict[str, Any]:
    """Record the decision and raise on a failed quality gate."""
    audio_missing = require_audio and _report_missing_audio_stream(report)
    score_ok = report["overall_score"] >= min_score
    profile_failures = _profile_gate_failures(report)
    baseline, reason = report.get("profile_baseline"), (profile_reason or "").strip()[:200]
    default_would_fail = bool(baseline) and float(baseline["overall_score"]) < min_score
    unexplained_switch = (default_would_fail or bool(report.get("advisory_checks"))) and not reason
    failed_audio = (require_clean_audio or profile == FILM_GRADE_PROFILE) and any(
        check["name"] == "audio_levels" and not check["passed"]
        for check in report["checks"]
        if require_audio or check["details"].get("has_audio") is not False
    )
    if baseline and reason:
        report["profile_override"] = {
            "reason": reason,
            "profile": report["profile"]["name"],
            "profile_score": report["overall_score"],
            "default_score": baseline["overall_score"],
            "default_failed_checks": baseline["failed_checks"],
        }
    # ``all_passed`` stays the per-check aggregate from ``quality_check``; the
    # score gate gets its own fields so a passing gate never reads as
    # "every check passed" over failed checks.
    advisory = {*advisory_checks, *report.get("advisory_checks", [])}
    report["gate_passed"] = (
        score_ok and not audio_missing and not failed_audio and not profile_failures and not unexplained_switch
    )
    report["min_score"] = min_score
    report["failed_checks"] = [
        c["name"] for c in report.get("checks", []) if not c.get("passed") and c.get("name") not in advisory
    ]
    if not report["gate_passed"]:
        failures: list[str] = []
        overall_score = float(report["overall_score"])
        if not score_ok:
            failures.append(f"score {overall_score:.1f} < {min_score:.1f}")
        if audio_missing:
            failures.append("no audio stream detected (audio required)")
        elif failed_audio:
            failures.append("audio level check failed")
        if profile_failures:
            failures.append(f"{report['profile']['name']} profile limits failed: {', '.join(profile_failures)}")
        if unexplained_switch:
            failures.append(
                f"{report['profile']['name']} scores {overall_score:.1f} but the default profile scores "
                f"{float(baseline['overall_score']):.1f}; pass profile_reason to say why this profile fits the cut"
            )
        recommendations = "; ".join(report.get("recommendations", []))
        raise MCPVideoError(
            f"Quality gate failed: {'; '.join(failures)}. {recommendations}",
            error_type="quality_error",
            code="quality_gate_failed",
            suggested_action={
                "auto_fix": False,
                "description": "Inspect storyboard/thumbnail, fix visual/audio issues, then rerun quality checks.",
            },
        )
    return report
