"""Human review mutation for persisted shorts plans.

Append-only decision recording and fail-closed approval resolution.
No FFmpeg, network, or posting side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import MCPVideoError
from .models import CandidateMoment, canonical_dedup_key
from .shorts_plan import ReviewDecision, ShortsPlan, load_shorts_plan, save_shorts_plan


__all__ = [
    "resolve_approved_candidate",
    "review_shorts_plan",
]


def _review_error(problem: str, *, code: str, cause: str, recovery: str) -> MCPVideoError:
    return MCPVideoError(
        f"Problem: {problem} Likely cause: {cause} Recovery: {recovery}",
        error_type="validation_error",
        code=code,
        suggested_action={"auto_fix": False, "description": recovery},
    )


def _coerce_decision(
    *,
    candidate_id: str,
    decision: ReviewDecision | Mapping[str, Any] | str,
    evidence_ref: str | None,
) -> ReviewDecision:
    if isinstance(decision, ReviewDecision):
        if decision.candidate_id != candidate_id:
            raise _review_error(
                "The review decision targets the wrong candidate.",
                code="shorts_review_invalid",
                cause=(
                    f"decision.candidate_id={decision.candidate_id!r} does not match candidate_id={candidate_id!r}."
                ),
                recovery="Pass a decision whose candidate_id matches the candidate under review.",
            )
        if evidence_ref is not None and decision.evidence_ref is None:
            return decision.model_copy(update={"evidence_ref": evidence_ref})
        return decision

    if isinstance(decision, str):
        payload: dict[str, Any] = {"action": decision}
    elif isinstance(decision, Mapping):
        payload = dict(decision)
    else:
        raise _review_error(
            "The review decision payload is not valid.",
            code="shorts_review_invalid",
            cause=f"got {type(decision).__name__!r}.",
            recovery="Pass a ReviewDecision, action string, or decision mapping.",
        )

    if "candidate_id" in payload and payload["candidate_id"] != candidate_id:
        raise _review_error(
            "The review decision targets the wrong candidate.",
            code="shorts_review_invalid",
            cause=(f"decision.candidate_id={payload['candidate_id']!r} does not match candidate_id={candidate_id!r}."),
            recovery="Pass a decision whose candidate_id matches the candidate under review.",
        )
    payload["candidate_id"] = candidate_id
    if evidence_ref is not None and payload.get("evidence_ref") is None:
        payload["evidence_ref"] = evidence_ref

    try:
        return ReviewDecision.model_validate(payload)
    except Exception as exc:
        raise _review_error(
            "The review decision failed strict validation.",
            code="shorts_review_invalid",
            cause=str(exc).splitlines()[0] if str(exc) else "validation failure",
            recovery=(
                "Use preview, approve, reject, trim, title_hook_edit, or "
                "sensitive_unsuitable with fields matching the action shape."
            ),
        ) from exc


def review_shorts_plan(
    plan_path_or_dir: str,
    *,
    candidate_id: str,
    decision: ReviewDecision | Mapping[str, Any] | str,
    evidence_ref: str | None = None,
) -> ShortsPlan:
    """Append one human decision and persist the revised plan.

    Status becomes ``reviewed`` after any decision is recorded. Rendering
    still requires a current ``approve`` decision via
    :func:`resolve_approved_candidate`.
    """
    if not isinstance(candidate_id, str) or not candidate_id:
        raise _review_error(
            "A candidate id is required.",
            code="shorts_candidate_not_found",
            cause="candidate_id was empty.",
            recovery="Pass a candidate_id from the saved plan proposals.",
        )

    plan = load_shorts_plan(plan_path_or_dir)
    if not any(item.candidate_id == candidate_id for item in plan.proposals):
        raise _review_error(
            "The candidate does not exist.",
            code="shorts_candidate_not_found",
            cause=f"{candidate_id!r} is not in the saved proposal set.",
            recovery="Use a candidate id from the plan proposals.",
        )

    record = _coerce_decision(candidate_id=candidate_id, decision=decision, evidence_ref=evidence_ref)
    revised = plan.model_copy(
        update={
            "decisions": (*plan.decisions, record),
            "status": "reviewed",
        }
    )
    return save_shorts_plan(revised)


def resolve_approved_candidate(plan: ShortsPlan, candidate_id: str) -> CandidateMoment:
    """Apply the decision stack and return the approved effective candidate.

    Fail closed when there is no current approve, or when the candidate is
    marked unsuitable. ``trim`` / ``title_hook_edit`` / sensitivity decisions
    mutate the effective bounds and metadata; a later ``reject`` clears
    approval.
    """
    if not isinstance(plan, ShortsPlan):
        raise _review_error(
            "resolve_approved_candidate requires a strict ShortsPlan.",
            code="invalid_plan",
            cause=f"got {type(plan).__name__!r}.",
            recovery="Load the plan with load_shorts_plan(...) first.",
        )

    candidate = next((item for item in plan.proposals if item.candidate_id == candidate_id), None)
    if candidate is None:
        raise _review_error(
            "The candidate does not exist.",
            code="shorts_candidate_not_found",
            cause=f"{candidate_id!r} is not in the plan proposals.",
            recovery="Choose a candidate from the proposal output.",
        )

    updates: dict[str, Any] = {}
    approved = False
    for decision in plan.decisions:
        if decision.candidate_id != candidate_id:
            continue
        if decision.action == "reject":
            approved = False
        elif decision.action == "approve":
            approved = True
        elif decision.action == "preview":
            continue
        elif decision.action == "trim":
            if decision.start is None or decision.end is None:
                raise _review_error(
                    "A trim decision is missing bounds.",
                    code="shorts_review_invalid",
                    cause="trim requires start and end.",
                    recovery="Record trim with 0 <= start < end.",
                )
            updates["start"] = decision.start
            updates["end"] = decision.end
        elif decision.action == "title_hook_edit":
            if decision.title is not None:
                updates["suggested_title"] = decision.title
            if decision.hook is not None:
                updates["suggested_hook"] = decision.hook
        elif decision.action == "sensitive_unsuitable":
            if decision.unsuitable is True:
                updates["unsuitable"] = True
                updates["sensitivity"] = "unsafe"
            if decision.sensitive is True and "sensitivity" not in updates:
                updates["sensitivity"] = "sensitive"
            if decision.unsuitable is False:
                updates["unsuitable"] = False
                if updates.get("sensitivity") == "unsafe":
                    updates["sensitivity"] = "none"

    # Recompute dedup_key whenever bounds or sensitivity change so the
    # CandidateMoment invariant remains satisfied.
    start = float(updates.get("start", candidate.start))
    end = float(updates.get("end", candidate.end))
    sensitivity = str(updates.get("sensitivity", candidate.sensitivity))
    if "start" in updates or "end" in updates or "sensitivity" in updates:
        updates["dedup_key"] = canonical_dedup_key(
            start=start,
            end=end,
            excerpt=candidate.transcript_excerpt,
            sensitivity=sensitivity,  # type: ignore[arg-type]
        )

    effective = candidate.model_copy(update=updates) if updates else candidate

    if not approved:
        raise _review_error(
            "The candidate is not approved for rendering.",
            code="shorts_review_required",
            cause="No current human approval exists.",
            recovery="Record an approve decision after reviewing the candidate.",
        )
    if effective.unsuitable:
        raise _review_error(
            "The candidate is marked unsuitable.",
            code="shorts_candidate_unsuitable",
            cause="Human review flagged sensitive material.",
            recovery="Choose another candidate or record a deliberate revised review decision.",
        )
    return effective
