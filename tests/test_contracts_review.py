"""Tests for ``ReviewDecision``, ``KnownLimitation``, ``ApprovalState`` (design §4.9).

Review decisions are always made by a human. ``publishable`` is a derived
result, never a stored mutable boolean.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts.review import (
    ApprovalState,
    ApprovalStateValue,
    DecisionType,
    KnownLimitation,
    ReviewDecision,
)
from tests.contracts_fixtures import (
    approval_state_kwargs,
    known_limitation_kwargs,
    review_decision_kwargs,
)


def test_review_decision_is_a_record():
    decision = ReviewDecision(**review_decision_kwargs())
    assert isinstance(decision, RecordBase)
    assert canonical_record_id(decision).startswith("sha256:")


def test_review_decision_actor_must_be_human():
    with pytest.raises(ValidationError):
        ReviewDecision(**review_decision_kwargs(actor="agent"))
    with pytest.raises(ValidationError):
        ReviewDecision(**review_decision_kwargs(actor="tool"))


def test_review_decision_types_are_closed():
    assert {d.value for d in DecisionType} == {
        "approve",
        "reject",
        "trim",
        "repair",
        "regenerate",
        "accept_limitation",
    }


def test_known_limitation_is_a_record():
    limitation = KnownLimitation(**known_limitation_kwargs())
    assert isinstance(limitation, RecordBase)


def test_approval_state_values_are_closed():
    assert {s.value for s in ApprovalStateValue} == {
        "pending",
        "approved",
        "invalidated",
        "rejected",
    }


def test_approval_state_publishable_is_derived_not_stored():
    assert "publishable" not in ApprovalState.model_fields
    assert callable(getattr(ApprovalState, "is_publishable", None))


_ARTIFACT = "sha256:" + "a" * 64
_FINGERPRINT = "sha256:" + "b" * 64


def _approved_bundle(*, state: str = "approved", integrity_passed: bool = True):
    """An approval plus the resolved, freshly-bound human decision it requires."""

    decision = ReviewDecision(
        **review_decision_kwargs(decision="approve", dependency_fingerprint=_FINGERPRINT, target_ref=_ARTIFACT)
    )
    rid = canonical_record_id(decision)
    approval = ApprovalState(
        **approval_state_kwargs(
            state=state,
            dependency_fingerprint=_FINGERPRINT,
            required_artifact_ids=(_ARTIFACT,),
            integrity_results=({"artifact_id": _ARTIFACT, "passed": integrity_passed},),
            required_human_decisions=(rid,),
        )
    )
    return approval, decision


def _pub(approval, decisions, *, blocking=(), history=()) -> bool:
    return approval.is_publishable(decisions, history, blocking_findings=blocking)


def test_approval_state_is_publishable_when_fully_approved():
    approval, decision = _approved_bundle()
    assert _pub(approval, [decision]) is True


def test_approval_state_is_not_publishable_when_pending():
    approval, decision = _approved_bundle(state="pending")
    assert _pub(approval, [decision]) is False


def test_approval_state_not_publishable_with_unresolved_blocking_finding():
    approval, decision = _approved_bundle()
    assert _pub(approval, [decision], blocking=(_ARTIFACT,)) is False


def test_approval_state_not_publishable_when_missing_decision():
    approval, _ = _approved_bundle()
    assert _pub(approval, []) is False


def test_approval_state_not_publishable_when_integrity_fails():
    approval, decision = _approved_bundle(integrity_passed=False)
    assert _pub(approval, [decision]) is False


def test_approval_state_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ApprovalState(**approval_state_kwargs(publishable=True))
