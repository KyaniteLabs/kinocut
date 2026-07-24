"""Strict package contracts and canonical manifest helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.errors import MCPVideoError

from .captions import CaptionArtifact
from .models import CandidateMoment

PerformanceStatus = Literal["draft", "experimental"]

_PACKAGE_KIND = "shorts_package"
package_kind: str = _PACKAGE_KIND

_DRAFTING_ONLY_TAGS: tuple[str, ...] = ("suggested_title", "suggested_hook", "short_description")


class ThumbnailSpec(ValueObject):
    """Representative thumbnail chosen for an approved clip."""

    image_path: str = Field(min_length=1)
    timestamp: float = Field(ge=0.0)
    notes: str | None = None


class PerformanceIdentifier(ValueObject):
    """Optional drafting-only performance identifier."""

    status: PerformanceStatus
    label: str = Field(min_length=1, max_length=64)


class PackageConfig(ValueObject):
    """Controls deterministic package writing."""

    manifest_basename: str = Field(default="manifest", min_length=1, max_length=64)
    overwrite_manifest: bool = False
    write_thumbnail_marker: bool = True


class PackageAsset(ValueObject):
    """Portable package asset with a bounded role."""

    role: Literal[
        "vertical_video",
        "editable_subtitles",
        "representative_thumbnail",
        "edit_manifest",
        "performance_identifier",
    ]
    relative_path: str = Field(min_length=1)
    bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _no_traversal_in_path(self) -> PackageAsset:
        normalized = self.relative_path.replace("\\", "/")
        drive_path = len(normalized) > 1 and normalized[0].isalpha() and normalized[1] == ":"
        if normalized.startswith("/") or drive_path or ".." in normalized.split("/"):
            raise ValueError(f"asset path escapes package root: {self.relative_path!r}")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError(f"asset path contains control character: {self.relative_path!r}")
        return self


class PackageLineage(ValueObject):
    """Provenance references for the packaged clip."""

    candidate_id: str = Field(min_length=1)
    transcript_reference: str | None = None
    generation_lineage_ref: str | None = None
    review_decision_ref: str | None = None


class ShortsPackageManifest(ValueObject):
    """Machine-readable, JSON-stable edit manifest."""

    schema_version: int = Field(default=1, ge=1, le=1)
    package_kind: Literal["shorts_package"] = _PACKAGE_KIND
    package_id: str = Field(min_length=1)
    package_root: str = Field(min_length=1)
    generated_at: str | None = None
    candidate: CandidateMoment
    caption_artifact: CaptionArtifact
    suggested_title: str | None = None
    short_description: str | None = None
    source_timestamps: tuple[float, float] | None = None
    thumbnail: ThumbnailSpec
    lineage: PackageLineage
    assets: tuple[PackageAsset, ...]
    review_warnings: tuple[str, ...]
    drafting_only_flags: tuple[str, ...] = tuple(_DRAFTING_ONLY_TAGS)
    performance: PerformanceIdentifier | None = None

    @field_validator("schema_version", mode="before")
    @classmethod
    def _strict_schema_version(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("schema_version must be the integer 1")
        return value


class PackagedClipResult(ValueObject):
    """Deterministic package writer result."""

    package_root: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    asset_paths: tuple[str, ...]
    manifest: ShortsPackageManifest


def parse_package_manifest(payload: str | bytes) -> ShortsPackageManifest:
    """Parse a JSON-encoded manifest. Bytes payloads are decoded UTF-8 strict."""

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise MCPVideoError(
                "manifest payload is not valid UTF-8",
                error_type="validation_error",
                code="invalid_manifest_encoding",
            ) from exc
    try:
        data: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MCPVideoError(
            "manifest payload is not valid JSON",
            error_type="validation_error",
            code="invalid_manifest_json",
        ) from exc
    return ShortsPackageManifest.model_validate(data)


def canonical_manifest_bytes(manifest: ShortsPackageManifest) -> bytes:
    """Render a manifest to canonical JSON bytes."""

    payload = manifest.model_dump(mode="json")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def manifest_artifact_digest(manifest: ShortsPackageManifest) -> str:
    """Stable 16-hex prefix of the manifest's canonical digest."""

    digest = hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
    return digest[:16]


__all__ = [
    "PackageAsset",
    "PackageConfig",
    "PackageLineage",
    "PackagedClipResult",
    "PerformanceIdentifier",
    "PerformanceStatus",
    "ShortsPackageManifest",
    "ThumbnailSpec",
    "canonical_manifest_bytes",
    "manifest_artifact_digest",
    "package_kind",
    "parse_package_manifest",
]
