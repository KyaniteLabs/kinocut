"""Pure V2 subject-aware crop planning."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from kinocut.errors import ValidationError

from .models import (
    CropBudget,
    CropPreview,
    CropTarget,
    CropTrackSample,
    CropVariantPlan,
    NormalizedBox,
    ReframePlan,
    SpeakerTurn,
    TrackSample,
    VisualAnalysisPlan,
    canonical_sha256,
)


def _coverage(content: NormalizedBox, window: NormalizedBox) -> float:
    left = max(content.x, window.x)
    top = max(content.y, window.y)
    right = min(content.x + content.width, window.x + window.width)
    bottom = min(content.y + content.height, window.y + window.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    return max(0.0, min(1.0, intersection / content.area))


def _crop_size(source_width: int, source_height: int, target: CropTarget) -> tuple[float, float]:
    source_aspect = source_width / source_height
    target_aspect = target.aspect_width / target.aspect_height
    if target_aspect <= source_aspect:
        return target_aspect / source_aspect, 1.0
    return 1.0, source_aspect / target_aspect


def _bounded_center(desired: float, previous: float | None, size: float, max_step: float) -> float:
    lower = size / 2.0
    upper = 1.0 - size / 2.0
    bounded = min(upper, max(lower, desired))
    if previous is not None:
        bounded = min(previous + max_step, max(previous - max_step, bounded))
    return min(upper, max(lower, bounded))


def _track_samples(
    analysis: VisualAnalysisPlan,
    target: CropTarget,
    max_center_step: float,
    speaker_turns: tuple[SpeakerTurn, ...],
) -> tuple[CropTrackSample, ...]:
    tracks = {item.subject_id: item for item in analysis.subject_tracks}
    track = tracks[analysis.primary_subject_id]
    frame_regions = {item.timestamp_seconds: item.regions for item in analysis.safe_regions}
    crop_width, crop_height = _crop_size(analysis.source.width, analysis.source.height, target)
    previous_x: float | None = None
    previous_y: float | None = None
    samples = []
    for primary_sample in track.samples:
        active_id = _active_subject_id(primary_sample.timestamp_seconds, speaker_turns, analysis.primary_subject_id)
        subject = _nearest_sample(tracks[active_id].samples, primary_sample.timestamp_seconds)
        center_x = _bounded_center(subject.box.center_x, previous_x, crop_width, max_center_step)
        center_y = _bounded_center(subject.box.center_y, previous_y, crop_height, max_center_step)
        crop = NormalizedBox(
            x=center_x - crop_width / 2.0,
            y=center_y - crop_height / 2.0,
            width=crop_width,
            height=crop_height,
        )
        regions = frame_regions.get(subject.timestamp_seconds, ())
        region_coverage = min((_coverage(region.box, crop) for region in regions), default=1.0)
        samples.append(
            CropTrackSample(
                timestamp_seconds=primary_sample.timestamp_seconds,
                active_subject_id=active_id,
                crop_box=crop,
                subject_coverage=_coverage(subject.box, crop),
                safe_region_coverage=region_coverage,
                source_width=max(1, round(crop.width * analysis.source.width)),
                source_height=max(1, round(crop.height * analysis.source.height)),
            )
        )
        previous_x, previous_y = center_x, center_y
    return tuple(samples)


def _active_subject_id(
    timestamp: float,
    speaker_turns: tuple[SpeakerTurn, ...],
    fallback: str,
) -> str:
    matches = [turn for turn in speaker_turns if turn.start_seconds <= timestamp < turn.end_seconds]
    if not matches:
        return fallback
    return min(matches, key=lambda turn: (-turn.confidence, turn.subject_id)).subject_id


def _nearest_sample(samples: tuple[TrackSample, ...], timestamp: float) -> TrackSample:
    return min(samples, key=lambda sample: (abs(sample.timestamp_seconds - timestamp), sample.timestamp_seconds))


def _representative_previews(samples: tuple[CropTrackSample, ...], preview_count: int) -> tuple[CropPreview, ...]:
    count = min(preview_count, len(samples))
    indices: tuple[int, ...]
    if count == 1:
        indices = (0,)
    else:
        indices = tuple(dict.fromkeys(round(index * (len(samples) - 1) / (count - 1)) for index in range(count)))
    return tuple(
        CropPreview(
            timestamp_seconds=samples[index].timestamp_seconds,
            crop_box=samples[index].crop_box,
            subject_coverage=samples[index].subject_coverage,
            safe_region_coverage=samples[index].safe_region_coverage,
        )
        for index in indices
    )


def _abstention_reasons(
    analysis: VisualAnalysisPlan,
    track_confidence: float,
    min_tracking_confidence: float,
    source_crop_fraction: float,
    maximum_subject_loss: float,
    budget: CropBudget,
) -> tuple[str, ...]:
    reasons = []
    if track_confidence < min_tracking_confidence:
        reasons.append("tracking_confidence_below_threshold")
    if any(loss.subject_id == analysis.primary_subject_id for loss in analysis.tracking_losses):
        reasons.append("tracking_loss")
    if analysis.ambiguities:
        reasons.append("multi_subject_ambiguity")
    if source_crop_fraction > budget.max_source_crop_fraction + 1e-12:
        reasons.append("source_crop_budget_exceeded")
    if maximum_subject_loss > budget.max_subject_loss + 1e-12:
        reasons.append("subject_crop_budget_exceeded")
    return tuple(reasons)


def _variant(
    analysis: VisualAnalysisPlan,
    target: CropTarget,
    budget: CropBudget,
    min_tracking_confidence: float,
    max_center_step: float,
    preview_count: int,
    speaker_turns: tuple[SpeakerTurn, ...],
) -> CropVariantPlan:
    selected_ids = {turn.subject_id for turn in speaker_turns} or {analysis.primary_subject_id}
    confidence = min(item.confidence for item in analysis.subject_tracks if item.subject_id in selected_ids)
    samples = _track_samples(analysis, target, max_center_step, speaker_turns)
    source_crop_fraction = 1.0 - samples[0].crop_box.area
    maximum_subject_loss = max((1.0 - sample.subject_coverage for sample in samples), default=1.0)
    reasons = _abstention_reasons(
        analysis, confidence, min_tracking_confidence, source_crop_fraction, maximum_subject_loss, budget
    )
    return CropVariantPlan(
        target_id=target.target_id,
        status="abstained" if reasons else "ready",
        abstention_reasons=reasons,
        output_width=target.output_width,
        output_height=target.output_height,
        source_crop_fraction=source_crop_fraction,
        maximum_subject_loss=maximum_subject_loss,
        crop_track=samples,
        previews=_representative_previews(samples, preview_count),
    )


def plan_subject_aware_reframe(
    *,
    analysis: VisualAnalysisPlan | Mapping[str, Any],
    targets: Iterable[CropTarget | Mapping[str, Any]],
    crop_budget: CropBudget | Mapping[str, Any],
    min_tracking_confidence: float = 0.70,
    max_center_step: float = 0.10,
    preview_count: int = 3,
    speaker_turns: Iterable[SpeakerTurn | Mapping[str, Any]] = (),
) -> ReframePlan:
    """Plan target-aspect crop tracks without touching media."""

    if not 0.0 <= min_tracking_confidence <= 1.0:
        raise ValidationError("min_tracking_confidence", "must be between 0 and 1")
    if not 0.0 < max_center_step <= 1.0:
        raise ValidationError("max_center_step", "must be greater than 0 and at most 1")
    if preview_count < 1:
        raise ValidationError("preview_count", "must be at least 1")
    analysis_model = VisualAnalysisPlan.model_validate(analysis)
    target_models = tuple(
        sorted((CropTarget.model_validate(item) for item in targets), key=lambda item: item.target_id)
    )
    if not target_models:
        raise ValidationError("targets", "at least one crop target is required")
    if len({target.target_id for target in target_models}) != len(target_models):
        raise ValidationError("targets", "target ids must be unique")
    budget_model = CropBudget.model_validate(crop_budget)
    turn_models = tuple(
        sorted(
            (SpeakerTurn.model_validate(item) for item in speaker_turns),
            key=lambda item: (item.start_seconds, item.end_seconds, item.subject_id),
        )
    )
    known_subject_ids = {track.subject_id for track in analysis_model.subject_tracks}
    if any(turn.subject_id not in known_subject_ids for turn in turn_models):
        raise ValidationError("speaker_turns", "every speaker turn must reference a known subject track")
    payload = {
        "analysis_sha256": analysis_model.plan_sha256,
        "source": analysis_model.source,
        "primary_subject_id": analysis_model.primary_subject_id,
        "crop_budget": budget_model,
        "speaker_turns": turn_models,
        "min_tracking_confidence": min_tracking_confidence,
        "max_center_step": max_center_step,
        "variants": tuple(
            _variant(
                analysis_model,
                target,
                budget_model,
                min_tracking_confidence,
                max_center_step,
                preview_count,
                turn_models,
            )
            for target in target_models
        ),
    }
    prototype = ReframePlan.model_construct(**payload, plan_sha256="sha256:" + "0" * 64)
    return ReframePlan(
        **payload,
        plan_sha256=canonical_sha256(prototype, exclude={"plan_sha256"}),
    )
