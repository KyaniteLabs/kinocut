"""Feature-specific evidence models for restorative promotion decisions."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from .contracts import ModelProvenance, RestorativeFeature, Sha256, _FrozenModel, _SHA256_PATTERN


class NoiseType(StrEnum):
    WIND = "wind"
    HUM = "hum"
    ECHO = "echo"
    BROADBAND = "broadband"
    MIXED = "mixed"


class RestorativeEvidence(_FrozenModel):
    feature: RestorativeFeature
    evidence_contract_id: str
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    output_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    sample_count: int = Field(ge=1)
    model_provenance: ModelProvenance | None = None


class SpeechDenoiseEvidence(RestorativeEvidence):
    feature: Literal[RestorativeFeature.SPEECH_DENOISE] = RestorativeFeature.SPEECH_DENOISE
    evidence_contract_id: Literal["speech_denoise.evidence.v1"] = "speech_denoise.evidence.v1"
    noise_type: NoiseType
    noise_before_dbfs: float
    noise_after_dbfs: float
    snr_before_db: float
    snr_after_db: float
    intelligibility_before: float = Field(ge=0.0, le=1.0)
    intelligibility_after: float = Field(ge=0.0, le=1.0)
    speech_coverage_before: float = Field(ge=0.0, le=1.0)
    speech_coverage_after: float = Field(ge=0.0, le=1.0)


class AdvancedColorHDREvidence(RestorativeEvidence):
    feature: Literal[RestorativeFeature.ADVANCED_COLOR_HDR] = RestorativeFeature.ADVANCED_COLOR_HDR
    evidence_contract_id: Literal["advanced_color_hdr.evidence.v1"] = "advanced_color_hdr.evidence.v1"
    calibrated: bool
    calibration_profile: str = Field(min_length=1)
    input_color_space: str = Field(min_length=1)
    output_color_space: str = Field(min_length=1)
    delivery_color_space: str = Field(min_length=1)
    out_of_gamut_fraction: float = Field(ge=0.0, le=1.0)
    clipping_before_fraction: float = Field(ge=0.0, le=1.0)
    clipping_after_fraction: float = Field(ge=0.0, le=1.0)
    neutral_delta_e: float = Field(ge=0.0)
    neutral_sample_count: int = Field(ge=1)
    skin_delta_e: float = Field(ge=0.0)
    skin_sample_count: int = Field(ge=1)


class FrameRepairEvidence(RestorativeEvidence):
    feature: Literal[RestorativeFeature.FRAME_REPAIR] = RestorativeFeature.FRAME_REPAIR
    evidence_contract_id: Literal["frame_repair.evidence.v1"] = "frame_repair.evidence.v1"
    model_provenance: ModelProvenance  # pyright: ignore[reportGeneralTypeIssues]
    repair_kind: Literal["deblur", "upscale", "frame_repair"]
    temporal_consistency_score: float = Field(ge=0.0, le=1.0)
    identity_continuity_score: float = Field(ge=0.0, le=1.0)
    object_continuity_score: float = Field(ge=0.0, le=1.0)
    source_detail_coverage: float = Field(ge=0.0, le=1.0)
    invented_detail_detected: bool
    invented_detail_claimed: bool


class BackgroundRepairEvidence(RestorativeEvidence):
    feature: Literal[RestorativeFeature.BACKGROUND_REPAIR] = RestorativeFeature.BACKGROUND_REPAIR
    evidence_contract_id: Literal["background_repair.evidence.v1"] = "background_repair.evidence.v1"
    segmentation_confidence: float = Field(ge=0.0, le=1.0)
    foreground_coverage_before: float = Field(ge=0.0, le=1.0)
    foreground_coverage_after: float = Field(ge=0.0, le=1.0)
    foreground_object_coverage: float = Field(ge=0.0, le=1.0)
    edge_temporal_stability: float = Field(ge=0.0, le=1.0)
    invented_background: bool


class StyledCaptionEvidence(RestorativeEvidence):
    feature: Literal[RestorativeFeature.STYLED_CAPTIONS] = RestorativeFeature.STYLED_CAPTIONS
    evidence_contract_id: Literal["styled_captions.evidence.v1"] = "styled_captions.evidence.v1"
    style_approved: bool
    minimum_contrast_ratio: float = Field(ge=1.0)
    clipped_caption_count: int = Field(ge=0)
    safe_zone_coverage: float = Field(ge=0.0, le=1.0)
    timing_valid: bool
    maximum_timing_drift_ms: int = Field(ge=0)


Evidence = (
    SpeechDenoiseEvidence
    | AdvancedColorHDREvidence
    | FrameRepairEvidence
    | BackgroundRepairEvidence
    | StyledCaptionEvidence
)
