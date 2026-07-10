"""Deterministic C2 composition planning over an immutable C1 manifest."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from .composition_models import (
    COMPOSITION_VERIFIER_IDS,
    AudioMixTrack,
    CaptionPlan,
    CompositionIntent,
    CompositionPlan,
    GraphicElement,
    LayoutSpec,
    OutputVariant,
    SourceBinding,
    TimelineSegment,
)
from .errors import CreativeContractError
from .models import ProjectManifest, SelectionPlan, canonical_digest

_ZERO_SHA256 = "sha256:" + "0" * 64
ModelT = TypeVar("ModelT", bound=BaseModel)


class _HasId(Protocol):
    id: str


def _validated(value: ModelT | Mapping[str, Any], model_type: type[ModelT]) -> ModelT:
    return value if isinstance(value, model_type) else model_type.model_validate(value)


def _validated_sequence(values: Sequence[ModelT | Mapping[str, Any]], model_type: type[ModelT]) -> tuple[ModelT, ...]:
    return tuple(_validated(value, model_type) for value in values)


def _require_digest(model: BaseModel, field_name: str, code: str) -> None:
    expected = canonical_digest(model, exclude={field_name})
    if getattr(model, field_name) != expected:
        raise CreativeContractError(code, f"{field_name} does not match the canonical contract payload.")


def _unique_ids(items: Sequence[_HasId], label: str) -> None:
    ids = tuple(item.id for item in items)
    if len(ids) != len(set(ids)):
        raise CreativeContractError("duplicate_composition_id", f"{label} ids must be unique.")


def _validate_directives(
    manifest: ProjectManifest,
    layouts: tuple[LayoutSpec, ...],
    graphics: tuple[GraphicElement, ...],
    audio_tracks: tuple[AudioMixTrack, ...],
    caption_plan: CaptionPlan | None,
    output_variants: tuple[OutputVariant, ...],
) -> None:
    for items, label in (
        (layouts, "layout"),
        (graphics, "graphic"),
        (audio_tracks, "audio track"),
        (output_variants, "output variant"),
    ):
        _unique_ids(items, label)
    assets = {asset.id: asset for asset in manifest.assets}
    constraints = manifest.brand_constraints
    allowed_logos = set(constraints.logo_asset_ids)
    allowed_music = set(constraints.music_asset_ids)
    allowed_fonts = set(constraints.font_asset_ids)
    allowed_captions = set(constraints.caption_asset_ids)
    for graphic in graphics:
        if graphic.asset_id and graphic.asset_id not in assets:
            raise CreativeContractError("unknown_graphic_asset", f"Graphic {graphic.id} references an unknown asset.")
        if graphic.kind == "logo" and assets[graphic.asset_id or ""].media_kind != "image":
            raise CreativeContractError("invalid_logo_asset", f"Graphic {graphic.id} logo source is not an image.")
        if graphic.kind == "logo" and allowed_logos and graphic.asset_id not in allowed_logos:
            raise CreativeContractError("unapproved_logo", f"Graphic {graphic.id} uses an unapproved logo asset.")
        if graphic.font_asset_id and allowed_fonts and graphic.font_asset_id not in allowed_fonts:
            raise CreativeContractError("unapproved_font", f"Graphic {graphic.id} uses an unapproved font asset.")
        if graphic.font_asset_id and assets[graphic.font_asset_id].media_kind != "font":
            raise CreativeContractError("invalid_font_asset", f"Graphic {graphic.id} font source is not a font.")
    for track in audio_tracks:
        if track.asset_id not in assets or (allowed_music and track.asset_id not in allowed_music):
            raise CreativeContractError("unapproved_audio", f"Audio track {track.id} uses an unapproved asset.")
        asset = assets[track.asset_id]
        if asset.media_kind != "audio":
            raise CreativeContractError("invalid_audio_asset", f"Audio track {track.id} source is not audio.")
        known_spans = {span.id for span in asset.semantic_spans}
        if not set(track.span_ids).issubset(known_spans):
            raise CreativeContractError(
                "unknown_audio_span", f"Audio track {track.id} references an unknown semantic span."
            )
    if caption_plan:
        if caption_plan.asset_id not in assets or (allowed_captions and caption_plan.asset_id not in allowed_captions):
            raise CreativeContractError("unapproved_captions", "Caption plan uses an unapproved asset.")
        if assets[caption_plan.asset_id].media_kind != "captions":
            raise CreativeContractError("invalid_caption_asset", "Caption plan source is not a caption asset.")
        if caption_plan.font_asset_id and allowed_fonts and caption_plan.font_asset_id not in allowed_fonts:
            raise CreativeContractError("unapproved_font", "Caption plan uses an unapproved font asset.")
        if caption_plan.font_asset_id and assets[caption_plan.font_asset_id].media_kind != "font":
            raise CreativeContractError("invalid_font_asset", "Caption plan font source is not a font.")
    used_colors = {item.color for item in graphics if item.color}
    if caption_plan and caption_plan.color:
        used_colors.add(caption_plan.color)
    if not set(constraints.required_colors).issubset(used_colors):
        raise CreativeContractError("missing_brand_color", "Composition omits a required brand color.")
    graphic_text = {item.text for item in graphics if item.text}
    if not set(constraints.required_text).issubset(graphic_text):
        raise CreativeContractError("missing_brand_text", "Composition omits required brand text.")
    if set(constraints.forbidden_text) & graphic_text:
        raise CreativeContractError("forbidden_brand_text", "Composition includes forbidden brand text.")


def _build_timeline(
    manifest: ProjectManifest,
    bindings: tuple[SourceBinding, ...],
    layouts: tuple[LayoutSpec, ...],
    target_duration: float,
) -> tuple[TimelineSegment, ...]:
    assets = {asset.id: asset for asset in manifest.assets}
    output_cursor = 0.0
    segments: list[TimelineSegment] = []
    for binding in bindings:
        asset = assets[binding.asset_id]
        if asset.media_kind != "video":
            continue
        layout = next((item for item in layouts if binding.role in item.role_bindings), None)
        if layout is None:
            raise CreativeContractError("layout_prerequisite_absent", f"No layout binds role {binding.role}.")
        spans = {span.id: span for span in asset.semantic_spans}
        for span_id in binding.span_ids:
            if output_cursor >= target_duration:
                break
            span = spans[span_id]
            duration = min(span.end_seconds - span.start_seconds, target_duration - output_cursor)
            segments.append(
                TimelineSegment(
                    id=f"segment:{len(segments) + 1:03d}",
                    role=binding.role,
                    asset_id=binding.asset_id,
                    selected_span_ids=(span_id,),
                    source_start_seconds=span.start_seconds,
                    source_end_seconds=span.start_seconds + duration,
                    output_start_seconds=output_cursor,
                    output_end_seconds=output_cursor + duration,
                    layout_id=layout.id,
                )
            )
            output_cursor += duration
    if not segments or abs(output_cursor - target_duration) > 1e-6:
        raise CreativeContractError(
            "timeline_evidence_insufficient",
            "Selected source-backed video spans do not cover the requested duration.",
        )
    return tuple(segments)


def plan_composition(
    *,
    manifest: ProjectManifest | Mapping[str, Any],
    selection: SelectionPlan | Mapping[str, Any],
    intent: CompositionIntent | Mapping[str, Any],
    layouts: Sequence[LayoutSpec | Mapping[str, Any]],
    graphics: Sequence[GraphicElement | Mapping[str, Any]] = (),
    audio_tracks: Sequence[AudioMixTrack | Mapping[str, Any]] = (),
    caption_plan: CaptionPlan | Mapping[str, Any] | None = None,
    output_variants: Sequence[OutputVariant | Mapping[str, Any]] = (),
) -> CompositionPlan:
    """Map declared intent and evidence to an inspectable plan; never execute media work."""

    valid_manifest = _validated(manifest, ProjectManifest)
    valid_selection = _validated(selection, SelectionPlan)
    valid_intent = _validated(intent, CompositionIntent)
    valid_layouts = _validated_sequence(layouts, LayoutSpec)
    valid_graphics = _validated_sequence(graphics, GraphicElement)
    valid_audio = _validated_sequence(audio_tracks, AudioMixTrack)
    valid_caption = None if caption_plan is None else _validated(caption_plan, CaptionPlan)
    valid_variants = _validated_sequence(output_variants, OutputVariant)
    _require_digest(valid_manifest, "manifest_sha256", "manifest_hash_mismatch")
    _require_digest(valid_selection, "selection_sha256", "selection_hash_mismatch")
    if valid_selection.manifest_sha256 != valid_manifest.manifest_sha256:
        raise CreativeContractError("selection_manifest_mismatch", "Selection is bound to a different manifest.")
    if valid_selection.abstentions:
        raise CreativeContractError("selection_incomplete", "Composition cannot proceed with selection abstentions.")
    _validate_directives(valid_manifest, valid_layouts, valid_graphics, valid_audio, valid_caption, valid_variants)
    bindings = tuple(
        SourceBinding(
            role=item.role,
            asset_id=item.asset_id,
            span_ids=item.span_ids,
            confidence=item.confidence,
            confidence_rationale=item.confidence_rationale,
            evidence_ids=item.evidence_ids,
        )
        for item in sorted(valid_selection.selections, key=lambda item: (item.role, item.asset_id))
    )
    timeline = _build_timeline(valid_manifest, bindings, valid_layouts, valid_intent.target_duration_seconds)
    draft = CompositionPlan(
        manifest_sha256=valid_manifest.manifest_sha256,
        selection_sha256=valid_selection.selection_sha256,
        intent=valid_intent,
        source_bindings=bindings,
        timeline=timeline,
        layouts=tuple(sorted(valid_layouts, key=lambda item: item.id)),
        graphics=tuple(sorted(valid_graphics, key=lambda item: item.id)),
        audio_tracks=tuple(sorted(valid_audio, key=lambda item: item.id)),
        caption_plan=valid_caption,
        output_variants=tuple(sorted(valid_variants, key=lambda item: item.id)),
        brand_constraints=valid_manifest.brand_constraints,
        compile_target=valid_intent.compile_target,
        verifier_ids=COMPOSITION_VERIFIER_IDS,
        plan_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"plan_sha256": canonical_digest(draft, exclude={"plan_sha256"})})
