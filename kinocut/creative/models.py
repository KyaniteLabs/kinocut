"""Versioned, immutable contracts for source-backed creative planning."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = str
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_STABLE_ID_PATTERN = r"^[a-z][a-z0-9_]*:[a-z0-9][a-z0-9_-]*$"


class CreativeModel(BaseModel):
    """Strict base for artifacts whose serialized shape is a public contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def canonical_digest(model: BaseModel, *, exclude: set[str]) -> Sha256:
    """Hash canonical JSON without timestamps or environment-dependent state."""

    payload = model.model_dump(mode="json", exclude=exclude)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def relative_reference(value: str) -> str:
    """Validate a portable artifact reference without touching the filesystem."""

    if not value or "\x00" in value or Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("path reference must be a non-empty relative path")
    return value


class AssetRights(CreativeModel):
    status: Literal["cleared", "restricted", "unknown"]
    provenance: str = Field(min_length=1)
    license_id: str | None = None
    attribution_required: bool
    attribution_text: str | None = None

    @model_validator(mode="after")
    def require_attribution_text(self) -> AssetRights:
        if self.attribution_required and not self.attribution_text:
            raise ValueError("attribution-required assets need attribution_text")
        return self


class SemanticSpan(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    kind: Literal["transcript", "shot", "scene", "audio_event", "visual"]
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: str = Field(min_length=1)
    text: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> SemanticSpan:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("semantic span end_seconds must be greater than start_seconds")
        return self


class QualityFinding(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    kind: str = Field(min_length=1)
    severity: Literal["info", "advisory", "blocking"]
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[str, ...] = Field(min_length=1)


class RoleCandidate(CreativeModel):
    role: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)
    span_ids: tuple[str, ...] = ()


class CreativeAsset(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    path: str
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    media_kind: Literal["video", "audio", "image", "font", "captions"]
    rights: AssetRights
    semantic_spans: tuple[SemanticSpan, ...] = ()
    quality_findings: tuple[QualityFinding, ...] = ()
    role_candidates: tuple[RoleCandidate, ...] = ()
    user_supplied: bool

    _validate_path = field_validator("path")(relative_reference)

    @model_validator(mode="after")
    def validate_local_references(self) -> CreativeAsset:
        span_ids = tuple(span.id for span in self.semantic_spans)
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("semantic span ids must be unique within an asset")
        finding_ids = tuple(item.id for item in self.quality_findings)
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("quality finding ids must be unique within an asset")
        known_spans = set(span_ids)
        for candidate in self.role_candidates:
            if not set(candidate.span_ids).issubset(known_spans):
                raise ValueError("role candidate references unknown semantic span")
        return self


class BrandConstraints(CreativeModel):
    logo_asset_ids: tuple[str, ...] = ()
    music_asset_ids: tuple[str, ...] = ()
    font_asset_ids: tuple[str, ...] = ()
    caption_asset_ids: tuple[str, ...] = ()
    required_colors: tuple[str, ...] = ()
    required_text: tuple[str, ...] = ()
    forbidden_text: tuple[str, ...] = ()

    @field_validator("required_colors")
    @classmethod
    def validate_colors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if any(re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None for value in values):
            raise ValueError("required colors must use six-digit hex notation")
        return values

    def referenced_asset_ids(self) -> tuple[str, ...]:
        return self.logo_asset_ids + self.music_asset_ids + self.font_asset_ids + self.caption_asset_ids


class ProjectManifest(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_project_manifest"] = "creative_project_manifest"
    project_id: str = Field(pattern=_STABLE_ID_PATTERN)
    assets: tuple[CreativeAsset, ...]
    brand_constraints: BrandConstraints = Field(default_factory=BrandConstraints)
    manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_project_references(self) -> ProjectManifest:
        asset_ids = tuple(asset.id for asset in self.assets)
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset ids must be unique")
        all_span_ids = tuple(span.id for asset in self.assets for span in asset.semantic_spans)
        if len(all_span_ids) != len(set(all_span_ids)):
            raise ValueError("semantic span ids must be unique across the project")
        if not set(self.brand_constraints.referenced_asset_ids()).issubset(set(asset_ids)):
            raise ValueError("brand constraint references unknown asset")
        return self


class SelectionIntent(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    query: str = Field(min_length=1)
    required_roles: tuple[str, ...] = Field(min_length=1)

    @field_validator("required_roles")
    @classmethod
    def unique_roles(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("required roles must be unique")
        return values


class SelectionEvidence(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    role: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    asset_id: str = Field(pattern=_STABLE_ID_PATTERN)
    span_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)
    source: str = Field(min_length=1)


class AssetSelection(CreativeModel):
    role: str
    asset_id: str
    span_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class SelectionAbstention(CreativeModel):
    role: str
    code: Literal["source_evidence_absent", "rights_not_cleared", "confidence_below_threshold"]
    reason: str = Field(min_length=1)


class SelectionPlan(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_asset_selection"] = "creative_asset_selection"
    manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    intent: SelectionIntent
    selections: tuple[AssetSelection, ...]
    abstentions: tuple[SelectionAbstention, ...]
    selection_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)


def dump_contract(model: BaseModel) -> dict[str, Any]:
    """Return the JSON-compatible contract payload for callers and receipts."""

    return model.model_dump(mode="json")
