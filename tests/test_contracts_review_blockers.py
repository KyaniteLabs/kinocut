"""Independent-review blocker regressions for Wave 0 domain contracts (Task 2).

Each test pins one review finding: versions are frozen to ``Literal[1]``; cross-
record references are canonical ``Sha256`` ids bound to the exact record; ranges
are positive and nonnegative; normalized regions stay inside the frame with
positive area; acceptance thresholds are closed to the defect/severity enums;
``canonical_record_id`` is restricted to ``RecordBase`` with informational-only
exclusions; and ``ApprovalState.is_publishable`` consumes resolved review
evidence bound to the current dependency fingerprint.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from kinocut.contracts._common import (
    NormalizedRegion,
    RecordBase,
    canonical_record_id,
)
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.protection import ProtectedElement
from kinocut.contracts.review import (
    ApprovalState,
    ApprovalStateValue,
    IntegrityResult,
    ReviewDecision,
)
from kinocut.contracts.verdict import ClipVerdict
from tests.contracts_fixtures import (
    acceptance_spec_kwargs,
    approval_state_kwargs,
    defect_kwargs,
    protection_kwargs,
    review_decision_kwargs,
    valid_record_kwargs,
    verdict_kwargs,
)

_SHA = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_SHA_C = "sha256:" + "c" * 64


# ---- Versions frozen to Literal[1] ---------------------------------------


def test_schema_version_is_frozen_to_one():
    with pytest.raises(ValidationError):
        RecordBase(**valid_record_kwargs(schema_version=2))


def test_defect_taxonomy_version_is_frozen_to_one():
    with pytest.raises(ValidationError):
        DefectFinding(**defect_kwargs(taxonomy_version=2))


# ---- Canonical Sha256 cross-record references ----------------------------


def test_clip_verdict_acceptance_binds_to_canonical_record():
    # A bare label is no longer accepted: acceptance must be the exact record id.
    with pytest.raises(ValidationError):
        ClipVerdict(**verdict_kwargs(acceptance_spec_id="spec-1"))
    ok = ClipVerdict(**verdict_kwargs(acceptance_spec_id=_SHA))
    assert ok.acceptance_spec_id == _SHA


def test_protected_element_requires_canonical_human_approval_ref():
    with pytest.raises(ValidationError):
        ProtectedElement(**protection_kwargs(human_approval_ref="decision:1"))
    with pytest.raises(ValidationError):
        ProtectedElement(**protection_kwargs(human_approval_ref=None))
    ok = ProtectedElement(**protection_kwargs(human_approval_ref=_SHA))
    assert ok.human_approval_ref == _SHA


# ---- Range and region invariants -----------------------------------------


def test_defect_time_range_must_be_positive_and_nonnegative():
    with pytest.raises(ValidationError):
        DefectFinding(**defect_kwargs(time_range=(-0.1, 1.0)))  # negative time
    with pytest.raises(ValidationError):
        DefectFinding(**defect_kwargs(time_range=(1.0, 1.0)))  # zero-length
    ok = DefectFinding(**defect_kwargs(time_range=(0.0, 1.5)))
    assert ok.time_range == (0.0, 1.5)


def test_review_decision_target_range_must_be_positive():
    with pytest.raises(ValidationError):
        ReviewDecision(**review_decision_kwargs(decision="trim", target_range=(2.0, 1.0)))
    with pytest.raises(ValidationError):
        ReviewDecision(**review_decision_kwargs(decision="trim", target_range=(-1.0, 2.0)))
    ok = ReviewDecision(**review_decision_kwargs(decision="trim", target_range=(0.0, 2.0)))
    assert ok.target_range == (0.0, 2.0)


def test_normalized_region_must_stay_in_frame_with_positive_area():
    with pytest.raises(ValidationError):
        NormalizedRegion(x=0.9, y=0.1, width=0.2, height=0.1)  # x + width > 1
    with pytest.raises(ValidationError):
        NormalizedRegion(x=0.1, y=0.1, width=0.0, height=0.1)  # zero area
    ok = NormalizedRegion(x=0.1, y=0.1, width=0.2, height=0.1)
    assert ok.width == 0.2


# ---- Acceptance thresholds closed to enums -------------------------------


def test_acceptance_thresholds_closed_to_defect_and_severity_enums():
    with pytest.raises(ValidationError):
        GenerationAcceptanceSpec(**acceptance_spec_kwargs(forbidden_defect_codes=("not_a_code",)))
    with pytest.raises(ValidationError):
        GenerationAcceptanceSpec(
            **acceptance_spec_kwargs(
                severity_thresholds=({"defect_code": "identity_drift", "max_severity": "catastrophic"},)
            )
        )
    with pytest.raises(ValidationError):
        GenerationAcceptanceSpec(
            **acceptance_spec_kwargs(severity_thresholds=({"defect_code": "not_a_code", "max_severity": "low"},))
        )
    ok = GenerationAcceptanceSpec(**acceptance_spec_kwargs())
    assert ok.forbidden_defect_codes == ("text_drift",)


# ---- canonical_record_id restricted --------------------------------------


def test_canonical_record_id_rejects_non_record_base():
    class NotARecord(BaseModel):
        x: int = 1

    with pytest.raises((TypeError, ValueError)):
        canonical_record_id(NotARecord())


def test_canonical_record_id_rejects_semantic_exclusions():
    verdict = ClipVerdict(**verdict_kwargs(acceptance_spec_id=_SHA))
    # Excluding a *semantic* field would let two different records collide.
    with pytest.raises((ValueError, TypeError)):
        canonical_record_id(verdict, exclude=frozenset({"disposition"}))


# ---- ApprovalState.is_publishable redesign -------------------------------


def _approved_state(
    *,
    fingerprint: str,
    decision_ids: tuple[str, ...],
    state=ApprovalStateValue.APPROVED,
    integrity=None,
    blocking=(),
    candidate: str = _SHA,
    superseding=None,
) -> ApprovalState:
    kwargs = approval_state_kwargs(
        candidate_artifact=candidate,
        dependency_fingerprint=fingerprint,
        required_artifact_ids=(_SHA,),
        integrity_results=integrity if integrity is not None else (IntegrityResult(artifact_id=_SHA, passed=True),),
        required_human_decisions=decision_ids,
        state=state,
        invalidation_reasons=blocking,
        superseding_state_id=superseding,
    )
    return ApprovalState(**kwargs)


def _decision(
    *, fingerprint: str, decision: str = "approve", target: str = _SHA, created_by: str = "human"
) -> tuple[ReviewDecision, str]:
    rec = ReviewDecision(
        **review_decision_kwargs(
            decision=decision, dependency_fingerprint=fingerprint, target_ref=target, created_by=created_by
        )
    )
    return rec, canonical_record_id(rec)


def _pub(state, decisions, *, blocking=(), history=()) -> bool:
    """Call ``is_publishable`` with the fail-closed, fully-explicit signature."""

    return state.is_publishable(decisions, history, blocking_findings=blocking)


def test_is_publishable_true_when_evidence_is_complete_and_fresh():
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [dec]) is True


def test_is_publishable_false_when_required_decision_missing():
    _, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, []) is False


def test_is_publishable_false_when_decision_rejected():
    dec, rid = _decision(fingerprint=_SHA_B, decision="reject")
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_decision_is_stale():
    # Approved, but the decision was made against a different dependency fingerprint.
    dec, rid = _decision(fingerprint=_SHA)  # fingerprint _SHA
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))  # state expects _SHA_B
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_integrity_missing_or_conflicting():
    dec, rid = _decision(fingerprint=_SHA_B)
    missing = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,), integrity=())
    assert _pub(missing, [dec]) is False
    conflicting = _approved_state(
        fingerprint=_SHA_B,
        decision_ids=(rid,),
        integrity=(IntegrityResult(artifact_id=_SHA, passed=True), IntegrityResult(artifact_id=_SHA, passed=False)),
    )
    assert _pub(conflicting, [dec]) is False


def test_is_publishable_false_when_candidate_has_a_failed_integrity_result():
    # Candidate C passes on one line but FAILS on another while only A is required.
    dec, rid = _decision(fingerprint=_SHA_B, target=_SHA_C)
    state = _approved_state(
        fingerprint=_SHA_B,
        decision_ids=(rid,),
        candidate=_SHA_C,
        integrity=(
            IntegrityResult(artifact_id=_SHA, passed=True),
            IntegrityResult(artifact_id=_SHA_C, passed=True),
            IntegrityResult(artifact_id=_SHA_C, passed=False),
        ),
    )
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_blocking_findings_present():
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [dec], blocking=(_SHA,)) is False


def test_is_publishable_requires_explicit_completeness_evidence():
    # Omitting the fail-closed evidence arguments is a hard error, not a silent pass.
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    with pytest.raises(TypeError):
        state.is_publishable([dec], [])  # missing required blocking_findings


def test_is_publishable_false_when_not_approved():
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,), state=ApprovalStateValue.PENDING)
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_decision_targets_other_artifact():
    # A decision approving a *different* artifact must not publish the candidate.
    dec, rid = _decision(fingerprint=_SHA_B, target=_SHA_C)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_decision_lacks_human_provenance():
    dec, rid = _decision(fingerprint=_SHA_B, created_by="agent")
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_candidate_artifact_not_verified():
    # Candidate is not among the integrity-passed required artifacts.
    dec, rid = _decision(fingerprint=_SHA_B, target=_SHA_C)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,), candidate=_SHA_C)
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_state_is_superseded_by_field_or_history():
    dec, rid = _decision(fingerprint=_SHA_B)
    by_field = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,), superseding=_SHA_B)
    assert _pub(by_field, [dec]) is False
    # Derived from history: an old approved state superseded by a NEW rejected
    # state (whose supersedes points at the old) is not publishable.
    old = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    old_id = canonical_record_id(old)
    newer_rejected = ApprovalState(
        **approval_state_kwargs(state="rejected", supersedes=old_id, candidate_artifact=_SHA_C)
    )
    assert _pub(old, [dec], history=[newer_rejected]) is False


def test_is_publishable_false_when_self_is_subclass_or_forged():
    dec, rid = _decision(fingerprint=_SHA_B)

    class LookalikeState(ApprovalState):
        pass

    impostor = LookalikeState(
        **approval_state_kwargs(
            state="approved",
            dependency_fingerprint=_SHA_B,
            candidate_artifact=_SHA,
            required_artifact_ids=(_SHA,),
            integrity_results=({"artifact_id": _SHA, "passed": True},),
            required_human_decisions=(rid,),
        )
    )
    assert _pub(impostor, [dec]) is False  # self is a subclass → fail closed
    valid = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    forged_self = valid.model_copy(update={"record_id": "sha256:" + "9" * 64})
    assert _pub(forged_self, [dec]) is False  # self carries a forged record_id


def test_is_publishable_false_when_approve_superseded_by_newer_reject():
    approve, rid = _decision(fingerprint=_SHA_B)
    reject = ReviewDecision(
        **review_decision_kwargs(decision="reject", target_ref=_SHA, dependency_fingerprint=_SHA_B, supersedes=rid)
    )
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [approve, reject]) is False


def test_canonical_record_id_maps_unicode_error():
    from kinocut.errors import MCPVideoError

    bad = ReviewDecision(**review_decision_kwargs(rationale="lone surrogate \ud800 here"))
    with pytest.raises(MCPVideoError):
        canonical_record_id(bad)


def test_is_publishable_fails_closed_on_untrusted_history():
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))

    class LookalikeState(ApprovalState):
        pass

    impostor = LookalikeState(**approval_state_kwargs())
    assert _pub(state, [dec], history=[impostor]) is False  # subclass → untrusted
    dup = ApprovalState(**approval_state_kwargs())
    assert _pub(state, [dec], history=[dup, dup]) is False  # duplicate → untrusted


def test_is_publishable_false_when_decision_identity_is_forged():
    # A decision whose *content* differs from the required id (only a supplied
    # record_id makes it look right) must be rejected: identity is recomputed.
    legit, rid = _decision(fingerprint=_SHA_B)
    forged = legit.model_copy(update={"record_id": rid, "rationale": "tampered rationale"})
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [forged]) is False


def test_is_publishable_false_when_required_decision_ids_duplicated():
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid, rid))
    assert _pub(state, [dec]) is False


def test_is_publishable_false_when_resolved_decision_is_subclass():
    class LookalikeDecision(ReviewDecision):
        pass

    impostor = LookalikeDecision(
        **review_decision_kwargs(decision="approve", target_ref=_SHA, dependency_fingerprint=_SHA_B)
    )
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(canonical_record_id(impostor),))
    assert _pub(state, [impostor]) is False


def test_is_publishable_false_when_resolved_decisions_have_duplicate_canonical():
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    assert _pub(state, [dec, dec]) is False  # duplicate resolved decision → untrusted


def test_is_publishable_false_when_required_approve_superseded_by_trim():
    approve, rid = _decision(fingerprint=_SHA_B)
    trim = ReviewDecision(
        **review_decision_kwargs(
            decision="trim",
            target_ref=_SHA,
            dependency_fingerprint=_SHA_B,
            target_range=(0.0, 1.0),
            supersedes=rid,
        )
    )
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    # A required approve superseded by ANY later decision is no longer current.
    assert _pub(state, [approve, trim]) is False


def test_is_publishable_fails_closed_on_dangling_history_supersedes():
    dec, rid = _decision(fingerprint=_SHA_B)
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    dangling = ApprovalState(**approval_state_kwargs(supersedes="sha256:" + "7" * 64))
    assert _pub(state, [dec], history=[dangling]) is False  # invalid graph → fail closed


def test_is_publishable_false_when_a_current_reject_exists():
    approve, rid = _decision(fingerprint=_SHA_B)
    reject = ReviewDecision(**review_decision_kwargs(decision="reject", target_ref=_SHA, dependency_fingerprint=_SHA_B))
    state = _approved_state(fingerprint=_SHA_B, decision_ids=(rid,))
    # A concurrent reject/repair/regenerate for the same candidate+fingerprint blocks publish.
    assert _pub(state, [approve, reject]) is False


def test_review_decision_range_is_bounded_for_approve_or_trim():
    # An approval may bind an exact accepted trim; trim itself still requires it.
    approved = ReviewDecision(**review_decision_kwargs(decision="approve", target_range=(0.0, 1.0)))
    assert approved.target_range == (0.0, 1.0)
    with pytest.raises(ValidationError):
        ReviewDecision(**review_decision_kwargs(decision="trim", target_range=None))
    ok = ReviewDecision(**review_decision_kwargs(decision="trim", target_range=(0.0, 1.0)))
    assert ok.target_range == (0.0, 1.0)


# ---- Additional model hardening (findings 10-12) --------------------------


def test_usage_rights_evidence_ref_must_be_project_relative():
    from kinocut.contracts.asset import AssetRecord
    from tests.contracts_fixtures import asset_record_kwargs

    with pytest.raises(ValidationError):
        AssetRecord(**asset_record_kwargs(usage_rights_evidence_ref="/etc/rights.json"))
    with pytest.raises(ValidationError):
        AssetRecord(**asset_record_kwargs(usage_rights_evidence_ref="http://x/y"))
    ok = AssetRecord(**asset_record_kwargs(usage_rights_evidence_ref="rights/clip.json"))
    assert ok.usage_rights_evidence_ref == "rights/clip.json"


def test_taxonomy_version_rejects_bool_and_float():
    for bad in (True, 1.0, "1"):
        with pytest.raises(ValidationError):
            DefectFinding(**defect_kwargs(taxonomy_version=bad))


def test_clip_verdict_range_only_on_approved_with_trim():
    # Only approved_with_trim may carry a range; any other disposition rejects it.
    with pytest.raises(ValidationError):
        ClipVerdict(**verdict_kwargs(acceptance_spec_id=_SHA, disposition="approved", approved_range=(0.0, 1.0)))
    with pytest.raises(ValidationError):
        ClipVerdict(**verdict_kwargs(acceptance_spec_id=_SHA, disposition="rejected", approved_range=(0.0, 1.0)))
    ok = ClipVerdict(
        **verdict_kwargs(acceptance_spec_id=_SHA, disposition="approved_with_trim", approved_range=(0.0, 1.0))
    )
    assert ok.approved_range == (0.0, 1.0)
