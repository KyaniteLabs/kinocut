"""Independent evidence verifier for composition plans and output packages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .composition import _require_digest, _validated
from .composition_models import CompositionApproval, CompositionPlan
from .models import canonical_digest
from .verification_models import (
    CompositionVerificationCheck,
    CompositionVerificationReport,
    VerificationEvidence,
)

_ZERO_SHA256 = "sha256:" + "0" * 64
CheckFunction = Callable[[CompositionPlan, CompositionApproval, VerificationEvidence], CompositionVerificationCheck]


def _check(check_id: str, passed: bool, message: str, details: dict[str, Any]) -> CompositionVerificationCheck:
    return CompositionVerificationCheck(id=check_id, passed=passed, message=message, details=details)


def _source_attribution(
    plan: CompositionPlan, _: CompositionApproval, evidence: VerificationEvidence
) -> CompositionVerificationCheck:
    required = {
        (binding.asset_id, span_id) for binding in plan.source_bindings for span_id in (binding.span_ids or (None,))
    }
    observed = {(item.asset_id, item.span_id) for item in evidence.attributions}
    missing = sorted(f"{asset_id}#{span_id or 'asset'}" for asset_id, span_id in required - observed)
    return _check(
        "source_attribution",
        not missing,
        "Every planned source binding has observed attribution."
        if not missing
        else "Source attribution is incomplete.",
        {"missing": missing},
    )


def _timeline_coverage(
    plan: CompositionPlan, approval: CompositionApproval, evidence: VerificationEvidence
) -> CompositionVerificationCheck:
    expected = {
        segment.id: (
            segment.output_start_seconds,
            segment.output_end_seconds,
            segment.selected_span_ids,
        )
        for segment in plan.timeline
    }
    observed = {
        item.segment_id: (item.output_start_seconds, item.output_end_seconds, item.selected_span_ids)
        for item in evidence.timeline
    }
    approved = set(approval.approved_segment_ids) == set(expected)
    passed = observed == expected and approved
    return _check(
        "timeline_coverage",
        passed,
        "Observed timeline exactly matches approved source coverage."
        if passed
        else "Observed timeline or approval coverage differs from the plan.",
        {"expected_segment_ids": sorted(expected), "observed_segment_ids": sorted(observed)},
    )


def _audio_mix(
    plan: CompositionPlan, _: CompositionApproval, evidence: VerificationEvidence
) -> CompositionVerificationCheck:
    observed = {item.track_id: item for item in evidence.audio}
    failures: list[str] = []
    for track in plan.audio_tracks:
        item = observed.get(track.id)
        if item is None:
            failures.append(f"{track.id}:missing")
            continue
        if item.peak_dbfs > track.max_peak_dbfs:
            failures.append(f"{track.id}:peak")
        if abs(item.integrated_lufs - track.target_lufs) > 1.0:
            failures.append(f"{track.id}:loudness")
    passed = not failures and set(observed) == {track.id for track in plan.audio_tracks}
    return _check(
        "audio_mix",
        passed,
        "Observed audio satisfies every declared mix target."
        if passed
        else "Audio mix evidence does not match targets.",
        {"failures": failures},
    )


def _text_layout(
    plan: CompositionPlan, _: CompositionApproval, evidence: VerificationEvidence
) -> CompositionVerificationCheck:
    required_ids = {item.id for item in plan.graphics if item.kind == "text"}
    if plan.caption_plan:
        required_ids.add(plan.caption_plan.id)
    observed = {item.element_id: item for item in evidence.text}
    failures = sorted(
        element_id
        for element_id in required_ids
        if element_id not in observed or not observed[element_id].inside_safe_area or not observed[element_id].readable
    )
    passed = not failures
    return _check(
        "text_layout",
        passed,
        "All planned text is readable and inside the safe area." if passed else "Text layout evidence failed.",
        {"failures": failures},
    )


def _branding(
    plan: CompositionPlan, _: CompositionApproval, evidence: VerificationEvidence
) -> CompositionVerificationCheck:
    observed = evidence.branding
    planned_logos = {item.asset_id for item in plan.graphics if item.kind == "logo" and item.asset_id}
    planned_fonts = {item.font_asset_id for item in plan.graphics if item.font_asset_id}
    if plan.caption_plan and plan.caption_plan.font_asset_id:
        planned_fonts.add(plan.caption_plan.font_asset_id)
    planned_colors = {item.color for item in plan.graphics if item.color}
    if plan.caption_plan and plan.caption_plan.color:
        planned_colors.add(plan.caption_plan.color)
    required_text = set(plan.brand_constraints.required_text)
    observed_text = set(observed.rendered_text)
    forbidden_found = sorted(set(plan.brand_constraints.forbidden_text) & observed_text)
    failures = {
        "logos": sorted(planned_logos - set(observed.logo_asset_ids)),
        "fonts": sorted(planned_fonts - set(observed.font_asset_ids)),
        "colors": sorted(planned_colors - set(observed.colors)),
        "text": sorted(required_text - observed_text),
        "forbidden_text": forbidden_found,
    }
    passed = not any(failures.values())
    return _check(
        "branding",
        passed,
        "Observed branding matches the approved constraints." if passed else "Branding evidence failed.",
        failures,
    )


def _variant_contracts(
    plan: CompositionPlan, _: CompositionApproval, evidence: VerificationEvidence
) -> CompositionVerificationCheck:
    expected = {item.id: (item.width, item.height, item.container) for item in plan.output_variants}
    observed = {item.variant_id: (item.width, item.height, item.container) for item in evidence.package.artifacts}
    passed = observed == expected
    return _check(
        "variant_contracts",
        passed,
        "Output artifacts match every declared variant." if passed else "Output variants differ from the plan.",
        {"expected": sorted(expected), "observed": sorted(observed)},
    )


def _package_integrity(
    plan: CompositionPlan, approval: CompositionApproval, evidence: VerificationEvidence
) -> CompositionVerificationCheck:
    package = evidence.package
    artifacts_valid = all(item.sha256 and item.size_bytes > 0 for item in package.artifacts)
    passed = (
        approval.plan_sha256 == plan.plan_sha256
        and package.plan_sha256 == plan.plan_sha256
        and package.approval_sha256 == approval.approval_sha256
        and artifacts_valid
        and len(package.artifacts) == len(plan.output_variants)
    )
    return _check(
        "package_integrity",
        passed,
        "Package hashes and approval binding are complete." if passed else "Package integrity evidence failed.",
        {"artifact_count": len(package.artifacts)},
    )


_CHECKS: Mapping[str, CheckFunction] = {
    "source_attribution": _source_attribution,
    "timeline_coverage": _timeline_coverage,
    "audio_mix": _audio_mix,
    "text_layout": _text_layout,
    "branding": _branding,
    "variant_contracts": _variant_contracts,
    "package_integrity": _package_integrity,
}


def verify_composition(
    *,
    plan: CompositionPlan | Mapping[str, Any],
    approval: CompositionApproval | Mapping[str, Any],
    evidence: VerificationEvidence | Mapping[str, Any],
) -> CompositionVerificationReport:
    """Verify caller-observed evidence; this function never probes output files itself."""

    valid_plan = _validated(plan, CompositionPlan)
    valid_approval = _validated(approval, CompositionApproval)
    valid_evidence = _validated(evidence, VerificationEvidence)
    _require_digest(valid_plan, "plan_sha256", "composition_plan_hash_mismatch")
    _require_digest(valid_approval, "approval_sha256", "composition_approval_hash_mismatch")
    checks = tuple(
        _CHECKS[check_id](valid_plan, valid_approval, valid_evidence) for check_id in valid_plan.verifier_ids
    )
    draft = CompositionVerificationReport(
        plan_sha256=valid_plan.plan_sha256,
        passed=all(check.passed for check in checks),
        checks=checks,
        report_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"report_sha256": canonical_digest(draft, exclude={"report_sha256"})})
