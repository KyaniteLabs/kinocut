"""Approved-asset registry record contracts (backlog #36, #38, #41).

These are **internal** primitives — they are not re-exported through
``kinocut.contracts`` and are never registered as MCP/CLI tools. They persist
approved clips and reusable audio beds over the existing projectstore, reusing
its atomic, lock-guarded, content-addressed infrastructure.

Privacy posture mirrors the rest of the contract layer: raw prompts,
transcripts, PII, and host paths are **structurally unrepresentable**. Media
identity is always a content hash; embeddings are referenced by artifact hash;
provenance is stored by hash only; tags are bounded strings.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from kinocut.contracts._common import (
    AssetId,
    RecordBase,
    Sha256,
    ValueObject,
)
from kinocut.contracts.asset import GenerationLineage, UsageRightsStatus

# Bounded free-form identifiers carried inside registry records. These are never
# host paths, prompts, or transcripts — they are short labels for query filters.
_TAG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,62}$"
_FAMILY_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_SPAN_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,63}$"
_MAX_TAGS = 32
_TAG_RE = re.compile(_TAG_PATTERN)


def _validate_tags(tags: tuple[str, ...]) -> None:
    """Enforce the bounded tag grammar shared by clip and bed records."""

    if len(tags) > _MAX_TAGS:
        raise ValueError(f"at most {_MAX_TAGS} tags are allowed")
    seen: set[str] = set()
    for tag in tags:
        if _TAG_RE.fullmatch(tag) is None:
            raise ValueError(f"tag {tag!r} is not a bounded lowercase label")
        if tag in seen:
            raise ValueError(f"tag {tag!r} appears more than once")
        seen.add(tag)


class ClipTechnicalMetadata(ValueObject):
    """Safe technical summary of an approved clip — no host paths or transcripts."""

    duration_seconds: float = Field(ge=0.0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    fps: float | None = Field(default=None, ge=0.0)
    codec: str | None = Field(default=None, min_length=1, max_length=64)
    has_audio: bool = True


class BedTechnicalMetadata(ValueObject):
    """Safe technical summary of a reusable audio bed."""

    duration_seconds: float = Field(ge=0.0)
    sample_rate: int | None = Field(default=None, ge=1)
    channels: int | None = Field(default=None, ge=1)
    codec: str | None = Field(default=None, min_length=1, max_length=64)


class LineageRelation(StrEnum):
    """The closed set of directed relations a lineage link may express."""

    GENERATED_FROM = "generated_from"
    VARIANT_OF = "variant_of"
    REPAIR_OF = "repair_of"
    DERIVED_FROM = "derived_from"
    FAMILY_MEMBER = "family_member"


class ClipRecord(RecordBase):
    """A persistently indexed approved clip (backlog #36).

    Binds a content-addressed media identity to the verdict, rights, consent,
    and technical metadata that make it eligible for approved-only search. Raw
    prompts, transcripts, PII, and host paths have no field here — provenance is
    always a hash reference.
    """

    record_kind: Literal["clip_record"] = "clip_record"

    asset_id: AssetId
    source_asset_id: AssetId
    verdict_id: Sha256
    review_decision_id: Sha256
    usage_rights_status: UsageRightsStatus
    technical: ClipTechnicalMetadata
    tags: tuple[str, ...] = ()
    embedding_ref: Sha256 | None = None
    semantic_span_id: str | None = Field(default=None, pattern=_SPAN_PATTERN)

    @model_validator(mode="after")
    def _validate_tags(self) -> ClipRecord:
        """Tags are bounded, unique, lowercase labels."""

        _validate_tags(self.tags)
        return self


class BedRecord(RecordBase):
    """A persistently indexed reusable audio bed (backlog #41).

    Carries rights, consent, mood/tempo/key, and family-grouping so later
    beat-planning can query and audition approved beds without re-deriving
    rights or consent from scratch.
    """

    record_kind: Literal["bed_record"] = "bed_record"

    asset_id: AssetId
    usage_rights_status: UsageRightsStatus
    review_decision_id: Sha256
    technical: BedTechnicalMetadata
    mood: str | None = Field(default=None, min_length=1, max_length=64)
    tempo_bpm: int | None = Field(default=None, ge=1, le=400)
    musical_key: str | None = Field(default=None, min_length=1, max_length=32)
    tags: tuple[str, ...] = ()
    family_id: str | None = Field(default=None, pattern=_FAMILY_PATTERN)
    embedding_ref: Sha256 | None = None

    @model_validator(mode="after")
    def _validate_tags(self) -> BedRecord:
        """Tags share the same bounded grammar as clip records."""

        _validate_tags(self.tags)
        return self


class LineageLink(RecordBase):
    """One durable edge in the generation-lineage graph (backlog #38).

    Links a derivative asset to its source asset(s) with a typed relation,
    optionally carrying the embedded :class:`GenerationLineage` provenance
    metadata (prompt hash, model, settings hash) and a family group id. The
    graph built from these edges is validated for cycles and dangling refs by
    the query/graph layer — the record itself enforces structural constraints
    (at least one source, no self-derivation for directed edges).
    """

    record_kind: Literal["lineage_link"] = "lineage_link"

    derivative_asset_id: AssetId
    source_asset_ids: tuple[AssetId, ...]
    relation: LineageRelation
    family_id: str | None = Field(default=None, pattern=_FAMILY_PATTERN)
    lineage_value: GenerationLineage | None = None
    prompt_outcome_id: Sha256 | None = None

    @model_validator(mode="after")
    def _validate_sources_and_self_reference(self) -> LineageLink:
        """At least one source; no self-derivation on directed edges."""

        if not self.source_asset_ids:
            raise ValueError("lineage link must reference at least one source asset")
        if len(set(self.source_asset_ids)) != len(self.source_asset_ids):
            raise ValueError("source_asset_ids must not contain duplicates")
        if self.relation is not LineageRelation.FAMILY_MEMBER and self.derivative_asset_id in self.source_asset_ids:
            raise ValueError("a derivative may not be its own source")
        return self
