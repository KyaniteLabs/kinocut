"""``AssetRecord`` and ``GenerationLineage`` (design §4.3).

Media identities are byte-hash asset ids. Provenance is stored by hash, never
raw prompt text. Original locations are project-relative — never home paths or
absolute paths that could leak the host filesystem.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from kinocut.contracts._common import (
    AssetId,
    RecordBase,
    Sha256,
    ValueObject,
)
from kinocut.contracts._paths import location_violation


class MediaKind(StrEnum):
    """The closed set of media kinds an asset may hold."""

    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    SUBTITLE = "subtitle"


class UsageRightsStatus(StrEnum):
    """Rights posture for an asset; evidence is referenced privately."""

    CLEARED = "cleared"
    PENDING = "pending"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class GenerationLineage(ValueObject):
    """How a generated asset came to be — provenance stored by hash only."""

    # Revalidate instances so a lineage that bypassed validation (e.g. via
    # ``model_construct``) and is passed straight into an ``AssetRecord`` payload
    # is fully re-checked at the store boundary rather than trusted as-is.
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always")

    generator_model: str
    provider_id: str
    prompt_hash: Sha256 | None = None
    generation_settings_hash: Sha256 | None = None
    source_asset_ids: tuple[AssetId, ...] = ()
    reference_asset_ids: tuple[AssetId, ...] = ()


class AssetRecord(RecordBase):
    """A content-addressed media asset and its provenance (design §4.3)."""

    record_kind: Literal["asset_record"] = "asset_record"

    asset_id: AssetId
    media_kind: MediaKind
    original_location: str = Field(min_length=1)
    byte_size: int = Field(ge=0, strict=True)
    ingest_time: str | None = None
    preflight_summary: str | None = None
    preflight_artifact_id: Sha256 | None = None
    usage_rights_status: UsageRightsStatus = UsageRightsStatus.UNKNOWN
    usage_rights_evidence_ref: str | None = None
    lineage: GenerationLineage | None = None
    parent_asset_id: AssetId | None = None
    variant_of: AssetId | None = None
    derived_artifact_ids: tuple[Sha256, ...] = ()

    @field_validator("original_location")
    @classmethod
    def _must_be_project_relative(cls, value: str) -> str:
        """Reject absolute, home, URL, traversing, or control-char locations.

        Delegates to the shared ``location_violation`` rule so the model and the
        project-store boundary enforce exactly the same definition of "safe,
        project-relative location".
        """

        reason = location_violation(value)
        if reason is not None:
            raise ValueError(f"original_location {reason}")
        return value

    @field_validator("usage_rights_evidence_ref")
    @classmethod
    def _evidence_ref_is_project_relative(cls, value: str | None) -> str | None:
        """A rights-evidence reference, when present, is a safe project path."""

        if value is not None:
            reason = location_violation(value)
            if reason is not None:
                raise ValueError(f"usage_rights_evidence_ref {reason}")
        return value
