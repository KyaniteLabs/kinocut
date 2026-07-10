"""Pure V1 subject and camera-evidence planner."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from kinocut.errors import ValidationError

from .models import (
    CropLossEstimate,
    FrameEvidence,
    FrameSafeRegions,
    LandmarkCapabilities,
    MultiSubjectAmbiguity,
    SourceVideo,
    SubjectTrack,
    TimedCameraMotion,
    TrackSample,
    TrackingLoss,
    VisualAnalysisPlan,
    canonical_sha256,
)


def _intersection_area(first, second) -> float:  # type: ignore[no-untyped-def]
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    return max(0.0, right - left) * max(0.0, bottom - top)


def _canonical_frames(frames: tuple[FrameEvidence, ...], source: SourceVideo) -> tuple[FrameEvidence, ...]:
    ordered = tuple(sorted(frames, key=lambda frame: frame.timestamp_seconds))
    timestamps = [frame.timestamp_seconds for frame in ordered]
    if not ordered:
        raise ValidationError("frames", "at least one evidence frame is required")
    if len(timestamps) != len(set(timestamps)):
        raise ValidationError("frames", "timestamps must be unique")
    if timestamps[-1] > source.duration_seconds + 1e-9:
        raise ValidationError("frames", "timestamps must not exceed source duration")
    return tuple(
        frame.model_copy(
            update={
                "subjects": tuple(sorted(frame.subjects, key=lambda subject: subject.subject_id)),
                "safe_regions": tuple(sorted(frame.safe_regions, key=lambda region: region.region_id)),
            }
        )
        for frame in ordered
    )


def _subject_tracks(frames: tuple[FrameEvidence, ...]) -> tuple[tuple[SubjectTrack, ...], tuple[TrackingLoss, ...]]:
    samples_by_subject: dict[str, list[TrackSample]] = defaultdict(list)
    observations_by_frame = [{subject.subject_id: subject for subject in frame.subjects} for frame in frames]
    subject_ids = sorted({subject_id for observed in observations_by_frame for subject_id in observed})
    losses: list[TrackingLoss] = []
    tracks: list[SubjectTrack] = []
    for subject_id in subject_ids:
        for frame, observed in zip(frames, observations_by_frame, strict=True):
            subject = observed.get(subject_id)
            if subject is None:
                losses.append(TrackingLoss(subject_id=subject_id, timestamp_seconds=frame.timestamp_seconds))
                continue
            samples_by_subject[subject_id].append(
                TrackSample(
                    timestamp_seconds=frame.timestamp_seconds,
                    box=subject.box,
                    confidence=subject.confidence,
                    face_landmarks=subject.face_landmarks,
                    pose_landmarks=subject.pose_landmarks,
                )
            )
        samples = tuple(samples_by_subject[subject_id])
        tracks.append(
            SubjectTrack(
                subject_id=subject_id,
                confidence=sum(sample.confidence for sample in samples) / len(frames),
                coverage_ratio=len(samples) / len(frames),
                samples=samples,
            )
        )
    return tuple(tracks), tuple(losses)


def _ambiguities(frames: tuple[FrameEvidence, ...], confidence_delta: float) -> tuple[MultiSubjectAmbiguity, ...]:
    ambiguities = []
    for frame in frames:
        ranked = sorted(frame.subjects, key=lambda subject: (-subject.confidence, subject.subject_id))
        if len(ranked) < 2:
            continue
        delta = ranked[0].confidence - ranked[1].confidence
        if delta <= confidence_delta + 1e-12:
            ambiguities.append(
                MultiSubjectAmbiguity(
                    timestamp_seconds=frame.timestamp_seconds,
                    subject_ids=tuple(sorted((ranked[0].subject_id, ranked[1].subject_id))),
                    confidence_delta=delta,
                )
            )
    return tuple(ambiguities)


def _crop_losses(frames: tuple[FrameEvidence, ...], primary_subject_id: str) -> tuple[CropLossEstimate, ...]:
    estimates = []
    for frame in frames:
        subject = next((item for item in frame.subjects if item.subject_id == primary_subject_id), None)
        if subject is None:
            estimates.append(
                CropLossEstimate(
                    timestamp_seconds=frame.timestamp_seconds,
                    subject_id=primary_subject_id,
                    crop_box=frame.candidate_crop,
                    available=False,
                    reason="primary_subject_not_observed",
                )
            )
        elif frame.candidate_crop is None:
            estimates.append(
                CropLossEstimate(
                    timestamp_seconds=frame.timestamp_seconds,
                    subject_id=primary_subject_id,
                    crop_box=None,
                    available=False,
                    reason="candidate_crop_not_provided",
                )
            )
        else:
            retained = _intersection_area(subject.box, frame.candidate_crop) / subject.box.area
            estimates.append(
                CropLossEstimate(
                    timestamp_seconds=frame.timestamp_seconds,
                    subject_id=primary_subject_id,
                    crop_box=frame.candidate_crop,
                    available=True,
                    subject_loss=max(0.0, min(1.0, 1.0 - retained)),
                    source_crop_fraction=1.0 - frame.candidate_crop.area,
                )
            )
    return tuple(estimates)


def plan_visual_analysis(
    *,
    source: SourceVideo | Mapping[str, Any],
    frames: Iterable[FrameEvidence | Mapping[str, Any]],
    primary_subject_id: str,
    ambiguity_confidence_delta: float = 0.05,
) -> VisualAnalysisPlan:
    """Build a canonical V1 plan from already-computed local evidence."""

    if not 0.0 <= ambiguity_confidence_delta <= 1.0:
        raise ValidationError("ambiguity_confidence_delta", "must be between 0 and 1")
    source_model = SourceVideo.model_validate(source)
    frame_models = tuple(FrameEvidence.model_validate(frame) for frame in frames)
    ordered = _canonical_frames(frame_models, source_model)
    tracks, losses = _subject_tracks(ordered)
    if primary_subject_id not in {track.subject_id for track in tracks}:
        raise ValidationError("primary_subject_id", "must reference an observed opaque subject id")
    camera_motion = tuple(
        TimedCameraMotion(timestamp_seconds=frame.timestamp_seconds, **frame.camera_motion.model_dump())
        for frame in ordered
    )
    safe_regions = tuple(
        FrameSafeRegions(timestamp_seconds=frame.timestamp_seconds, regions=frame.safe_regions) for frame in ordered
    )
    capabilities = LandmarkCapabilities(
        face=any(subject.face_landmarks for frame in ordered for subject in frame.subjects),
        pose=any(subject.pose_landmarks for frame in ordered for subject in frame.subjects),
    )
    payload = {
        "source": source_model,
        "primary_subject_id": primary_subject_id,
        "frames": ordered,
        "subject_tracks": tracks,
        "tracking_losses": losses,
        "ambiguities": _ambiguities(ordered, ambiguity_confidence_delta),
        "camera_motion": camera_motion,
        "safe_regions": safe_regions,
        "crop_loss_estimates": _crop_losses(ordered, primary_subject_id),
        "landmark_capabilities": capabilities,
    }
    prototype = VisualAnalysisPlan.model_construct(
        **payload,
        plan_sha256="sha256:" + "0" * 64,
    )
    return VisualAnalysisPlan(
        **payload,
        plan_sha256=canonical_sha256(prototype, exclude={"plan_sha256"}),
    )
