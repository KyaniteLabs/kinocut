"""Governed review ledger (#48, #49, #50, #51).

Writers and queries over the review contracts (design §4.9): timestamped human
review decisions, the known-limitation ledger, dependency-fingerprint approval
invalidation, and the fail-closed publish gate. Every decision is human-made;
``publishable`` is always derived, never stored.
"""

from __future__ import annotations

from pydantic import Field

from kinocut.contracts._common import ValueObject
from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.defect import DefectFinding, DefectStatus
from kinocut.contracts.review import (
    ApprovalState,
    ApprovalStateValue,
    KnownLimitation,
    ReviewDecision,
)
from kinocut.projectstore import Project, append_record, read_records

_NON_BLOCKING_DEFECT_STATUSES = frozenset({DefectStatus.RESOLVED, DefectStatus.FALSE_POSITIVE})


def _active(project: Project, kind: str, model: type) -> list[object]:
    """Exact-type records whose id no later record supersedes."""

    rows = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


# --- #48 timestamped review decisions ---


def record_review_decision(project: Project, decision: ReviewDecision) -> ReviewDecision:
    """Persist one human review decision. Corrections supersede by id."""

    appended = append_record(project, decision)
    return appended  # type: ignore[return-value]


def review_decisions_for_target(project: Project, target_ref: str) -> list[ReviewDecision]:
    """Return active review decisions bound to ``target_ref``."""

    return [d for d in _active(project, "review_decision", ReviewDecision) if d.target_ref == target_ref]


def _decision_exists(project: Project, decision_id: str) -> bool:
    rows = read_records(project, "review_decision")
    return any(type(item) is ReviewDecision and item.record_id == decision_id for item in rows)


# --- #50 known-limitation ledger ---


def record_known_limitation(project: Project, limitation: KnownLimitation) -> KnownLimitation:
    """Persist one accepted limitation, bound to its authorizing decision."""

    if not _decision_exists(project, limitation.accepted_by_decision_id):
        raise contract_error(
            "known limitation references no authorizing review decision", INVALID_RECORD
        )
    appended = append_record(project, limitation)
    return appended  # type: ignore[return-value]


def known_limitations(project: Project) -> list[KnownLimitation]:
    """Return active accepted-limitation records."""

    return _active(project, "known_limitation", KnownLimitation)  # type: ignore[return-value]


# --- approval state + #51 invalidation ---


def record_approval_state(project: Project, state: ApprovalState) -> ApprovalState:
    """Persist one approval-state record."""

    appended = append_record(project, state)
    return appended  # type: ignore[return-value]


def _states_for_candidate(project: Project, candidate: str) -> list[ApprovalState]:
    return [
        item
        for item in read_records(project, "approval_state")
        if type(item) is ApprovalState and item.candidate_artifact == candidate
    ]


def _active_state(project: Project, candidate: str) -> ApprovalState | None:
    states = _states_for_candidate(project, candidate)
    superseded = {item.supersedes for item in states if item.supersedes is not None}
    active = [item for item in states if item.record_id not in superseded]
    return active[-1] if active else None


def invalidate_approval(project: Project, prior_state_id: str, reason: str) -> ApprovalState:
    """Append a superseding invalidated state when a dependency changes (#51).

    The prior state is immutable; invalidation is a new record that supersedes
    it. The publish gate derives supersession from this history, so a stale
    approval can never publish.
    """

    prior = next(
        (item for item in read_records(project, "approval_state")
         if type(item) is ApprovalState and item.record_id == prior_state_id),
        None,
    )
    if prior is None:
        raise contract_error("no approval state found to invalidate", INVALID_RECORD)
    data = prior.model_dump()
    data["supersedes"] = prior.record_id
    data["state"] = ApprovalStateValue.INVALIDATED
    data["invalidation_reasons"] = (*prior.invalidation_reasons, reason)
    data.pop("record_id", None)
    data.pop("superseding_state_id", None)
    successor = ApprovalState(**data)
    return append_record(project, successor)  # type: ignore[return-value]


# --- #49 fail-closed publish gate ---


class PublishGateResult(ValueObject):
    """Derived publishability for a candidate artifact; never stored."""

    publishable: bool
    reasons: tuple[str, ...] = Field(default=())


class ReviewPackage(ValueObject):
    """A governed review manifest assembling the evidence for a candidate (#47).

    Read-only projection over the review ledger: the derived publish verdict, the
    active review decisions, accepted limitations, and unresolved blocking
    defects for one candidate artifact. Never a stored approval boolean.
    """

    candidate_artifact: str
    publishable: bool
    publish_gate_reasons: tuple[str, ...] = ()
    review_decision_ids: tuple[str, ...] = ()
    known_limitation_ids: tuple[str, ...] = ()
    open_defect_ids: tuple[str, ...] = ()
    human_review_required: bool = True


def _active_defects(project: Project) -> list[DefectFinding]:
    rows = [item for item in read_records(project, "defect_finding") if type(item) is DefectFinding]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def review_package(
    project: Project,
    candidate_artifact: str,
    *,
    blocking_findings: tuple[str, ...] = (),
) -> ReviewPackage:
    """Assemble the review manifest for ``candidate_artifact`` (#47)."""

    gate = evaluate_publish_gate(project, candidate_artifact, blocking_findings=blocking_findings)
    decisions = review_decisions_for_target(project, candidate_artifact)
    limitations = known_limitations(project)
    open_defects = [
        finding.record_id
        for finding in _active_defects(project)
        if finding.status not in _NON_BLOCKING_DEFECT_STATUSES
    ]
    return ReviewPackage(
        candidate_artifact=candidate_artifact,
        publishable=gate.publishable,
        publish_gate_reasons=gate.reasons,
        review_decision_ids=tuple(decision.record_id for decision in decisions),
        known_limitation_ids=tuple(item.record_id for item in limitations),
        open_defect_ids=tuple(open_defects),
    )


def evaluate_publish_gate(
    project: Project,
    candidate_artifact: str,
    *,
    blocking_findings: tuple[str, ...],
) -> PublishGateResult:
    """Derive whether ``candidate_artifact`` may publish (design §4.9).

    Fail-closed: no approval state, any blocking finding, any invalidation, or
    any failed integrity/decision sub-check blocks publishing. The authoritative
    verdict comes from :meth:`ApprovalState.is_publishable`; ``reasons`` are an
    advisory human-readable explanation.
    """

    reasons: list[str] = []
    if blocking_findings:
        reasons.append(f"blocked by {len(blocking_findings)} unresolved finding(s)")
    active = _active_state(project, candidate_artifact)
    if active is None:
        reasons.append("no active approval state for candidate")
        return PublishGateResult(publishable=False, reasons=tuple(reasons))
    if active.invalidation_reasons:
        reasons.append("candidate approval is invalidated/superseded")
    states = _states_for_candidate(project, candidate_artifact)
    decisions = [
        item for item in read_records(project, "review_decision") if type(item) is ReviewDecision
    ]
    publishable = active.is_publishable(decisions, states, blocking_findings=blocking_findings)
    if not publishable and not reasons:
        reasons.append("publish conditions not satisfied (approval/integrity/decision checks)")
    return PublishGateResult(publishable=publishable, reasons=tuple(reasons))


__all__ = [
    "PublishGateResult",
    "ReviewPackage",
    "evaluate_publish_gate",
    "invalidate_approval",
    "known_limitations",
    "record_approval_state",
    "record_known_limitation",
    "record_review_decision",
    "review_decisions_for_target",
    "review_package",
]
