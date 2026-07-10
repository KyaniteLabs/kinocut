"""Deterministic, planning-only visual intelligence contracts."""

from .analysis import plan_visual_analysis
from .models import (
    CameraMotion,
    CropBudget,
    CropTarget,
    FrameEvidence,
    Landmark,
    LandmarkKind,
    NormalizedBox,
    SafeRegion,
    SafeRegionKind,
    SourceVideo,
    SubjectObservation,
    VisualAnalysisPlan,
)
from .reframe import plan_subject_aware_reframe
from .stabilization import plan_stabilization
from .verification import (
    verify_borders,
    verify_crop_continuity,
    verify_crop_resolution,
    verify_duration_and_sync,
    verify_motion_reduction,
    verify_safe_zone_coverage,
    verify_subject_coverage,
)

__all__ = [
    "CameraMotion",
    "CropBudget",
    "CropTarget",
    "FrameEvidence",
    "Landmark",
    "LandmarkKind",
    "NormalizedBox",
    "SafeRegion",
    "SafeRegionKind",
    "SourceVideo",
    "SubjectObservation",
    "VisualAnalysisPlan",
    "plan_stabilization",
    "plan_subject_aware_reframe",
    "plan_visual_analysis",
    "verify_borders",
    "verify_crop_continuity",
    "verify_crop_resolution",
    "verify_duration_and_sync",
    "verify_motion_reduction",
    "verify_safe_zone_coverage",
    "verify_subject_coverage",
]
