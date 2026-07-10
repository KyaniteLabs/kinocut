"""Contracts for composition plans, previews, approvals, and compilation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .models import (
    _SHA256_PATTERN,
    _STABLE_ID_PATTERN,
    BrandConstraints,
    CreativeModel,
    Sha256,
    relative_reference,
)

COMPOSITION_VERIFIER_IDS = (
    "source_attribution",
    "timeline_coverage",
    "audio_mix",
    "text_layout",
    "branding",
    "variant_contracts",
    "package_integrity",
)


class CompositionIntent(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    summary: str = Field(min_length=1)
    target_duration_seconds: float = Field(gt=0.0)
    compile_target: str = Field(min_length=1)


class SourceBinding(CreativeModel):
    role: str = Field(min_length=1)
    asset_id: str = Field(pattern=_STABLE_ID_PATTERN)
    span_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class LayoutSpec(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    kind: Literal["full_frame", "picture_in_picture", "split_screen", "grid"]
    role_bindings: tuple[str, ...] = Field(min_length=1)


class GraphicElement(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    kind: Literal["logo", "text"]
    asset_id: str | None = Field(default=None, pattern=_STABLE_ID_PATTERN)
    text: str | None = None
    font_asset_id: str | None = Field(default=None, pattern=_STABLE_ID_PATTERN)
    color: str | None = None
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_source(self) -> GraphicElement:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("graphic end_seconds must be greater than start_seconds")
        if self.kind == "logo" and (self.asset_id is None or self.text is not None):
            raise ValueError("logo graphics require asset_id and cannot contain text")
        if self.kind == "text" and (not self.text or self.asset_id is not None):
            raise ValueError("text graphics require text and cannot contain asset_id")
        return self


class AudioMixTrack(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    asset_id: str = Field(pattern=_STABLE_ID_PATTERN)
    span_ids: tuple[str, ...]
    output_start_seconds: float = Field(ge=0.0)
    output_end_seconds: float = Field(gt=0.0)
    gain_db: float = Field(ge=-96.0, le=24.0)
    target_lufs: float = Field(ge=-70.0, le=0.0)
    max_peak_dbfs: float = Field(ge=-20.0, le=0.0)

    @model_validator(mode="after")
    def validate_time_range(self) -> AudioMixTrack:
        if self.output_end_seconds <= self.output_start_seconds:
            raise ValueError("audio output end must be greater than start")
        return self


class CaptionPlan(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    asset_id: str = Field(pattern=_STABLE_ID_PATTERN)
    mode: Literal["editable_sidecar", "burned"]
    font_asset_id: str | None = Field(default=None, pattern=_STABLE_ID_PATTERN)
    color: str | None = None


class OutputVariant(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    width: int = Field(ge=16, le=16384)
    height: int = Field(ge=16, le=16384)
    container: Literal["mp4", "mov", "webm"]


class TimelineSegment(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    role: str
    asset_id: str = Field(pattern=_STABLE_ID_PATTERN)
    selected_span_ids: tuple[str, ...] = Field(min_length=1)
    source_start_seconds: float = Field(ge=0.0)
    source_end_seconds: float = Field(gt=0.0)
    output_start_seconds: float = Field(ge=0.0)
    output_end_seconds: float = Field(gt=0.0)
    layout_id: str = Field(pattern=_STABLE_ID_PATTERN)


class CompositionPlan(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_composition_plan"] = "creative_composition_plan"
    manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    selection_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    intent: CompositionIntent
    source_bindings: tuple[SourceBinding, ...]
    timeline: tuple[TimelineSegment, ...] = Field(min_length=1)
    layouts: tuple[LayoutSpec, ...] = Field(min_length=1)
    graphics: tuple[GraphicElement, ...]
    audio_tracks: tuple[AudioMixTrack, ...]
    caption_plan: CaptionPlan | None
    output_variants: tuple[OutputVariant, ...] = Field(min_length=1)
    brand_constraints: BrandConstraints
    compile_target: str
    verifier_ids: tuple[str, ...] = COMPOSITION_VERIFIER_IDS
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_plan_graph(self) -> CompositionPlan:
        if self.verifier_ids != COMPOSITION_VERIFIER_IDS:
            raise ValueError("verifier_ids must contain the complete ordered composition verifier set")
        if self.compile_target != self.intent.compile_target:
            raise ValueError("compile_target must match the composition intent")
        binding_keys = tuple((item.role, item.asset_id) for item in self.source_bindings)
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("source binding role and asset pairs must be unique")
        for label, items in (
            ("timeline segment", self.timeline),
            ("layout", self.layouts),
            ("graphic", self.graphics),
            ("audio track", self.audio_tracks),
            ("output variant", self.output_variants),
        ):
            ids = tuple(item.id for item in items)
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} ids must be unique")
        layout_ids = {item.id for item in self.layouts}
        binding_spans = {(binding.role, binding.asset_id): set(binding.span_ids) for binding in self.source_bindings}
        cursor = 0.0
        for segment in self.timeline:
            if segment.layout_id not in layout_ids:
                raise ValueError("timeline segment references an unknown layout")
            if not set(segment.selected_span_ids).issubset(binding_spans.get((segment.role, segment.asset_id), set())):
                raise ValueError("timeline segment references an unknown selected span")
            if abs(segment.output_start_seconds - cursor) > 1e-6:
                raise ValueError("timeline segments must be contiguous and ordered")
            cursor = segment.output_end_seconds
        if abs(cursor - self.intent.target_duration_seconds) > 1e-6:
            raise ValueError("timeline must cover the requested duration exactly")
        return self


class StoryboardFrame(CreativeModel):
    index: int = Field(ge=0)
    segment_id: str = Field(pattern=_STABLE_ID_PATTERN)
    output_start_seconds: float = Field(ge=0.0)
    output_end_seconds: float = Field(gt=0.0)
    source_labels: tuple[str, ...]
    layout_id: str
    graphic_ids: tuple[str, ...]


class TimelinePreviewRow(CreativeModel):
    segment_id: str = Field(pattern=_STABLE_ID_PATTERN)
    output_start_seconds: float = Field(ge=0.0)
    output_end_seconds: float = Field(gt=0.0)
    selected_span_ids: tuple[str, ...]
    audio_track_ids: tuple[str, ...]
    caption_id: str | None = None


class CompositionPreview(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_composition_preview"] = "creative_composition_preview"
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    storyboard: tuple[StoryboardFrame, ...]
    timeline: tuple[TimelinePreviewRow, ...]
    changes: tuple[dict[str, str], ...]
    preview_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)


class CompositionApproval(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_composition_approval"] = "creative_composition_approval"
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    preview_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    approved_segment_ids: tuple[str, ...]
    approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)


class CompileOperation(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    op: Literal["trim", "resize", "merge", "add_text", "composite_layers"]
    parameters: dict[str, Any]


class CompiledComposition(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_compile_plan"] = "creative_compile_plan"
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    target_id: str
    operations: tuple[CompileOperation, ...]
    renders_nothing: Literal[True] = True
    compile_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("target_id")
    @classmethod
    def nonempty_target(cls, value: str) -> str:
        return value


class OutputArtifact(CreativeModel):
    variant_id: str = Field(pattern=_STABLE_ID_PATTERN)
    path: str
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(gt=0)
    width: int = Field(ge=16)
    height: int = Field(ge=16)
    container: Literal["mp4", "mov", "webm"]

    _validate_path = field_validator("path")(relative_reference)
