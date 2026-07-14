"""Capability-gated, side-effect-free boundary for optional visual analyzers."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError, field_validator, model_validator

from kinocut.aivideo.inspection.manifest import (
    InspectionPackage,
    ProviderCapabilityResult,
)
from kinocut.contracts._common import NormalizedRegion, Sha256, ValueObject
from kinocut.contracts.defect import (
    DefectCode,
    DefectFinding,
    Measurement,
    Severity,
)
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_VIDEO_DURATION

logger = logging.getLogger(__name__)

VisualCapabilityId = Literal[
    "visual.motion_intent",
    "visual.generative_defects",
]
AnalysisStatus = Literal["complete", "capability_unavailable"]

VISUAL_CAPABILITIES: tuple[VisualCapabilityId, ...] = (
    "visual.motion_intent",
    "visual.generative_defects",
)
_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VISUAL_DEFECT_CODES = frozenset(
    {
        DefectCode.TEXT_DRIFT,
        DefectCode.IDENTITY_DRIFT,
        DefectCode.OBJECT_MUTATION,
        DefectCode.WARPING,
        DefectCode.FLICKER,
        DefectCode.UNWANTED_CAMERA_MOTION,
        DefectCode.CONTINUITY_FAILURE,
        DefectCode.LATE_FRAME_DEGRADATION,
    }
)


class ProviderFindingProposal(ValueObject):
    """Strict provider proposal; lifecycle fields are intentionally absent."""

    defect_code: DefectCode
    time_range: tuple[float, float]
    spatial_region: NormalizedRegion | None = None
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    measurements: tuple[Measurement, ...] = ()
    evidence_artifact_ids: tuple[Sha256, ...] = ()

    @model_validator(mode="after")
    def _is_bounded_visual_finding(self) -> ProviderFindingProposal:
        start, end = self.time_range
        if start < 0.0 or end <= start:
            raise ValueError("time_range must be a positive, nonnegative range")
        if self.defect_code not in _VISUAL_DEFECT_CODES:
            raise ValueError("provider defect code is outside the visual taxonomy")
        if len(set(self.evidence_artifact_ids)) != len(self.evidence_artifact_ids):
            raise ValueError("evidence artifact ids must be unique")
        if not self.evidence_artifact_ids:
            raise ValueError("provider findings require inspection evidence")
        if any(
            _PROVIDER_ID_RE.fullmatch(item.name) is None or _PROVIDER_ID_RE.fullmatch(item.unit) is None
            for item in self.measurements
        ):
            raise ValueError("measurement names and units must be bounded codes")
        return self


class ProviderFindingBatch(ValueObject):
    """Provider envelope binding findings to one identity and capability."""

    provider_id: str
    capability_id: VisualCapabilityId
    findings: tuple[ProviderFindingProposal, ...] = ()

    @field_validator("provider_id")
    @classmethod
    def _provider_id_is_code(cls, value: str) -> str:
        if _PROVIDER_ID_RE.fullmatch(value) is None:
            raise ValueError("provider id must be a bounded code")
        return value


class VisualFindingsProvider(Protocol):
    """Internal adapter contract; providers are constructed only by the registry."""

    provider_id: str
    capability_ids: tuple[VisualCapabilityId, ...]

    def analyze(
        self, package: InspectionPackage, capability_id: VisualCapabilityId
    ) -> ProviderFindingBatch | Mapping[str, Any]: ...


ProviderFactory = Callable[[], VisualFindingsProvider]


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    """Code-owned provider constructor definition."""

    provider_id: str
    factory: ProviderFactory


class ProviderRegistry:
    """Immutable id-to-constructor registry; never resolves imports or URLs."""

    def __init__(self, definitions: Iterable[ProviderDefinition] = ()) -> None:
        indexed: dict[str, ProviderDefinition] = {}
        for definition in definitions:
            if _PROVIDER_ID_RE.fullmatch(definition.provider_id) is None:
                raise _provider_error("inspection_provider_registry_invalid")
            if definition.provider_id in indexed or not callable(definition.factory):
                raise _provider_error("inspection_provider_registry_invalid")
            indexed[definition.provider_id] = definition
        self._definitions = MappingProxyType(indexed)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        """Return installed identifiers in deterministic order."""

        return tuple(sorted(self._definitions))

    def resolve(self, provider_id: str) -> ProviderDefinition | None:
        """Resolve a bounded static identifier without dynamic loading."""

        if _PROVIDER_ID_RE.fullmatch(provider_id) is None:
            raise _provider_error("inspection_provider_id_invalid")
        return self._definitions.get(provider_id)


class VisualProviderAnalysis(ValueObject):
    """Normalized result with explicit optional-capability availability."""

    status: AnalysisStatus
    provider_id: str | None
    playable_end: float = Field(gt=0.0, le=MAX_VIDEO_DURATION)
    capability: ProviderCapabilityResult
    findings: tuple[DefectFinding, ...] = ()

    @model_validator(mode="after")
    def _status_matches_capability(self) -> VisualProviderAnalysis:
        if self.status == "complete" and not self.capability.available:
            raise ValueError("complete analysis requires an available capability")
        if self.status == "capability_unavailable" and self.capability.available:
            raise ValueError("unavailable analysis requires an unavailable capability")
        if not self.capability.available and self.findings:
            raise ValueError("unavailable analysis cannot carry findings")
        if any(finding.time_range[1] > self.playable_end for finding in self.findings):
            raise ValueError("provider findings must stay within the playable extent")
        return self


VISUAL_PROVIDER_REGISTRY = ProviderRegistry()


def analyze_optional_visual_findings(
    package: InspectionPackage,
    *,
    playable_end: float,
    capability_id: VisualCapabilityId,
    provider_id: str | None,
    project_id: str,
    created_by: str,
    registry: ProviderRegistry = VISUAL_PROVIDER_REGISTRY,
) -> VisualProviderAnalysis:
    """Run one explicitly configured analyzer and normalize untrusted output."""

    if (
        isinstance(playable_end, bool)
        or not isinstance(playable_end, (int, float))
        or not math.isfinite(playable_end)
        or playable_end <= 0.0
        or playable_end > MAX_VIDEO_DURATION
    ):
        raise _provider_error("inspection_provider_request_invalid")
    trusted_end = float(playable_end)
    if capability_id not in VISUAL_CAPABILITIES:
        raise _provider_error("inspection_capability_invalid")
    if provider_id is None:
        return _unavailable(capability_id, None, trusted_end, "provider_not_configured")
    definition = registry.resolve(provider_id)
    if definition is None:
        return _unavailable(capability_id, provider_id, trusted_end, "provider_not_installed")
    provider = _construct_provider(definition)
    if provider is None:
        return _unavailable(capability_id, provider_id, trusted_end, "provider_failed")
    if capability_id not in provider.capability_ids:
        return _unavailable(capability_id, provider_id, trusted_end, "capability_not_supported")
    try:
        raw_batch = provider.analyze(package, capability_id)
    except Exception as exc:
        logger.warning(
            "optional visual findings provider failed: %s (%s)",
            provider_id,
            type(exc).__name__,
        )
        return _unavailable(capability_id, provider_id, trusted_end, "provider_failed")
    batch = _validate_batch(raw_batch, provider_id, capability_id, package, trusted_end)
    try:
        findings = _normalize_findings(batch, package, project_id, created_by)
    except ValidationError as exc:
        raise _provider_error("inspection_provider_request_invalid") from exc
    return VisualProviderAnalysis(
        status="complete",
        provider_id=provider_id,
        playable_end=trusted_end,
        capability=ProviderCapabilityResult(capability_id=capability_id, available=True),
        findings=findings,
    )


def _construct_provider(
    definition: ProviderDefinition,
) -> VisualFindingsProvider | None:
    try:
        provider = definition.factory()
    except Exception as exc:
        logger.warning(
            "optional visual provider construction failed: %s (%s)",
            definition.provider_id,
            type(exc).__name__,
        )
        return None
    try:
        provider_id = provider.provider_id
        capabilities = provider.capability_ids
        analyze = provider.analyze
    except Exception as exc:
        logger.warning(
            "optional visual provider contract failed: %s (%s)",
            definition.provider_id,
            type(exc).__name__,
        )
        raise _provider_error("inspection_provider_invalid") from exc
    valid_capabilities = (
        isinstance(capabilities, tuple)
        and len(capabilities) == len(set(capabilities))
        and all(item in VISUAL_CAPABILITIES for item in capabilities)
    )
    if provider_id != definition.provider_id or not valid_capabilities or not callable(analyze):
        raise _provider_error("inspection_provider_invalid")
    return provider


def _validate_batch(
    raw_batch: object,
    provider_id: str,
    capability_id: VisualCapabilityId,
    package: InspectionPackage,
    playable_end: float,
) -> ProviderFindingBatch:
    try:
        batch = ProviderFindingBatch.model_validate(raw_batch)
    except (ValidationError, TypeError, ValueError) as exc:
        raise _provider_error("inspection_provider_output_invalid") from exc
    evidence_ids = _inspection_artifact_ids(package)
    valid_binding = batch.provider_id == provider_id and batch.capability_id == capability_id
    valid_evidence = all(set(proposal.evidence_artifact_ids) <= evidence_ids for proposal in batch.findings)
    valid_times = all(proposal.time_range[1] <= playable_end for proposal in batch.findings)
    if not valid_binding or not valid_evidence or not valid_times:
        raise _provider_error("inspection_provider_output_invalid")
    return batch


def _inspection_artifact_ids(package: InspectionPackage) -> set[str]:
    direct = (package.technical_metadata, package.preview, package.muted_preview)
    ids = {item.artifact_id for item in direct if item is not None}
    if package.motion_strip is not None:
        ids.add(package.motion_strip.artifact.artifact_id)
    ids.update(item.artifact.artifact_id for item in package.sampled_frames)
    ids.update(item.artifact.artifact_id for item in package.region_crops)
    ids.update(item.artifact_id for item in package.frame_difference_measurements)
    return ids


def _normalize_findings(
    batch: ProviderFindingBatch,
    package: InspectionPackage,
    project_id: str,
    created_by: str,
) -> tuple[DefectFinding, ...]:
    findings = tuple(
        DefectFinding(
            project_id=project_id,
            created_by=created_by,
            defect_code=proposal.defect_code,
            target_id=package.source_asset_id,
            time_range=proposal.time_range,
            spatial_region=proposal.spatial_region,
            severity=proposal.severity,
            confidence=proposal.confidence,
            detector=f"provider.{batch.provider_id}.{batch.capability_id}",
            measurements=proposal.measurements,
            evidence_artifact_ids=proposal.evidence_artifact_ids,
        )
        for proposal in batch.findings
    )
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.time_range,
                finding.defect_code.value,
                finding.severity.value,
                finding.confidence,
                finding.evidence_artifact_ids,
            ),
        )
    )


def _unavailable(
    capability_id: VisualCapabilityId,
    provider_id: str | None,
    playable_end: float,
    reason_code: str,
) -> VisualProviderAnalysis:
    return VisualProviderAnalysis(
        status="capability_unavailable",
        provider_id=provider_id,
        playable_end=playable_end,
        capability=ProviderCapabilityResult(
            capability_id=capability_id,
            available=False,
            reason_code=reason_code,
        ),
    )


def _provider_error(code: str) -> MCPVideoError:
    return MCPVideoError(
        "Optional visual inspection provider data is invalid.",
        error_type="validation_error",
        code=code,
    )
