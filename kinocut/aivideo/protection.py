"""Fail-closed protected-element mutation precheck."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, cast

from pydantic import ValidationError, model_validator

from kinocut.contracts._common import Sha256, ValueObject
from kinocut.contracts._errors import PROTECTED_ELEMENT_CHANGE, contract_error
from kinocut.contracts.protection import ElementType, ProtectedElement
from kinocut.contracts.review import DecisionType, ReviewDecision
from kinocut.errors import MCPVideoError
from kinocut.projectstore import Project, append_record, read_records

_FORCE_KEYS = frozenset({"force", "override", "bypass"})


class MutationOperation(StrEnum):
    """Closed mutation set whose dependency footprint is engine-owned."""

    BODY_SWAP = "body_swap"
    REPLACE_SOURCE = "replace_source"
    NORMALIZE_AUDIO = "normalize_audio"
    TRIM_CLIP = "trim_clip"
    EDIT_TIMELINE = "edit_timeline"
    EDIT_GRAPHIC = "edit_graphic"
    EDIT_SUBTITLES = "edit_subtitles"
    RETIME = "retime"
    REMIX = "remix"
    CHANGE_RENDER_PARAMETERS = "change_render_parameters"
    SALVAGE_CLEAN_EDGES = "salvage_clean_edges"
    SALVAGE_FREEZE_EXTENSION = "salvage_freeze_extension"
    SALVAGE_STILL_FRAME = "salvage_still_frame"
    SALVAGE_REGION_CROP = "salvage_region_crop"
    SALVAGE_BACKGROUND_ONLY = "salvage_background_only"


_OPERATION_FOOTPRINTS: dict[
    MutationOperation,
    tuple[tuple[ElementType, str], ...],
] = {
    MutationOperation.BODY_SWAP: (
        (ElementType.SOURCE_ASSET, "source_asset"),
        (ElementType.AUDIO_STREAM, "audio_stream"),
    ),
    MutationOperation.REPLACE_SOURCE: ((ElementType.SOURCE_ASSET, "source_asset"),),
    MutationOperation.NORMALIZE_AUDIO: ((ElementType.AUDIO_STREAM, "audio_stream"),),
    MutationOperation.TRIM_CLIP: ((ElementType.CLIP_RANGE, "clip_range"),),
    MutationOperation.EDIT_TIMELINE: ((ElementType.TIMELINE_RANGE, "timeline_range"),),
    MutationOperation.EDIT_GRAPHIC: ((ElementType.GRAPHIC, "graphic"),),
    MutationOperation.EDIT_SUBTITLES: ((ElementType.SUBTITLE_SET, "subtitle_set"),),
    MutationOperation.RETIME: ((ElementType.TIMING_MAP, "timing_map"),),
    MutationOperation.REMIX: ((ElementType.MIX, "mix"),),
    MutationOperation.CHANGE_RENDER_PARAMETERS: ((ElementType.RENDER_PARAMETER_SET, "render_parameter_set"),),
    MutationOperation.SALVAGE_CLEAN_EDGES: (
        (ElementType.SOURCE_ASSET, "source_asset"),
        (ElementType.CLIP_RANGE, "clip_range"),
    ),
    MutationOperation.SALVAGE_FREEZE_EXTENSION: (
        (ElementType.SOURCE_ASSET, "source_asset"),
        (ElementType.TIMING_MAP, "timing_map"),
    ),
    MutationOperation.SALVAGE_STILL_FRAME: (
        (ElementType.SOURCE_ASSET, "source_asset"),
        (ElementType.CLIP_RANGE, "clip_range"),
    ),
    MutationOperation.SALVAGE_REGION_CROP: (
        (ElementType.SOURCE_ASSET, "source_asset"),
        (ElementType.RENDER_PARAMETER_SET, "render_parameter_set"),
    ),
    MutationOperation.SALVAGE_BACKGROUND_ONLY: (
        (ElementType.SOURCE_ASSET, "source_asset"),
        (ElementType.RENDER_PARAMETER_SET, "render_parameter_set"),
    ),
}
_DEPENDENCY_FIELDS = frozenset(field for footprint in _OPERATION_FOOTPRINTS.values() for _kind, field in footprint)


class MutationIntent(ValueObject):
    """Closed operation inputs from which the engine derives exact targets."""

    operation: MutationOperation
    source_asset: Sha256 | None = None
    audio_stream: Sha256 | None = None
    clip_range: Sha256 | None = None
    timeline_range: Sha256 | None = None
    graphic: Sha256 | None = None
    subtitle_set: Sha256 | None = None
    timing_map: Sha256 | None = None
    mix: Sha256 | None = None
    render_parameter_set: Sha256 | None = None
    authorization_decision_ids: tuple[Sha256, ...] = ()

    @model_validator(mode="after")
    def _has_exact_engine_footprint(self) -> MutationIntent:
        """Require exactly the named dependency fields owned by the operation."""

        required = {field for _kind, field in _OPERATION_FOOTPRINTS[self.operation]}
        populated = {field for field in _DEPENDENCY_FIELDS if getattr(self, field) is not None}
        if populated != required:
            raise ValueError("operation dependency footprint is incomplete or contradictory")
        return self


def _intent_payload(operation: Any) -> dict[str, Any]:
    """Extract the bounded public intent shape from a mapping or object."""

    if isinstance(operation, Mapping):
        if _FORCE_KEYS & operation.keys():
            raise _invalid_intent("mutation intent contains a forbidden bypass field")
        return dict(operation)
    if any(hasattr(operation, key) for key in _FORCE_KEYS):
        raise _invalid_intent("mutation intent contains a forbidden bypass field")
    payload = {
        "operation": getattr(operation, "operation", None),
        "authorization_decision_ids": getattr(operation, "authorization_decision_ids", ()),
    }
    payload.update({field: getattr(operation, field, None) for field in _DEPENDENCY_FIELDS})
    return payload


def _invalid_intent(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="invalid_mutation_intent")


def _coerce_intent(operation: Any) -> MutationIntent:
    if type(operation) is MutationIntent:
        return operation
    try:
        return MutationIntent.model_validate(_intent_payload(operation))
    except ValidationError as exc:
        raise _invalid_intent("mutation intent is invalid") from exc


def protect(project: Project, element: ProtectedElement) -> ProtectedElement:
    """Persist a human-authorized protected element in the project store."""

    return cast(ProtectedElement, append_record(project, element))


def touched_dependencies(operation: Any) -> set[tuple[ElementType, str]]:
    """Derive typed exact targets from the closed operation representation."""

    intent = _coerce_intent(operation)
    return {
        (kind, value)
        for kind, field in _OPERATION_FOOTPRINTS[intent.operation]
        if (value := getattr(intent, field)) is not None
    }


def _active_records(project: Project, kind: str, model: type) -> list[Any]:
    records = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in records if item.supersedes is not None}
    return [item for item in records if item.record_id not in superseded]


def _human_approval(decision: ReviewDecision | None, fingerprint: str) -> bool:
    """Whether a decision is an actual human approval for this dependency."""

    return bool(
        decision is not None
        and decision.created_by.startswith("human")
        and decision.decision is DecisionType.APPROVE
        and decision.dependency_fingerprint == fingerprint
    )


def _authorization_is_fresh(
    lock: ProtectedElement,
    original: ReviewDecision,
    decision: ReviewDecision,
) -> bool:
    """Require the new approval to explicitly derive from the lock or original."""

    lineage = set(decision.source_record_ids)
    return bool(
        decision.record_id != original.record_id
        and (decision.supersedes == original.record_id or original.record_id in lineage or lock.record_id in lineage)
    )


def _authorized(
    lock: ProtectedElement,
    intent: MutationIntent,
    all_decisions: dict[str, ReviewDecision],
    active_decision_ids: set[str],
) -> bool:
    """Resolve original and new human approvals and prove their relationship."""

    original = all_decisions.get(lock.human_approval_ref)
    if not _human_approval(original, lock.dependency_fingerprint):
        return False
    if original is None:  # narrowed by _human_approval; retained for type checkers
        return False
    if original.target_ref not in {lock.dependency_fingerprint, lock.record_id}:
        return False

    for decision_id in intent.authorization_decision_ids:
        decision = all_decisions.get(decision_id)
        if decision_id not in active_decision_ids:
            continue
        if not _human_approval(decision, lock.dependency_fingerprint):
            continue
        if decision is None:  # narrowed by _human_approval
            continue
        if decision.target_ref not in {lock.dependency_fingerprint, lock.record_id}:
            continue
        if _authorization_is_fresh(lock, original, decision):
            return True
    return False


def decision_history(project: Project) -> tuple[dict[str, ReviewDecision], set[str]]:
    """Return complete decision history plus the current unsuperseded IDs."""

    records = [item for item in read_records(project, "review_decision") if type(item) is ReviewDecision]
    superseded = {item.supersedes for item in records if item.supersedes is not None}
    by_id = {item.record_id: item for item in records}
    return by_id, set(by_id) - superseded


def assert_no_protected_collision(project: Project, operation: Any) -> None:
    """Reject every unallowed protected dependency touched by a mutation."""

    intent = _coerce_intent(operation)
    touched = touched_dependencies(intent)
    locks = _active_records(project, "protected_element", ProtectedElement)
    decisions, active_decision_ids = decision_history(project)
    for lock in locks:
        target = (lock.element_type, lock.dependency_fingerprint)
        if target not in touched:
            continue
        if intent.operation in lock.allowed_operations:
            continue
        if _authorized(lock, intent, decisions, active_decision_ids):
            continue
        raise contract_error(
            "mutation touches a protected element and requires a new human decision",
            PROTECTED_ELEMENT_CHANGE,
        )
