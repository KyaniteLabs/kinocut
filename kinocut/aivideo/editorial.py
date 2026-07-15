"""Editorial planning engines: beat map writer/query (#42).

A beat map is canonical, append-only state bound to one acceptance spec. The
writer rejects a map whose acceptance spec is absent (dangling reference); the
query returns active (non-superseded) maps for a spec.
"""

from __future__ import annotations

from pydantic import Field

from kinocut.contracts._common import ValueObject
from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.editorial import BeatMap, ContinuityPlan
from kinocut.contracts.registry import ClipRecord
from kinocut.projectstore import Project, append_record, read_records


def _active(project: Project, kind: str, model: type) -> list[object]:
    rows = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def _spec_exists(project: Project, spec_id: str) -> bool:
    rows = read_records(project, "generation_acceptance_spec")
    return any(type(item) is GenerationAcceptanceSpec and item.record_id == spec_id for item in rows)


def record_beat_map(project: Project, beat_map: BeatMap) -> BeatMap:
    """Persist one beat map, rejecting a dangling acceptance-spec reference."""

    if not _spec_exists(project, beat_map.acceptance_spec_id):
        raise contract_error("beat map references no acceptance spec", INVALID_RECORD)
    return append_record(project, beat_map)  # type: ignore[return-value]


def beat_maps_for_spec(project: Project, spec_id: str) -> list[BeatMap]:
    """Return active beat maps bound to ``spec_id``."""

    return [item for item in _active(project, "beat_map", BeatMap) if item.acceptance_spec_id == spec_id]  # type: ignore[return-value]


def record_continuity_plan(project: Project, plan: ContinuityPlan) -> ContinuityPlan:
    """Persist one continuity plan, rejecting a dangling acceptance-spec reference."""

    if not _spec_exists(project, plan.acceptance_spec_id):
        raise contract_error("continuity plan references no acceptance spec", INVALID_RECORD)
    return append_record(project, plan)  # type: ignore[return-value]


def continuity_plans_for_spec(project: Project, spec_id: str) -> list[ContinuityPlan]:
    """Return active continuity plans bound to ``spec_id``."""

    return [item for item in _active(project, "continuity_plan", ContinuityPlan) if item.acceptance_spec_id == spec_id]  # type: ignore[return-value]


class BeatCoverage(ValueObject):
    """One beat's coverage state against approved clip material (#43)."""

    beat_id: str
    label: str
    covered: bool
    missing_subjects: tuple[str, ...] = ()


class CoverageReport(ValueObject):
    """Deterministic coverage projection: beats vs approved clip subjects (#43)."""

    acceptance_spec_id: str
    total_beats: int = Field(ge=0)
    covered_count: int = Field(ge=0)
    approved_clip_count: int = Field(ge=0)
    beats: tuple[BeatCoverage, ...] = ()


def _approved_clip_subjects(project: Project) -> tuple[frozenset[str], int]:
    clips = [item for item in read_records(project, "clip_record") if type(item) is ClipRecord]
    superseded = {item.supersedes for item in clips if item.supersedes is not None}
    active = [item for item in clips if item.record_id not in superseded]
    tags: set[str] = set()
    for clip in active:
        tags.update(clip.tags)
    return frozenset(tags), len(active)


def coverage_report(project: Project, spec_id: str) -> CoverageReport:
    """Project each beat of the active beat map against approved clip subjects.

    A beat is covered when every ``required_subject`` is present in the union of
    approved clip tags. Read-only; never a source of truth.
    """

    maps = beat_maps_for_spec(project, spec_id)
    beat_map = maps[-1] if maps else None
    available, clip_count = _approved_clip_subjects(project)
    if beat_map is None:
        return CoverageReport(
            acceptance_spec_id=spec_id,
            total_beats=0,
            covered_count=0,
            approved_clip_count=clip_count,
            beats=(),
        )
    rows: list[BeatCoverage] = []
    covered = 0
    for beat in beat_map.beats:
        missing = tuple(s for s in beat.required_subjects if s not in available)
        is_covered = not missing
        covered += int(is_covered)
        rows.append(
            BeatCoverage(
                beat_id=beat.beat_id,
                label=beat.label,
                covered=is_covered,
                missing_subjects=missing,
            )
        )
    return CoverageReport(
        acceptance_spec_id=spec_id,
        total_beats=len(rows),
        covered_count=covered,
        approved_clip_count=clip_count,
        beats=tuple(rows),
    )


class ContinuityFinding(ValueObject):
    """One shot's continuity status against approved clip material (#19)."""

    shot_id: str
    status: str  # satisfied | incomplete | violation
    unmet_subjects: tuple[str, ...] = ()
    violated_forbiddens: tuple[str, ...] = ()


class ContinuityReport(ValueObject):
    """Deterministic continuity findings; optional VLM enrichment is fail-soft."""

    acceptance_spec_id: str
    findings: tuple[ContinuityFinding, ...] = ()
    optional_provider_status: str = "provider_not_configured"


def continuity_assistant(project: Project, spec_id: str) -> ContinuityReport:
    """Compare the active continuity plan against approved clip material (#19).

    Core deterministic check over tags: each expectation is ``satisfied`` when
    its expected subjects are present and no forbidden change appears in approved
    clips, ``incomplete`` when an expected subject is missing, or ``violation``
    when a forbidden change is present. Optional VLM/embedding enrichment is
    capability-gated and returns ``provider_not_configured`` deterministically.
    """

    plans = continuity_plans_for_spec(project, spec_id)
    plan = plans[-1] if plans else None
    available, _ = _approved_clip_subjects(project)
    findings: list[ContinuityFinding] = []
    if plan is not None:
        for expectation in plan.expectations:
            unmet = tuple(s for s in expectation.expected_subjects if s not in available)
            violated = tuple(c for c in expectation.forbidden_changes if c in available)
            if violated:
                status = "violation"
            elif unmet:
                status = "incomplete"
            else:
                status = "satisfied"
            findings.append(
                ContinuityFinding(
                    shot_id=expectation.shot_id,
                    status=status,
                    unmet_subjects=unmet,
                    violated_forbiddens=violated,
                )
            )
    return ContinuityReport(acceptance_spec_id=spec_id, findings=tuple(findings))


__all__ = [
    "BeatCoverage",
    "ContinuityFinding",
    "ContinuityReport",
    "CoverageReport",
    "beat_maps_for_spec",
    "continuity_assistant",
    "continuity_plans_for_spec",
    "coverage_report",
    "record_beat_map",
    "record_continuity_plan",
]
