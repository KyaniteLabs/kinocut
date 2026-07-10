"""Versioned edit decision lists, timeline diffs, and pure verification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from itertools import pairwise
from typing import Any, Literal, Self, cast

from pydantic import Field, model_validator

from kinocut.errors import ValidationError as MCPValidationError

from .models import FrozenModel, SemanticTimeline, Sha256, SourceSpan, canonical_digest

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_EDIT_ID_PATTERN = r"^edit:[0-9a-f]{64}$"


class EditOperation(StrEnum):
    DELETE = "delete"
    RETAIN = "retain"
    REORDER = "reorder"
    SPEED = "speed"
    REPLACE = "replace"


class EditAction(FrozenModel):
    schema_version: Literal[1] = 1
    edit_id: str = Field(pattern=_EDIT_ID_PATTERN)
    edit_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    operation: EditOperation
    target_span_id: str
    source_start_seconds: float = Field(ge=0.0)
    source_end_seconds: float = Field(gt=0.0)
    rationale: str = Field(min_length=1)
    destination_index: int | None = Field(default=None, ge=0)
    speed: float | None = Field(default=None, gt=0.0)
    replacement_span_id: str | None = None
    replacement_start_seconds: float | None = Field(default=None, ge=0.0)
    replacement_end_seconds: float | None = Field(default=None, gt=0.0)

    @classmethod
    def create(
        cls,
        *,
        operation: EditOperation,
        target_span: SourceSpan,
        rationale: str,
        source_start_seconds: float | None = None,
        source_end_seconds: float | None = None,
        destination_index: int | None = None,
        speed: float | None = None,
        replacement_span: SourceSpan | None = None,
        replacement_start_seconds: float | None = None,
        replacement_end_seconds: float | None = None,
    ) -> Self:
        payload = {
            "operation": operation,
            "target_span_id": target_span.span_id,
            "source_start_seconds": target_span.source_start_seconds
            if source_start_seconds is None
            else source_start_seconds,
            "source_end_seconds": target_span.source_end_seconds if source_end_seconds is None else source_end_seconds,
            "rationale": rationale,
            "destination_index": destination_index,
            "speed": speed,
            "replacement_span_id": replacement_span.span_id if replacement_span else None,
            "replacement_start_seconds": replacement_span.source_start_seconds
            if replacement_span and replacement_start_seconds is None
            else replacement_start_seconds,
            "replacement_end_seconds": replacement_span.source_end_seconds
            if replacement_span and replacement_end_seconds is None
            else replacement_end_seconds,
        }
        prototype = cls.model_construct(edit_id="edit:" + "0" * 64, edit_sha256="sha256:" + "0" * 64, **payload)
        digest = canonical_digest(prototype, exclude={"edit_id", "edit_sha256"})
        return cls(edit_id="edit:" + digest.removeprefix("sha256:"), edit_sha256=digest, **payload)

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("edit source range must have positive duration")
        operation_fields = {
            EditOperation.REORDER: self.destination_index is not None
            and self.speed is None
            and self.replacement_span_id is None,
            EditOperation.SPEED: self.speed is not None
            and self.destination_index is None
            and self.replacement_span_id is None,
            EditOperation.REPLACE: self.replacement_span_id is not None
            and self.destination_index is None
            and self.speed is None,
            EditOperation.DELETE: self.destination_index is None
            and self.speed is None
            and self.replacement_span_id is None,
            EditOperation.RETAIN: self.destination_index is None
            and self.speed is None
            and self.replacement_span_id is None,
        }
        if not operation_fields[self.operation]:
            raise ValueError(f"invalid fields for {self.operation.value} edit")
        replacement_values = (self.replacement_start_seconds, self.replacement_end_seconds)
        if self.operation == EditOperation.REPLACE:
            replacement_start = self.replacement_start_seconds
            replacement_end = self.replacement_end_seconds
            if replacement_start is None or replacement_end is None:
                raise ValueError("replacement edits require an exact source range")
            if replacement_end <= replacement_start:
                raise ValueError("replacement source range must have positive duration")
        elif any(value is not None for value in replacement_values):
            raise ValueError("replacement source range is only valid for replacement edits")
        expected = canonical_digest(self, exclude={"edit_id", "edit_sha256"})
        if self.edit_sha256 != expected:
            raise ValueError("edit hash does not match canonical edit content")
        if self.edit_id != "edit:" + expected.removeprefix("sha256:"):
            raise ValueError("edit id does not match canonical edit content")
        return self


class EditDecisionList(FrozenModel):
    schema_version: Literal[1] = 1
    artifact_kind: Literal["edit_decision_list"] = "edit_decision_list"
    policy_id: Literal["local_timeline_editing"] = "local_timeline_editing"
    policy_version: Literal[1] = 1
    timeline_edits_allowed: Literal[True] = True
    synthetic_speech_allowed: Literal[False] = False
    hidden_reordering_allowed: Literal[False] = False
    source_overwrite_allowed: Literal[False] = False
    network_allowed: Literal[False] = False
    source_id: str
    source_duration_seconds: float = Field(gt=0.0)
    semantic_timeline_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    edits: tuple[EditAction, ...]
    edl_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @classmethod
    def create(cls, *, timeline: SemanticTimeline, edits: Sequence[EditAction]) -> Self:
        canonical = tuple(edits)
        _validate_edit_references(timeline, canonical)
        prototype = cls.model_construct(
            source_id=timeline.source.source_id,
            source_duration_seconds=timeline.source.duration_seconds,
            semantic_timeline_sha256=timeline.timeline_sha256,
            edits=canonical,
            edl_sha256="sha256:" + "0" * 64,
        )
        digest = canonical_digest(prototype, exclude={"edl_sha256"})
        return cls(
            source_id=timeline.source.source_id,
            source_duration_seconds=timeline.source.duration_seconds,
            semantic_timeline_sha256=timeline.timeline_sha256,
            edits=canonical,
            edl_sha256=digest,
        )

    @model_validator(mode="after")
    def validate_edl_hash(self) -> Self:
        if len({edit.edit_id for edit in self.edits}) != len(self.edits):
            raise ValueError("EDL edit ids must be unique")
        expected = canonical_digest(self, exclude={"edl_sha256"})
        if self.edl_sha256 != expected:
            raise ValueError("EDL hash does not match canonical EDL content")
        return self


class EditApproval(FrozenModel):
    schema_version: Literal[1] = 1
    edl_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    selected_edit_ids: tuple[str, ...]
    approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @classmethod
    def create(cls, *, edl: EditDecisionList, selected_edit_ids: Sequence[str]) -> Self:
        requested = tuple(selected_edit_ids)
        known = {edit.edit_id for edit in edl.edits}
        if len(requested) != len(set(requested)) or not set(requested).issubset(known):
            raise MCPValidationError("selected_edit_ids", "approval must contain unique edit ids from the exact EDL")
        selected = tuple(edit.edit_id for edit in edl.edits if edit.edit_id in requested)
        prototype = cls.model_construct(
            edl_sha256=edl.edl_sha256,
            selected_edit_ids=selected,
            approval_sha256="sha256:" + "0" * 64,
        )
        digest = canonical_digest(prototype, exclude={"approval_sha256"})
        return cls(edl_sha256=edl.edl_sha256, selected_edit_ids=selected, approval_sha256=digest)

    @model_validator(mode="after")
    def validate_approval_hash(self) -> Self:
        if len(self.selected_edit_ids) != len(set(self.selected_edit_ids)):
            raise ValueError("selected approval edit ids must be unique")
        expected = canonical_digest(self, exclude={"approval_sha256"})
        if self.approval_sha256 != expected:
            raise ValueError("approval hash does not match exact EDL and selected edit ids")
        return self


class TimelineSegment(FrozenModel):
    segment_id: str
    source_id: str
    source_start_seconds: float
    source_end_seconds: float
    output_start_seconds: float
    output_end_seconds: float
    speed: float = Field(gt=0.0)
    origin_edit_id: str | None = None


class RemovedRange(FrozenModel):
    edit_id: str
    target_span_id: str
    source_start_seconds: float
    source_end_seconds: float


class CaptionRemap(FrozenModel):
    remap_id: str
    span_id: str
    span_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    source_start_seconds: float
    source_end_seconds: float
    output_start_seconds: float
    output_end_seconds: float
    confidence: float = Field(ge=0.0, le=1.0)


class TimelineDiff(FrozenModel):
    schema_version: Literal[1] = 1
    artifact_kind: Literal["timeline_diff"] = "timeline_diff"
    edl_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    selected_edit_ids: tuple[str, ...]
    source_duration_seconds: float
    output_duration_seconds: float
    output_segments: tuple[TimelineSegment, ...]
    removed: tuple[RemovedRange, ...]
    audio_video_mapping_shared: Literal[True] = True
    caption_remap: tuple[CaptionRemap, ...]
    diff_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @classmethod
    def create(cls, *, timeline: SemanticTimeline, edl: EditDecisionList, approval: EditApproval) -> Self:
        return cast(Self, plan_timeline_diff(timeline, edl, approval))

    @model_validator(mode="after")
    def validate_diff_hash(self) -> Self:
        expected = canonical_digest(self, exclude={"diff_sha256"})
        if self.diff_sha256 != expected:
            raise ValueError("timeline diff hash does not match canonical diff content")
        return self


class VerificationCheck(FrozenModel):
    check_id: str
    passed: bool
    message: str


class EDLVerification(FrozenModel):
    schema_version: Literal[1] = 1
    edl_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    diff_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    passed: bool
    checks: tuple[VerificationCheck, ...]


def _validate_edit_references(timeline: SemanticTimeline, edits: tuple[EditAction, ...]) -> None:
    if len({edit.edit_id for edit in edits}) != len(edits):
        raise MCPValidationError("edits", "edit ids must be unique")
    for edit in edits:
        expected_hash = canonical_digest(edit, exclude={"edit_id", "edit_sha256"})
        expected_id = "edit:" + expected_hash.removeprefix("sha256:")
        if edit.edit_sha256 != expected_hash or edit.edit_id != expected_id:
            raise MCPValidationError("edits", "every edit must retain its exact canonical hash and id")
        target = timeline.span_by_id(edit.target_span_id)
        if target is None or not _contains(target, edit.source_start_seconds, edit.source_end_seconds):
            raise MCPValidationError("edits", "every edit range must be contained by its exact target span id")
        if edit.replacement_span_id:
            replacement = timeline.span_by_id(edit.replacement_span_id)
            if replacement is None or not _contains(
                replacement, edit.replacement_start_seconds, edit.replacement_end_seconds
            ):
                raise MCPValidationError("edits", "replacement range must be contained by its exact source span id")
    ordered = sorted(edits, key=lambda edit: (edit.source_start_seconds, edit.source_end_seconds, edit.edit_id))
    if any(left.source_end_seconds > right.source_start_seconds for left, right in pairwise(ordered)):
        raise MCPValidationError("edits", "edit source ranges must not overlap")


def _contains(span: SourceSpan, start: float | None, end: float | None) -> bool:
    return start is not None and end is not None and span.source_start_seconds <= start < end <= span.source_end_seconds


def make_edit(*, operation: EditOperation, target_span: SourceSpan, rationale: str, **options: Any) -> EditAction:
    return EditAction.create(operation=operation, target_span=target_span, rationale=rationale, **options)


def create_edl(timeline: SemanticTimeline, *, edits: Sequence[EditAction]) -> EditDecisionList:
    return EditDecisionList.create(timeline=timeline, edits=edits)


def approve_edl(edl: EditDecisionList, *, selected_edit_ids: Sequence[str]) -> EditApproval:
    return EditApproval.create(edl=edl, selected_edit_ids=selected_edit_ids)


def _selected_actions(edl: EditDecisionList, approval: EditApproval) -> tuple[EditAction, ...]:
    expected_edl_hash = canonical_digest(edl, exclude={"edl_sha256"})
    if edl.edl_sha256 != expected_edl_hash:
        raise MCPValidationError("edl", "EDL hash does not match its canonical content")
    expected_approval_hash = canonical_digest(approval, exclude={"approval_sha256"})
    if approval.approval_sha256 != expected_approval_hash:
        raise MCPValidationError("approval", "approval hash does not match exact selected edit ids")
    if approval.edl_sha256 != edl.edl_sha256:
        raise MCPValidationError("approval", "approval must bind the exact EDL hash")
    known = {edit.edit_id for edit in edl.edits}
    if not set(approval.selected_edit_ids).issubset(known):
        raise MCPValidationError("approval", "approval contains an edit id outside the EDL")
    return tuple(edit for edit in edl.edits if edit.edit_id in approval.selected_edit_ids)


def _atomic_segments(duration: float, actions: tuple[EditAction, ...], source_id: str) -> list[dict[str, Any]]:
    boundaries = {0.0, duration}
    for action in actions:
        boundaries.update((action.source_start_seconds, action.source_end_seconds))
    points = sorted(boundaries)
    segments: list[dict[str, Any]] = []
    for start, end in pairwise(points):
        action = next(
            (
                candidate
                for candidate in actions
                if candidate.source_start_seconds <= start and end <= candidate.source_end_seconds
            ),
            None,
        )
        if action and action.operation == EditOperation.DELETE:
            continue
        if action and action.operation == EditOperation.REPLACE:
            if start == action.source_start_seconds:
                segments.append(_replacement_segment(action, source_id))
            continue
        segments.append(
            {
                "source_id": source_id,
                "start": start,
                "end": end,
                "speed": action.speed if action and action.operation == EditOperation.SPEED else 1.0,
                "edit_id": action.edit_id if action else None,
            }
        )
    return _apply_reorders(segments, tuple(action for action in actions if action.operation == EditOperation.REORDER))


def _replacement_segment(action: EditAction, source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "start": action.replacement_start_seconds,
        "end": action.replacement_end_seconds,
        "speed": 1.0,
        "edit_id": action.edit_id,
    }


def _apply_reorders(segments: list[dict[str, Any]], actions: tuple[EditAction, ...]) -> list[dict[str, Any]]:
    moved: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        moved[action.edit_id] = [segment for segment in segments if segment["edit_id"] == action.edit_id]
    remaining = [segment for segment in segments if segment["edit_id"] not in moved]
    for action in sorted(actions, key=lambda item: (item.destination_index, item.edit_id)):
        destination_index = action.destination_index
        if destination_index is None:
            raise MCPValidationError("destination_index", "reorder edits require a destination index")
        if destination_index > len(remaining):
            raise MCPValidationError("destination_index", "reorder destination exceeds output segment count")
        remaining[destination_index:destination_index] = moved[action.edit_id]
    return remaining


def _timeline_segments(raw: list[dict[str, Any]]) -> tuple[TimelineSegment, ...]:
    output_position = 0.0
    result: list[TimelineSegment] = []
    for segment in raw:
        duration = (segment["end"] - segment["start"]) / segment["speed"]
        payload = {
            "source_id": segment["source_id"],
            "source_start_seconds": segment["start"],
            "source_end_seconds": segment["end"],
            "output_start_seconds": output_position,
            "output_end_seconds": output_position + duration,
            "speed": segment["speed"],
            "origin_edit_id": segment["edit_id"],
        }
        segment_id = "segment:" + canonical_digest(payload).removeprefix("sha256:")
        result.append(TimelineSegment(segment_id=segment_id, **payload))
        output_position += duration
    return tuple(result)


def _caption_remap(timeline: SemanticTimeline, segments: tuple[TimelineSegment, ...]) -> tuple[CaptionRemap, ...]:
    remaps: list[CaptionRemap] = []
    for word in timeline.words:
        containing = [
            segment
            for segment in segments
            if segment.source_start_seconds <= word.source_start_seconds
            and word.source_end_seconds <= segment.source_end_seconds
        ]
        intersects = [
            segment
            for segment in segments
            if segment.source_start_seconds < word.source_end_seconds
            and segment.source_end_seconds > word.source_start_seconds
        ]
        if intersects and not containing:
            raise MCPValidationError("caption_remap", "approved edits must not leave a partially mapped word span")
        for segment in containing:
            output_start = (
                segment.output_start_seconds
                + (word.source_start_seconds - segment.source_start_seconds) / segment.speed
            )
            output_end = (
                segment.output_start_seconds + (word.source_end_seconds - segment.source_start_seconds) / segment.speed
            )
            payload = {
                "span_id": word.span_id,
                "span_sha256": word.span_sha256,
                "source_start_seconds": word.source_start_seconds,
                "source_end_seconds": word.source_end_seconds,
                "output_start_seconds": output_start,
                "output_end_seconds": output_end,
                "confidence": word.confidence,
            }
            remap_id = "caption_remap:" + canonical_digest(payload).removeprefix("sha256:")
            remaps.append(CaptionRemap(remap_id=remap_id, **payload))
    return tuple(sorted(remaps, key=lambda remap: (remap.output_start_seconds, remap.span_id)))


def plan_timeline_diff(timeline: SemanticTimeline, edl: EditDecisionList, approval: EditApproval) -> TimelineDiff:
    """Compile approved actions into an explicit output-to-source coverage map."""

    if edl.source_id != timeline.source.source_id or edl.semantic_timeline_sha256 != timeline.timeline_sha256:
        raise MCPValidationError("edl", "EDL must bind the exact semantic timeline and source")
    _validate_edit_references(timeline, edl.edits)
    actions = _selected_actions(edl, approval)
    output_segments = _timeline_segments(
        _atomic_segments(timeline.source.duration_seconds, actions, timeline.source.source_id)
    )
    removed = tuple(
        RemovedRange(
            edit_id=action.edit_id,
            target_span_id=action.target_span_id,
            source_start_seconds=action.source_start_seconds,
            source_end_seconds=action.source_end_seconds,
        )
        for action in actions
        if action.operation in {EditOperation.DELETE, EditOperation.REPLACE}
    )
    payload = {
        "edl_sha256": edl.edl_sha256,
        "approval_sha256": approval.approval_sha256,
        "selected_edit_ids": approval.selected_edit_ids,
        "source_duration_seconds": timeline.source.duration_seconds,
        "output_duration_seconds": output_segments[-1].output_end_seconds if output_segments else 0.0,
        "output_segments": output_segments,
        "removed": removed,
        "audio_video_mapping_shared": True,
        "caption_remap": _caption_remap(timeline, output_segments),
    }
    prototype = TimelineDiff.model_construct(diff_sha256="sha256:" + "0" * 64, **payload)
    digest = canonical_digest(prototype, exclude={"diff_sha256"})
    return TimelineDiff(diff_sha256=digest, **payload)


def _check(check_id: str, passed: bool, success: str, failure: str) -> VerificationCheck:
    return VerificationCheck(check_id=check_id, passed=passed, message=success if passed else failure)


def verify_timeline_diff(
    timeline: SemanticTimeline, edl: EditDecisionList, approval: EditApproval, diff: TimelineDiff
) -> EDLVerification:
    """Independently recompute the diff and fail closed on any mismatch."""

    approval_ok = (
        approval.edl_sha256 == edl.edl_sha256
        and approval.approval_sha256 == canonical_digest(approval, exclude={"approval_sha256"})
        and set(approval.selected_edit_ids).issubset({edit.edit_id for edit in edl.edits})
    )
    try:
        expected = plan_timeline_diff(timeline, edl, approval)
        expected_ok = diff == expected
    except MCPValidationError:
        expected = None
        expected_ok = False
    coverage_ok = all(
        segment.source_id == timeline.source.source_id
        and 0 <= segment.source_start_seconds < segment.source_end_seconds <= timeline.source.duration_seconds
        for segment in diff.output_segments
    )
    ordering_ok = all(
        segment.output_start_seconds == (0.0 if index == 0 else diff.output_segments[index - 1].output_end_seconds)
        and segment.output_end_seconds > segment.output_start_seconds
        for index, segment in enumerate(diff.output_segments)
    )
    audio_video_ok = diff.audio_video_mapping_shared and expected is not None
    known_words = {word.span_id: word.span_sha256 for word in timeline.words}
    caption_ok = (
        expected is not None
        and diff.caption_remap == expected.caption_remap
        and all(
            known_words.get(remap.span_id) == remap.span_sha256
            and 0 <= remap.output_start_seconds < remap.output_end_seconds <= diff.output_duration_seconds
            for remap in diff.caption_remap
        )
    )
    checks = (
        _check(
            "approval_hash",
            approval_ok,
            "Approval binds this EDL and selected edit ids.",
            "Approval does not bind this EDL.",
        ),
        _check(
            "source_coverage",
            coverage_ok,
            "Every output segment maps to valid source time.",
            "Output contains invalid or foreign source time.",
        ),
        _check(
            "ordering",
            ordering_ok and expected_ok,
            "Output ordering exactly matches approved actions.",
            "Output ordering differs from approved actions.",
        ),
        _check(
            "approved_removal_only",
            expected_ok,
            "Removed time exactly matches approved edits.",
            "Timeline diff contains missing, changed, or unapproved removal.",
        ),
        _check(
            "audio_video_sync",
            audio_video_ok and expected_ok,
            "Audio and video share the exact approved source-to-output map.",
            "Audio/video mapping is missing or differs from the approved diff.",
        ),
        _check(
            "caption_remap",
            caption_ok,
            "Retained transcript spans map exactly onto output time.",
            "Caption remap is missing, stale, partial, or source-inconsistent.",
        ),
    )
    return EDLVerification(
        edl_sha256=edl.edl_sha256,
        diff_sha256=diff.diff_sha256,
        passed=all(check.passed for check in checks),
        checks=checks,
    )


def _timeline(value: SemanticTimeline | Mapping[str, Any]) -> SemanticTimeline:
    return value if isinstance(value, SemanticTimeline) else SemanticTimeline.model_validate(value)


def build_edl(
    timeline: SemanticTimeline | Mapping[str, Any],
    *,
    edits: Sequence[EditAction | Mapping[str, Any]],
) -> EditDecisionList:
    """Surface adapter for a model or JSON-compatible semantic timeline and edits."""

    canonical_timeline = _timeline(timeline)
    canonical_edits = tuple(edit if isinstance(edit, EditAction) else EditAction.model_validate(edit) for edit in edits)
    return create_edl(canonical_timeline, edits=canonical_edits)


def verify_edl(
    timeline: SemanticTimeline | Mapping[str, Any],
    edl: EditDecisionList | Mapping[str, Any],
    approval: EditApproval | Mapping[str, Any],
    diff: TimelineDiff | Mapping[str, Any],
) -> EDLVerification:
    """Surface verifier accepting validated Pydantic models or their JSON dumps."""

    return verify_timeline_diff(
        _timeline(timeline),
        edl if isinstance(edl, EditDecisionList) else EditDecisionList.model_validate(edl),
        approval if isinstance(approval, EditApproval) else EditApproval.model_validate(approval),
        diff if isinstance(diff, TimelineDiff) else TimelineDiff.model_validate(diff),
    )
