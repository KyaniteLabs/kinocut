"""Typed, deterministic, privacy-safe temporal inspection manifests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, StrictBool, computed_field, field_validator, model_validator

from kinocut.contracts._common import AssetId, NormalizedRegion, Sha256, ValueObject
from kinocut.contracts._paths import location_violation
from kinocut.errors import MCPVideoError
from kinocut.projectstore import Project, layout, store

_CODE_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


class ArtifactRef(ValueObject):
    """A content-addressed artifact reference with no absolute host path."""

    artifact_id: Sha256
    kind: str
    location: str

    @field_validator("kind")
    @classmethod
    def _kind_is_code(cls, value: str) -> str:
        if _CODE_RE.fullmatch(value) is None:
            raise ValueError("kind must be a bounded lowercase code")
        return value

    @model_validator(mode="after")
    def _location_matches_identity(self) -> ArtifactRef:
        if location_violation(self.location) is not None:
            raise ValueError("artifact location must be project-relative")
        path = PurePosixPath(self.location)
        expected = layout.artifact_relative_path(self.artifact_id, path.name)
        if path != expected:
            raise ValueError("artifact location must match its content identity")
        return self


class TimestampedArtifactRef(ValueObject):
    """A sampled frame reference tied to a decoded media timestamp."""

    artifact: ArtifactRef
    timestamp: float = Field(ge=0.0)
    labels: tuple[str, ...]

    @field_validator("labels")
    @classmethod
    def _labels_are_policy_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {"0", "25", "50", "75", "95", "last"}
        if not value or len(set(value)) != len(value) or any(v not in allowed for v in value):
            raise ValueError("labels must be unique approved sampling labels")
        return value


class RegionCropArtifactRef(ValueObject):
    """A source-resolution crop tied to its region and decoded timestamp."""

    artifact: ArtifactRef
    timestamp: float = Field(ge=0.0)
    name: str
    region: NormalizedRegion

    @field_validator("name")
    @classmethod
    def _name_is_code(cls, value: str) -> str:
        if _CODE_RE.fullmatch(value) is None:
            raise ValueError("region name must be a bounded lowercase code")
        return value


class MotionStripArtifactRef(ValueObject):
    """A tiled strip and the exact decoded timestamps represented in it."""

    artifact: ArtifactRef
    sample_timestamps: tuple[float, ...]

    @field_validator("sample_timestamps")
    @classmethod
    def _timestamps_are_ordered(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not value or any(v < 0.0 for v in value) or tuple(sorted(set(value))) != value:
            raise ValueError("sample timestamps must be unique and ascending")
        return value


class ProviderCapabilityResult(ValueObject):
    """Availability result for one optional inspection analyzer."""

    capability_id: str
    available: StrictBool
    reason_code: str | None = None

    @field_validator("capability_id", "reason_code")
    @classmethod
    def _codes_are_bounded(cls, value: str | None) -> str | None:
        if value is not None and _CODE_RE.fullmatch(value) is None:
            raise ValueError("capability values must be bounded lowercase codes")
        return value

    @model_validator(mode="after")
    def _availability_is_coherent(self) -> ProviderCapabilityResult:
        if self.available == (self.reason_code is not None):
            raise ValueError("only unavailable capabilities carry a reason code")
        return self


class InspectionPackage(ValueObject):
    """Deterministic manifest over every temporal-inspection artifact."""

    schema_version: Literal[1] = 1
    source_asset_id: AssetId
    technical_metadata: ArtifactRef | None = None
    preview: ArtifactRef | None = None
    muted_preview: ArtifactRef | None = None
    motion_strip: MotionStripArtifactRef | None = None
    sampled_frames: tuple[TimestampedArtifactRef, ...] = ()
    region_crops: tuple[RegionCropArtifactRef, ...] = ()
    frame_difference_measurements: tuple[ArtifactRef, ...] = ()
    findings: tuple[Sha256, ...] = ()
    capabilities: tuple[ProviderCapabilityResult, ...] = ()

    @computed_field
    @property
    def unavailable_capabilities(self) -> tuple[str, ...]:
        """Every unavailable optional analyzer, explicitly and stably ordered."""

        return tuple(item.capability_id for item in self.capabilities if not item.available)

    @model_validator(mode="after")
    def _capabilities_are_unique(self) -> InspectionPackage:
        ids = [item.capability_id for item in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("capability ids must be unique")
        return self


def _canonical_bytes(package: InspectionPackage) -> bytes:
    return json.dumps(
        package.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def persist_inspection_package(project: Project, package: InspectionPackage) -> ArtifactRef:
    """Persist canonical manifest bytes at their content-derived location."""

    content = _canonical_bytes(package)
    artifact_id = "sha256:" + hashlib.sha256(content).hexdigest()
    relative = layout.artifact_relative_path(artifact_id, "inspection.json")
    target = store.safe_target(project, relative)
    try:
        with store._project_lock(project):
            if target.exists() and target.read_bytes() != content:
                raise MCPVideoError(
                    "inspection manifest content does not match its identity",
                    error_type="store_error",
                    code="inspection_manifest_mismatch",
                )
            if not target.exists():
                store._atomic_write(target, content.decode("utf-8"))
    except OSError as exc:
        raise MCPVideoError(
            "inspection manifest could not be stored",
            error_type="store_error",
            code="inspection_manifest_store_failed",
        ) from exc
    return ArtifactRef(
        artifact_id=artifact_id,
        kind="inspection_manifest",
        location=str(relative),
    )
