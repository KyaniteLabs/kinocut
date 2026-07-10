"""Observed-evidence contracts for independent composition verification."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .composition_models import OutputArtifact
from .models import _SHA256_PATTERN, _STABLE_ID_PATTERN, CreativeModel, Sha256


class AttributionEvidence(CreativeModel):
    asset_id: str = Field(pattern=_STABLE_ID_PATTERN)
    span_id: str | None = Field(default=None, pattern=_STABLE_ID_PATTERN)


class TimelineObservation(CreativeModel):
    segment_id: str = Field(pattern=_STABLE_ID_PATTERN)
    output_start_seconds: float = Field(ge=0.0)
    output_end_seconds: float = Field(gt=0.0)
    selected_span_ids: tuple[str, ...]


class AudioObservation(CreativeModel):
    track_id: str = Field(pattern=_STABLE_ID_PATTERN)
    integrated_lufs: float = Field(ge=-70.0, le=0.0)
    peak_dbfs: float = Field(ge=-70.0, le=0.0)


class TextObservation(CreativeModel):
    element_id: str = Field(pattern=_STABLE_ID_PATTERN)
    rendered_text: str
    inside_safe_area: bool
    readable: bool


class BrandingObservation(CreativeModel):
    logo_asset_ids: tuple[str, ...] = ()
    font_asset_ids: tuple[str, ...] = ()
    colors: tuple[str, ...] = ()
    rendered_text: tuple[str, ...] = ()


class OutputPackageEvidence(CreativeModel):
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    artifacts: tuple[OutputArtifact, ...]


class VerificationEvidence(CreativeModel):
    attributions: tuple[AttributionEvidence, ...]
    timeline: tuple[TimelineObservation, ...]
    audio: tuple[AudioObservation, ...]
    text: tuple[TextObservation, ...]
    branding: BrandingObservation
    package: OutputPackageEvidence


class CompositionVerificationCheck(CreativeModel):
    id: str
    passed: bool
    gating: Literal[True] = True
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class CompositionVerificationReport(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_composition_verification"] = "creative_composition_verification"
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    passed: bool
    checks: tuple[CompositionVerificationCheck, ...]
    report_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
