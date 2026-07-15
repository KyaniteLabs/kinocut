"""Regeneration advice and defect-to-prompt feedback (#44, #58, A7).

Both are rule-based and evidence-first: they read canonical records (prompt
outcomes #40, cost #60, defects #6, verdicts) and never invent data. Estimates
and recommendations are explicitly labeled ``rule_based`` so a caller never
mistakes them for model output. Model-worded enrichment would be optional and
fail-soft; these functions are the deterministic core that always works.
"""

from __future__ import annotations

from pydantic import Field

from kinocut.aivideo.learning.cost import cost_totals
from kinocut.contracts._common import ValueObject
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.learning import PromptOutcome
from kinocut.contracts.verdict import ClipVerdict, Disposition
from kinocut.projectstore import Project, read_records

_REGENERATE_DISPOSITIONS = frozenset({Disposition.REJECTED, Disposition.REGENERATE})


def _active(project: Project, kind: str, model: type) -> list[object]:
    rows = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


class RegenerationAdvice(ValueObject):
    """Rule-based regeneration recommendation for one verdict (#44)."""

    verdict_id: str
    recommend_regenerate: bool
    basis: str = "rule_based"
    rationale: str
    prior_approved_outcome: bool
    cost_estimate_known: bool


def regeneration_advice(project: Project, verdict_id: str) -> RegenerationAdvice | None:
    """Advise whether to regenerate the clip behind ``verdict_id`` (#44).

    Rule: recommend regeneration when the verdict is rejected/regenerate AND no
    prior prompt outcome for this verdict was approved. Cost is reported as
    known/unknown explicitly (never inferred as zero). Returns None if the
    verdict is absent.
    """

    verdict = next(
        (item for item in _active(project, "clip_verdict", ClipVerdict) if item.record_id == verdict_id),
        None,
    )
    if verdict is None:
        return None
    outcomes = [item for item in _active(project, "prompt_outcome", PromptOutcome) if verdict_id in item.verdict_ids]
    prior_approved = any(
        linked is not verdict and linked.disposition not in _REGENERATE_DISPOSITIONS
        for outcome in outcomes
        for linked in _active(project, "clip_verdict", ClipVerdict)
        if linked.record_id in outcome.verdict_ids
    )
    cost_known = cost_totals(project).known_event_count > 0
    rejected = verdict.disposition in _REGENERATE_DISPOSITIONS
    recommend = rejected and not prior_approved
    rationale = (
        "verdict is rejected or regenerate with no prior approved outcome for this prompt"
        if recommend
        else "prior approved outcome exists or verdict is not a regenerate disposition"
    )
    return RegenerationAdvice(
        verdict_id=verdict_id,
        recommend_regenerate=recommend,
        rationale=rationale,
        prior_approved_outcome=prior_approved,
        cost_estimate_known=cost_known,
    )


class PromptDefectFeedback(ValueObject):
    """Defects observed for one prompt, rule-aggregated from linked outcomes (#58)."""

    prompt_hash: str
    defect_codes: tuple[str, ...] = ()
    defect_count: int = Field(ge=0)


def defect_prompt_feedback(project: Project) -> list[PromptDefectFeedback]:
    """Aggregate the defect codes linked to each prompt via prompt outcomes (#58).

    Deterministic projection: for each prompt outcome, collect the defect codes
    of its linked defects. Only prompts with at least one linked defect are
    returned. Never invents a recommendation beyond the observed codes.
    """

    outcomes = _active(project, "prompt_outcome", PromptOutcome)
    defects = {item.record_id: item for item in _active(project, "defect_finding", DefectFinding)}
    by_prompt: dict[str, set[str]] = {}
    for outcome in outcomes:
        codes = {
            defects[did].defect_code.value if hasattr(defects[did].defect_code, "value") else str(defects[did].defect_code)
            for did in outcome.defect_ids
            if did in defects
        }
        if codes:
            by_prompt.setdefault(outcome.prompt_hash, set()).update(codes)
    return [
        PromptDefectFeedback(
            prompt_hash=prompt_hash,
            defect_codes=tuple(sorted(codes)),
            defect_count=len(codes),
        )
        for prompt_hash, codes in sorted(by_prompt.items())
    ]


__all__ = [
    "PromptDefectFeedback",
    "RegenerationAdvice",
    "defect_prompt_feedback",
    "regeneration_advice",
]
