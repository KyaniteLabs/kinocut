"""``ReviewDecision``, ``KnownLimitation``, ``ApprovalState`` (design §4.9).

Review decisions are always made by a human. ``publishable`` is a derived
result — never a stored mutable boolean — computed from candidate integrity,
required-artifact coverage, unresolved findings, and human approval.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Literal

from pydantic import model_validator
from pydantic import Field

from kinocut.contracts._common import (
    RecordBase,
    Sha256,
    ValueObject,
    canonical_record_id,
)


class DecisionType(StrEnum):
    """The closed set of editorial decisions a human reviewer may record."""

    APPROVE = "approve"
    REJECT = "reject"
    TRIM = "trim"
    REPAIR = "repair"
    REGENERATE = "regenerate"
    ACCEPT_LIMITATION = "accept_limitation"


class ApprovalStateValue(StrEnum):
    """Lifecycle state of an approval; a new candidate always starts pending."""

    PENDING = "pending"
    APPROVED = "approved"
    INVALIDATED = "invalidated"
    REJECTED = "rejected"


class IntegrityResult(ValueObject):
    """Whether a required artifact re-hashed to its expected fingerprint."""

    artifact_id: Sha256
    passed: bool


class ReviewEvidence(ValueObject):
    """One required evidence key bound to exact content-addressed bytes."""

    requirement_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    artifact_id: Sha256


def _graph_has_cycle(edges: dict[str, str | None]) -> bool:
    """Return whether the ``id -> supersedes`` edge map contains a cycle."""

    # 0 = on the current path (being visited), 1 = fully explored.
    color: dict[str, int] = {}

    def _visit(node: str) -> bool:
        marker = color.get(node)
        if marker == 0:
            return True  # back-edge: a cycle
        if marker == 1:
            return False
        color[node] = 0
        nxt = edges.get(node)
        if nxt is not None and nxt in edges and _visit(nxt):
            return True
        color[node] = 1
        return False

    return any(_visit(node) for node in edges)


class ReviewDecision(RecordBase):
    """A human review decision bound to a target and dependency fingerprint."""

    record_kind: Literal["review_decision"] = "review_decision"

    # The actor is always a human: review authority is never delegated to agents.
    actor: Literal["human"] = "human"
    decision: DecisionType
    target_ref: str
    target_range: tuple[float, float] | None = None
    rationale: str
    dependency_fingerprint: Sha256
    acceptance_spec_id: Sha256 | None = None
    review_role: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$",
    )
    evidence_artifacts: tuple[ReviewEvidence, ...] = ()
    covered_requirement_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_target_range(self) -> ReviewDecision:
        """Only a ``trim`` decision may carry a range, and it must be bounded.

        A ``trim`` requires a positive, nonnegative ``target_range``; every other
        decision type must leave it unset — a range on an ``approve`` is a silent
        contradiction.
        """

        if self.decision is DecisionType.TRIM:
            if self.target_range is None:
                raise ValueError("a trim decision requires a target_range")
            start, end = self.target_range
            if start < 0.0 or end <= start:
                raise ValueError("target_range must be a positive, nonnegative range")
        elif self.decision is DecisionType.APPROVE and self.target_range is not None:
            start, end = self.target_range
            if start < 0.0 or end <= start:
                raise ValueError("target_range must be a positive, nonnegative range")
        elif self.target_range is not None:
            raise ValueError(f"{self.decision.value!r} must not carry a target_range")
        if len(set(self.covered_requirement_ids)) != len(self.covered_requirement_ids):
            raise ValueError("covered_requirement_ids must not contain duplicates")
        evidence_keys = [item.requirement_id for item in self.evidence_artifacts]
        if len(set(evidence_keys)) != len(evidence_keys):
            raise ValueError("evidence_artifacts must not repeat a requirement_id")
        return self


class KnownLimitation(RecordBase):
    """An accepted limitation carried forward with its authorizing decision."""

    record_kind: Literal["known_limitation"] = "known_limitation"

    summary: str
    related_defect_ids: tuple[Sha256, ...] = ()
    accepted_by_decision_id: Sha256


class ApprovalState(RecordBase):
    """The approval posture of a candidate artifact (design §4.9).

    ``publishable`` is intentionally not a stored field: it is derived by
    :meth:`is_publishable` from the current state, integrity results, required
    human decisions, and any unresolved blocking findings.
    """

    record_kind: Literal["approval_state"] = "approval_state"

    candidate_artifact: Sha256
    dependency_fingerprint: Sha256
    required_artifact_ids: tuple[Sha256, ...] = ()
    integrity_results: tuple[IntegrityResult, ...] = ()
    required_human_decisions: tuple[Sha256, ...] = ()
    state: ApprovalStateValue = ApprovalStateValue.PENDING
    invalidation_reasons: tuple[str, ...] = ()
    superseding_state_id: Sha256 | None = None

    def is_publishable(
        self,
        resolved_decisions: Iterable[ReviewDecision],
        resolved_approval_states: Iterable[ApprovalState],
        *,
        blocking_findings: tuple[Sha256, ...],
    ) -> bool:
        """Derive publishability from resolved review evidence (design §4.9).

        Never a stored boolean, and never a *trusted* one: instead of a caller
        ``superseded`` flag, the full ``resolved_approval_states`` history is
        consumed and supersession is *derived* — any valid newer state that
        supersedes this one blocks publishing, and an untrusted history (a
        forged, duplicate, or wrong-subclass state) fails closed. ``blocking_findings``
        (the caller's complete set of unresolved blocking findings) is required.
        Publishing also requires: the state is ``approved`` with no invalidation
        reasons; the candidate and every required artifact re-hashed to their
        expected fingerprint with no conflicting result; and every required human
        decision is a fresh, human ``approve`` bound to this candidate.
        """

        if type(self) is not ApprovalState:
            return False  # a subclass "lookalike" state never publishes
        if self.record_id is not None and self.record_id != canonical_record_id(self):
            return False  # a forged supplied self id never publishes
        if self.state is not ApprovalStateValue.APPROVED:
            return False
        if self.superseding_state_id is not None or self._is_superseded_by(resolved_approval_states):
            return False  # a superseded approval never publishes
        if blocking_findings or self.invalidation_reasons:
            return False
        if not self.required_artifact_ids or not self.required_human_decisions:
            return False
        if not self._integrity_verified():
            return False
        return self._decisions_satisfied(resolved_decisions)

    def _is_superseded_by(self, resolved_approval_states: Iterable[ApprovalState]) -> bool:
        """Derive supersession from the approval history, failing closed on doubt.

        The history must be a *complete, valid* supersession graph. Each state's
        identity is recomputed (a supplied ``record_id`` is never trusted); a
        wrong-subclass, forged, duplicate, dangling (``supersedes`` pointing
        outside the known graph), or cyclic history makes the whole history
        untrusted and returns ``True``. Otherwise, any state whose ``supersedes``
        points at this state's canonical id supersedes it.
        """

        self_id = canonical_record_id(self)
        edges: dict[str, str | None] = {}
        for state in resolved_approval_states:
            if type(state) is not ApprovalState:
                return True  # foreign / subclass object: untrusted history
            state_id = canonical_record_id(state)
            if state.record_id is not None and state.record_id != state_id:
                return True  # forged supplied id
            if state_id in edges:
                return True  # duplicate state
            edges[state_id] = state.supersedes
        known = set(edges) | {self_id}
        if any(target is not None and target not in known for target in edges.values()):
            return True  # dangling supersedes edge
        if _graph_has_cycle(edges):
            return True
        return any(target == self_id for target in edges.values())

    def _integrity_verified(self) -> bool:
        """Candidate and every required artifact passed with no failed result."""

        passed: set[str] = set()
        failed: set[str] = set()
        for result in self.integrity_results:
            (passed if result.passed else failed).add(result.artifact_id)
        required = set(self.required_artifact_ids) | {self.candidate_artifact}
        if required & failed:  # any required/candidate artifact has a failed result
            return False
        return required.issubset(passed)

    def _decisions_satisfied(self, resolved_decisions: Iterable[ReviewDecision]) -> bool:
        """Each required decision is a human ``approve`` bound to this candidate.

        The resolved set is materialized and fully validated: a wrong-subclass,
        forged (supplied id ≠ recomputed), or duplicated decision makes the whole
        set untrusted. Identity is always recomputed. Every required id (which
        must itself be duplicate-free) must map to an ``approve`` with human
        provenance, bound to the current dependency fingerprint, targeting the
        exact candidate. Finally, any *current* reject/repair/regenerate for this
        candidate+fingerprint blocks publishing outright.
        """

        required = list(self.required_human_decisions)
        required_set = set(required)
        if len(required_set) != len(required):
            return False  # duplicate required decision ids
        by_id = self._index_decisions(resolved_decisions)
        if by_id is None:
            return False  # untrusted resolved set (subclass / forged / duplicate)
        if any(decision.supersedes in required_set for decision in by_id.values()):
            return False  # a required decision was superseded by a later one (any type)
        for required_id in required:
            decision = by_id.get(required_id)
            if decision is None or decision.decision is not DecisionType.APPROVE:
                return False
            if decision.actor != "human" or not decision.created_by.startswith("human"):
                return False  # provenance: only a human decision publishes
            if decision.dependency_fingerprint != self.dependency_fingerprint:
                return False  # stale: made against a different dependency fingerprint
            if decision.target_ref != self.candidate_artifact:
                return False  # wrong target: approves a different artifact
        return not self._has_current_negative(by_id.values())

    def _index_decisions(self, resolved_decisions: Iterable[ReviewDecision]) -> dict[str, ReviewDecision] | None:
        """Recompute and index decisions by canonical id; ``None`` if untrusted."""

        by_id: dict[str, ReviewDecision] = {}
        for decision in resolved_decisions:
            if type(decision) is not ReviewDecision:
                return None  # subclass / foreign object
            canonical = canonical_record_id(decision)
            if decision.record_id is not None and decision.record_id != canonical:
                return None  # forged supplied id
            if canonical in by_id:
                return None  # duplicate decision
            by_id[canonical] = decision
        return by_id

    def _has_current_negative(self, decisions: Iterable[ReviewDecision]) -> bool:
        """True if a current reject/repair/regenerate targets this candidate state."""

        negatives = {DecisionType.REJECT, DecisionType.REPAIR, DecisionType.REGENERATE}
        for decision in decisions:
            if (
                decision.decision in negatives
                and decision.target_ref == self.candidate_artifact
                and decision.dependency_fingerprint == self.dependency_fingerprint
            ):
                return True
        return False
