"""Immutable contracts for deterministic visual-intelligence planning."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class StrictModel(BaseModel):
    """Forbid undeclared fields and mutation in planning artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class NormalizedBox(StrictModel):
    """Axis-aligned box in normalized source-frame coordinates."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def stays_inside_frame(self) -> NormalizedBox:
        if self.x + self.width > 1.0 + 1e-9 or self.y + self.height > 1.0 + 1e-9:
            raise ValueError("normalized box must stay inside the frame")
        return self

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0


class LandmarkKind(StrEnum):
    FACE = "face"
    POSE = "pose"


class Landmark(StrictModel):
    """Anonymous geometry point; identity attributes are intentionally absent."""

    name: str = Field(min_length=1)
    kind: LandmarkKind
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class SubjectObservation(StrictModel):
    """One opaque, non-identifying subject observation."""

    subject_id: str = Field(min_length=1)
    box: NormalizedBox
    confidence: float = Field(ge=0.0, le=1.0)
    face_landmarks: tuple[Landmark, ...] = ()
    pose_landmarks: tuple[Landmark, ...] = ()

    @model_validator(mode="after")
    def landmark_kinds_match_buckets(self) -> SubjectObservation:
        if any(point.kind is not LandmarkKind.FACE for point in self.face_landmarks):
            raise ValueError("face_landmarks may contain only face landmarks")
        if any(point.kind is not LandmarkKind.POSE for point in self.pose_landmarks):
            raise ValueError("pose_landmarks may contain only pose landmarks")
        return self


class CameraMotion(StrictModel):
    """Caller-measured frame-to-frame camera motion."""

    dx: float
    dy: float
    rotation_degrees: float
    zoom_delta: float = 0.0
    confidence: float = Field(ge=0.0, le=1.0)


class SafeRegionKind(StrEnum):
    TEXT = "text"
    ACTION = "action"


class SafeRegion(StrictModel):
    region_id: str = Field(min_length=1)
    kind: SafeRegionKind
    box: NormalizedBox
    confidence: float = Field(ge=0.0, le=1.0)


class SourceVideo(StrictModel):
    sha256: str = Field(pattern=_SHA256_PATTERN)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_seconds: float = Field(gt=0.0)


class FrameEvidence(StrictModel):
    """Precomputed local evidence supplied to the pure V1 planner."""

    timestamp_seconds: float = Field(ge=0.0)
    subjects: tuple[SubjectObservation, ...] = ()
    camera_motion: CameraMotion
    safe_regions: tuple[SafeRegion, ...] = ()
    candidate_crop: NormalizedBox | None = None

    @model_validator(mode="after")
    def ids_are_unique(self) -> FrameEvidence:
        subject_ids = [subject.subject_id for subject in self.subjects]
        region_ids = [region.region_id for region in self.safe_regions]
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("subject ids must be unique within a frame")
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("safe region ids must be unique within a frame")
        return self


class TrackSample(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    box: NormalizedBox
    confidence: float = Field(ge=0.0, le=1.0)
    face_landmarks: tuple[Landmark, ...] = ()
    pose_landmarks: tuple[Landmark, ...] = ()


class SubjectTrack(StrictModel):
    subject_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    samples: tuple[TrackSample, ...]


class TrackingLoss(StrictModel):
    subject_id: str
    timestamp_seconds: float = Field(ge=0.0)
    reason: Literal["not_observed"] = "not_observed"


class MultiSubjectAmbiguity(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    subject_ids: tuple[str, ...]
    confidence_delta: float = Field(ge=0.0, le=1.0)
    reason: Literal["similar_detection_confidence"] = "similar_detection_confidence"


class TimedCameraMotion(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    dx: float
    dy: float
    rotation_degrees: float
    zoom_delta: float
    confidence: float = Field(ge=0.0, le=1.0)


class FrameSafeRegions(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    regions: tuple[SafeRegion, ...]


class CropLossEstimate(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    subject_id: str
    crop_box: NormalizedBox | None
    available: bool
    subject_loss: float | None = Field(default=None, ge=0.0, le=1.0)
    source_crop_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: Literal["primary_subject_not_observed", "candidate_crop_not_provided"] | None = None


class LandmarkCapabilities(StrictModel):
    face: bool
    pose: bool


class VisualAnalysisPlan(StrictModel):
    schema_version: Literal[1] = 1
    plan_kind: Literal["visual_analysis"] = "visual_analysis"
    execution_mode: Literal["planning_only"] = "planning_only"
    local_only: Literal[True] = True
    identity_inference: Literal[False] = False
    source: SourceVideo
    primary_subject_id: str
    frames: tuple[FrameEvidence, ...]
    subject_tracks: tuple[SubjectTrack, ...]
    tracking_losses: tuple[TrackingLoss, ...]
    ambiguities: tuple[MultiSubjectAmbiguity, ...]
    camera_motion: tuple[TimedCameraMotion, ...]
    safe_regions: tuple[FrameSafeRegions, ...]
    crop_loss_estimates: tuple[CropLossEstimate, ...]
    landmark_capabilities: LandmarkCapabilities
    plan_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_plan_hash(self) -> VisualAnalysisPlan:
        if self.plan_sha256 != canonical_sha256(self, exclude={"plan_sha256"}):
            raise ValueError("visual analysis plan hash does not match canonical content")
        return self


class CropBudget(StrictModel):
    max_subject_loss: float = Field(ge=0.0, le=1.0)
    max_source_crop_fraction: float = Field(ge=0.0, le=1.0)


class CropTarget(StrictModel):
    target_id: str = Field(min_length=1)
    aspect_width: int = Field(gt=0)
    aspect_height: int = Field(gt=0)
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)

    @model_validator(mode="after")
    def output_matches_declared_aspect(self) -> CropTarget:
        declared = self.aspect_width / self.aspect_height
        output = self.output_width / self.output_height
        if abs(declared - output) > 0.01:
            raise ValueError("output dimensions must match the declared target aspect ratio")
        return self


class CropTrackSample(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    crop_box: NormalizedBox
    subject_coverage: float = Field(ge=0.0, le=1.0)
    safe_region_coverage: float = Field(ge=0.0, le=1.0)
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)


class CropPreview(StrictModel):
    """Representative preview metadata; no image is rendered by the planner."""

    timestamp_seconds: float = Field(ge=0.0)
    crop_box: NormalizedBox
    subject_coverage: float = Field(ge=0.0, le=1.0)
    safe_region_coverage: float = Field(ge=0.0, le=1.0)


class CropVariantPlan(StrictModel):
    target_id: str
    status: Literal["ready", "abstained"]
    abstention_reasons: tuple[str, ...]
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)
    source_crop_fraction: float = Field(ge=0.0, le=1.0)
    maximum_subject_loss: float = Field(ge=0.0, le=1.0)
    crop_track: tuple[CropTrackSample, ...]
    previews: tuple[CropPreview, ...]


class ReframePlan(StrictModel):
    schema_version: Literal[1] = 1
    plan_kind: Literal["subject_aware_reframe"] = "subject_aware_reframe"
    execution_mode: Literal["planning_only"] = "planning_only"
    policy_id: Literal["local_visual_transform"] = "local_visual_transform"
    timeline_locked: Literal[True] = True
    network_allowed: Literal[False] = False
    source_overwrite_allowed: Literal[False] = False
    analysis_sha256: str = Field(pattern=_SHA256_PATTERN)
    source: SourceVideo
    primary_subject_id: str
    crop_budget: CropBudget
    min_tracking_confidence: float = Field(ge=0.0, le=1.0)
    max_center_step: float = Field(gt=0.0, le=1.0)
    variants: tuple[CropVariantPlan, ...]
    plan_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_plan_hash(self) -> ReframePlan:
        if self.plan_sha256 != canonical_sha256(self, exclude={"plan_sha256"}):
            raise ValueError("reframe plan hash does not match canonical content")
        return self


class StabilizationTransform(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    translate_x: float
    translate_y: float
    rotation_degrees: float
    zoom_delta: float


class StabilizationPlan(StrictModel):
    schema_version: Literal[1] = 1
    plan_kind: Literal["advanced_stabilization"] = "advanced_stabilization"
    execution_mode: Literal["planning_only"] = "planning_only"
    policy_id: Literal["local_visual_transform"] = "local_visual_transform"
    timeline_locked: Literal[True] = True
    sync_locked: Literal[True] = True
    network_allowed: Literal[False] = False
    source_overwrite_allowed: Literal[False] = False
    analysis_sha256: str = Field(pattern=_SHA256_PATTERN)
    source: SourceVideo
    primary_subject_id: str
    crop_budget: CropBudget
    min_tracking_confidence: float = Field(ge=0.0, le=1.0)
    compensation_ratio: float = Field(gt=0.0, le=1.0)
    status: Literal["ready", "abstained"]
    abstention_reasons: tuple[str, ...]
    transforms: tuple[StabilizationTransform, ...]
    required_crop_box: NormalizedBox | None
    source_crop_fraction: float = Field(ge=0.0, le=1.0)
    maximum_subject_loss: float = Field(ge=0.0, le=1.0)
    input_motion_score: float = Field(ge=0.0)
    expected_motion_reduction: float = Field(ge=0.0, le=1.0)
    plan_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_plan_hash(self) -> StabilizationPlan:
        if self.plan_sha256 != canonical_sha256(self, exclude={"plan_sha256"}):
            raise ValueError("stabilization plan hash does not match canonical content")
        return self


class CoverageSample(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    coverage: float = Field(ge=0.0, le=1.0)


class ResolutionSample(StrictModel):
    timestamp_seconds: float = Field(ge=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class MotionMeasurement(StrictModel):
    before_score: float = Field(ge=0.0)
    after_score: float = Field(ge=0.0)


class BorderMeasurement(StrictModel):
    total_frames: int = Field(gt=0)
    frames_with_borders: int = Field(ge=0)

    @model_validator(mode="after")
    def border_count_fits_total(self) -> BorderMeasurement:
        if self.frames_with_borders > self.total_frames:
            raise ValueError("frames_with_borders must not exceed total_frames")
        return self


class TimelineSyncMeasurement(StrictModel):
    source_duration_seconds: float = Field(gt=0.0)
    output_duration_seconds: float = Field(gt=0.0)
    source_av_offset_seconds: float
    output_av_offset_seconds: float


class VerificationCheck(StrictModel):
    verifier_id: str
    passed: bool
    gating: Literal[True] = True
    measured: float
    required: float
    failure_codes: tuple[str, ...] = ()


def canonical_sha256(model: BaseModel, *, exclude: set[str] | None = None) -> str:
    """Hash a model using a stable JSON representation."""

    payload = model.model_dump(mode="json", exclude=exclude or set())
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
