"""Governed editorial verdict, defect, and acceptance workflows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import cast

from kinocut.contracts._common import ValueObject, canonical_record_id
from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.acceptance import (
    GenerationAcceptanceSpec,
    acceptance_requirement_ids,
)
from kinocut.contracts.defect import DefectFinding, DefectStatus
from kinocut.contracts.review import DecisionType, ReviewDecision
from kinocut.contracts.verdict import ClipVerdict, Disposition
from kinocut.limits import MAX_ACCEPTANCE_EVIDENCE_FILES
from kinocut.projectstore import Project, append_record, read_records
from kinocut.projectstore import layout, store
from kinocut.validation import DEFECT_SEVERITY_RANK

_ACCEPTED_DISPOSITIONS = frozenset({Disposition.APPROVED, Disposition.APPROVED_WITH_TRIM})
_NON_BLOCKING_DEFECT_STATUSES = frozenset({DefectStatus.RESOLVED, DefectStatus.FALSE_POSITIVE})
_HASH_CHUNK_BYTES = 1 << 20


class AcceptanceReport(ValueObject):
    """Derived acceptance result; never a mutable stored approval boolean."""

    accepted: bool
    unmet_required: tuple[str, ...] = ()
    forbidden_defect_ids: tuple[str, ...] = ()
    threshold_violation_ids: tuple[str, ...] = ()
    missing_defect_ids: tuple[str, ...] = ()
    foreign_defect_ids: tuple[str, ...] = ()
    missing_approval: bool = False
    missing_review_roles: tuple[str, ...] = ()
    missing_evidence_artifacts: tuple[str, ...] = ()
    invalid_evidence_artifact_ids: tuple[str, ...] = ()
    conflicting_evidence_requirements: tuple[str, ...] = ()
    conflicting_verdict_ids: tuple[str, ...] = ()


def _typed_records(project: Project, kind: str, model: type):
    """Return exact registered records, excluding superseded history."""

    records = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in records if item.supersedes is not None}
    return [item for item in records if item.record_id not in superseded]


def record_verdict(project: Project, verdict: ClipVerdict) -> ClipVerdict:
    """Persist one exact-hash editorial verdict in the canonical project store."""

    if verdict.disposition in _ACCEPTED_DISPOSITIONS:
        specs = [
            item
            for item in _typed_records(project, "generation_acceptance_spec", GenerationAcceptanceSpec)
            if item.record_id == verdict.acceptance_spec_id
        ]
        if len(specs) != 1 or approval_decision(project, specs[0], verdict) is None:
            raise contract_error("approved verdict requires exact active human evidence", INVALID_RECORD)
    return cast(ClipVerdict, append_record(project, verdict))


def approved_clips(project: Project) -> list[ClipVerdict]:
    """Return active verdicts eligible for the approved-only clip search."""

    specs = {
        item.record_id: item for item in _typed_records(project, "generation_acceptance_spec", GenerationAcceptanceSpec)
    }
    return [
        verdict
        for verdict in _typed_records(project, "clip_verdict", ClipVerdict)
        if verdict.disposition in _ACCEPTED_DISPOSITIONS
        and verdict.acceptance_spec_id in specs
        and approval_decision(project, specs[verdict.acceptance_spec_id], verdict) is not None
    ]


def acceptance_dependency_fingerprint(
    asset_hash: str,
    acceptance_spec_id: str,
    approved_range: tuple[float, float] | None,
) -> str:
    """Bind one human approval to its exact candidate, spec, and trim range."""

    payload = json.dumps(
        {
            "acceptance_spec_id": acceptance_spec_id,
            "approved_range": approved_range,
            "asset_hash": asset_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def approval_decision(
    project: Project,
    spec: GenerationAcceptanceSpec,
    verdict: ClipVerdict,
) -> ReviewDecision | None:
    """Resolve a verdict's exact, active, same-project human approval."""

    if verdict.review_decision_id is None:
        return None
    matches = [
        item
        for item in _typed_records(project, "review_decision", ReviewDecision)
        if item.record_id == verdict.review_decision_id
    ]
    if len(matches) != 1:
        return None
    decision = matches[0]
    spec_id = canonical_record_id(spec)
    required_range = verdict.approved_range if verdict.disposition is Disposition.APPROVED_WITH_TRIM else None
    expected_fingerprint = acceptance_dependency_fingerprint(
        verdict.asset_hash, verdict.acceptance_spec_id, required_range
    )
    if not (
        decision.project_id == project.project_id == spec.project_id == verdict.project_id
        and decision.actor == "human"
        and decision.created_by.startswith("human")
        and decision.decision is DecisionType.APPROVE
        and decision.target_ref == verdict.asset_hash
        and decision.target_range == required_range
        and decision.acceptance_spec_id == verdict.acceptance_spec_id == spec_id
        and decision.dependency_fingerprint == expected_fingerprint
        and decision.review_role is not None
    ):
        return None
    if spec.required_review_roles and decision.review_role not in spec.required_review_roles:
        return None
    allowed_requirements = set(acceptance_requirement_ids(spec))
    if not set(decision.covered_requirement_ids) <= allowed_requirements:
        return None
    allowed_evidence = set(spec.required_evidence_artifacts)
    if not {item.requirement_id for item in decision.evidence_artifacts} <= allowed_evidence:
        return None
    return decision


def _artifact_is_valid(project: Project, artifact_id: str) -> bool:
    """Independently hash one referenced private artifact; ambiguity fails closed."""

    digest = artifact_id.removeprefix("sha256:")
    directory = store.safe_target(project, layout.artifacts_dir() / PurePosixPath(digest))
    try:
        found = False
        for count, entry in enumerate(directory.iterdir(), start=1):
            if count > MAX_ACCEPTANCE_EVIDENCE_FILES:
                return False
            if not entry.is_file() or entry.is_symlink():
                continue
            found = True
            hasher = hashlib.sha256()
            with entry.open("rb") as handle:
                while chunk := handle.read(_HASH_CHUNK_BYTES):
                    hasher.update(chunk)
            actual = "sha256:" + hasher.hexdigest()
            if actual == artifact_id:
                return True
        if not found:
            return False
    except OSError:
        return False
    return False


def record_defect(project: Project, finding: DefectFinding) -> DefectFinding:
    """Persist one governed defect finding in the canonical project store."""

    return cast(DefectFinding, append_record(project, finding))


def defects_for_asset(project: Project, target_id: str) -> list[DefectFinding]:
    """Return active findings bound to one exact asset or artifact digest."""

    return [
        finding
        for finding in _typed_records(project, "defect_finding", DefectFinding)
        if finding.target_id == target_id
    ]


def _required_items(spec: GenerationAcceptanceSpec) -> tuple[str, ...]:
    """Flatten human-readable acceptance requirements without exposing text."""

    return acceptance_requirement_ids(spec)


def _matching_verdicts(spec: GenerationAcceptanceSpec, verdicts: Iterable[ClipVerdict]) -> tuple[ClipVerdict, ...]:
    """Select exact-spec verdicts while refusing subclass lookalikes."""

    spec_id = canonical_record_id(spec)
    return tuple(
        verdict for verdict in verdicts if type(verdict) is ClipVerdict and verdict.acceptance_spec_id == spec_id
    )


def _acceptance_findings(
    project: Project, verdicts: tuple[ClipVerdict, ...]
) -> tuple[tuple[DefectFinding, ...], tuple[str, ...], tuple[str, ...]]:
    """Union same-asset findings and legitimate refs; reject foreign refs."""

    assets = {verdict.asset_hash for verdict in verdicts}
    wanted = {finding_id for verdict in verdicts for finding_id in verdict.defect_ids}
    active = _typed_records(project, "defect_finding", DefectFinding)
    by_id = {finding.record_id: finding for finding in active}
    missing = tuple(sorted(wanted - by_id.keys()))
    foreign = tuple(
        sorted(
            {
                finding_id
                for verdict in verdicts
                for finding_id in verdict.defect_ids
                if finding_id in by_id and by_id[finding_id].target_id != verdict.asset_hash
            }
        )
    )
    legitimate_ids = {finding.record_id for finding in active if finding.target_id in assets}
    legitimate_ids.update(wanted - set(foreign))
    findings = tuple(by_id[item] for item in sorted(legitimate_ids) if item in by_id)
    return findings, missing, foreign


def _blocking_defects(
    spec: GenerationAcceptanceSpec, findings: tuple[DefectFinding, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return forbidden-code and above-threshold finding identities."""

    active = [finding for finding in findings if finding.status not in _NON_BLOCKING_DEFECT_STATUSES]
    forbidden_codes = set(spec.forbidden_defect_codes)
    forbidden = tuple(finding.record_id for finding in active if finding.defect_code in forbidden_codes)
    ceilings = {item.defect_code: item.max_severity for item in spec.severity_thresholds}
    threshold = tuple(
        finding.record_id
        for finding in active
        if finding.defect_code in ceilings
        and DEFECT_SEVERITY_RANK[finding.severity.value] > DEFECT_SEVERITY_RANK[ceilings[finding.defect_code].value]
    )
    return forbidden, threshold


def acceptance_eval(
    project: Project,
    *,
    spec: GenerationAcceptanceSpec,
    verdicts: Iterable[ClipVerdict],
) -> AcceptanceReport:
    """Evaluate exact-spec verdicts and their governed defect evidence."""

    matching = _matching_verdicts(spec, verdicts)
    candidate_approved = tuple(verdict for verdict in matching if verdict.disposition in _ACCEPTED_DISPOSITIONS)
    pairs = tuple(
        (verdict, decision)
        for verdict in candidate_approved
        if (decision := approval_decision(project, spec, verdict)) is not None
    )
    accepted_verdicts = tuple(verdict for verdict, _ in pairs)
    decisions = tuple(decision for _, decision in pairs)
    covered = {item for decision in decisions for item in decision.covered_requirement_ids}
    unmet = tuple(item for item in _required_items(spec) if item not in covered)
    roles = {decision.review_role for decision in decisions}
    missing_roles = tuple(role for role in spec.required_review_roles if role not in roles)
    evidence_by_key: dict[str, set[str]] = {}
    for decision in decisions:
        for item in decision.evidence_artifacts:
            evidence_by_key.setdefault(item.requirement_id, set()).add(item.artifact_id)
    evidence_conflicts = tuple(sorted(key for key, artifact_ids in evidence_by_key.items() if len(artifact_ids) > 1))
    missing_evidence = tuple(item for item in spec.required_evidence_artifacts if item not in evidence_by_key)
    invalid_evidence = tuple(
        sorted(
            {
                artifact_id
                for artifact_ids in evidence_by_key.values()
                for artifact_id in artifact_ids
                if not _artifact_is_valid(project, artifact_id)
            }
        )
    )
    approved_assets = {item.asset_hash for item in accepted_verdicts}
    active_for_spec = [
        item
        for item in _typed_records(project, "clip_verdict", ClipVerdict)
        if item.acceptance_spec_id == canonical_record_id(spec) and item.asset_hash in approved_assets
    ]
    conflict_ids = tuple(
        sorted(item.record_id for item in active_for_spec if item.disposition not in _ACCEPTED_DISPOSITIONS)
    )
    if conflict_ids:
        conflict_ids = tuple(sorted({*conflict_ids, *(item.record_id for item in accepted_verdicts)}))
    missing_approval = not bool(accepted_verdicts)
    findings, missing, foreign = _acceptance_findings(project, accepted_verdicts)
    forbidden, threshold = _blocking_defects(spec, findings)
    accepted = not (
        missing_approval
        or unmet
        or missing_roles
        or missing_evidence
        or invalid_evidence
        or evidence_conflicts
        or conflict_ids
        or forbidden
        or threshold
        or missing
        or foreign
    )
    return AcceptanceReport(
        accepted=accepted,
        unmet_required=unmet,
        forbidden_defect_ids=forbidden,
        threshold_violation_ids=threshold,
        missing_defect_ids=missing,
        foreign_defect_ids=foreign,
        missing_approval=missing_approval,
        missing_review_roles=missing_roles,
        missing_evidence_artifacts=missing_evidence,
        invalid_evidence_artifact_ids=invalid_evidence,
        conflicting_evidence_requirements=evidence_conflicts,
        conflicting_verdict_ids=conflict_ids,
    )
