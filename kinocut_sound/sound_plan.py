"""SoundPlan: the authoritative master contract for an episode.

A SoundPlan is the single source of truth for an episode's audio. It is a
validated immutable record (not a rendering side effect) that carries the
authoritative timeline, lines, beds/layers, buses/routing, format, delivery
policy, and provenance references. It exposes a canonical id and serializes
without ever leaking raw prompts, transcripts, host paths, or credentials.

Plan identity derives from semantic content only — ``created_at`` never binds
identity, and ``record_id`` must equal the canonical digest when supplied.
Design references: sonic-world design §"SoundPlan (authoritative timeline)"
and §"Receipt & Provenance".
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from kinocut_sound._canonical import (
    BoundedCode,
    FrozenModel,
    RecordBase,
    canonical_record_id,
)
from kinocut_sound.delivery import DeliveryPolicy
from kinocut_sound.format import AudioFormat
from kinocut_sound.lines import Line
from kinocut_sound.routing import Routing
from kinocut_sound.timeline import Timeline

# Revalidate embedded value objects so a payload that bypassed validation
# (e.g. via ``model_construct``) is fully re-checked at the plan boundary.
_STRICT_EMBED = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always")


def _is_sha256(value: str) -> bool:
    """True when ``value`` is a ``sha256:<64 hex>`` digest."""

    return value.startswith("sha256:") and len(value) == len("sha256:") + 64


class AssetLicenseRef(FrozenModel):
    """A typed license reference: bounded id + licensed asset hash."""

    model_config = _STRICT_EMBED

    license_id: str = Field(min_length=1)
    asset_hash: str = Field(min_length=1)

    @field_validator("license_id")
    @classmethod
    def _license_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("asset_hash")
    @classmethod
    def _asset_hash_is_sha(cls, value: str) -> str:
        if not _is_sha256(value):
            raise ValueError("asset_hash must be a sha256 digest")
        return value


class ProcessingPresetRef(FrozenModel):
    """A typed processing-preset reference: bounded id + preset hash."""

    model_config = _STRICT_EMBED

    preset_id: str = Field(min_length=1)
    preset_hash: str = Field(min_length=1)

    @field_validator("preset_id")
    @classmethod
    def _preset_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("preset_hash")
    @classmethod
    def _preset_hash_is_sha(cls, value: str) -> str:
        if not _is_sha256(value):
            raise ValueError("preset_hash must be a sha256 digest")
        return value


class ModelRef(FrozenModel):
    """A typed model reference: bounded id + model digest + version."""

    model_config = _STRICT_EMBED

    model_id: str = Field(min_length=1)
    model_hash: str = Field(min_length=1)
    model_version: int = Field(ge=1)

    @field_validator("model_id")
    @classmethod
    def _model_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("model_hash")
    @classmethod
    def _model_hash_is_sha(cls, value: str) -> str:
        if not _is_sha256(value):
            raise ValueError("model_hash must be a sha256 digest")
        return value

    @field_validator("model_version", mode="before")
    @classmethod
    def _version_strict_int(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("model_version must be a positive integer")
        return value


class PlanProvenance(FrozenModel):
    """Hashed, license-bound provenance for a SoundPlan.

    Raw prompts and transcripts are never embedded; only their bounded SHA-256
    hashes appear. Consent refs are opaque bounded ids — subject identity and
    biometric material live in the access-controlled ledger, not the plan.
    """

    model_config = _STRICT_EMBED

    consent_grant_refs: tuple[str, ...] = ()
    asset_license_refs: tuple[AssetLicenseRef, ...] = ()
    processing_preset_refs: tuple[ProcessingPresetRef, ...] = ()
    model_refs: tuple[ModelRef, ...] = ()
    prompt_hashes: tuple[str, ...] = ()
    transcript_hashes: tuple[str, ...] = ()

    @field_validator("consent_grant_refs")
    @classmethod
    def _grant_refs_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("consent_grant_refs must be unique")
        return value

    @field_validator("prompt_hashes", "transcript_hashes")
    @classmethod
    def _hash_lists_are_sha(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            if not _is_sha256(code):
                raise ValueError("hashes must be sha256 digests")
        if len(set(value)) != len(value):
            raise ValueError("hashes must be unique")
        return value


class SoundPlan(RecordBase):
    """The authoritative master contract for one episode's audio.

    The plan is immutable and content-addressed. ``record_id`` is the canonical
    semantic digest and excludes only informational ``created_at``. A supplied
    ``record_id`` must equal the canonical digest. The timeline is the sole
    authority on required output duration; the routing must reference only
    declared buses; lines must carry unique line ids; the format and delivery
    policy fully bind the rendering shape.
    """

    record_kind: Literal["sound_plan"] = "sound_plan"
    plan_kind: Literal["episode"] = "episode"
    project_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    format: AudioFormat
    timeline: Timeline
    lines: tuple[Line, ...] = ()
    beds: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()
    routing: Routing
    delivery: DeliveryPolicy
    provenance: PlanProvenance

    @field_validator("episode_id")
    @classmethod
    def _episode_id_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("beds", "layers")
    @classmethod
    def _bed_layer_refs_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("bed/layer refs must be unique")
        return value

    @model_validator(mode="after")
    def _line_ids_unique(self) -> SoundPlan:
        ids = [line.line_id for line in self.lines]
        if len(set(ids)) != len(ids):
            raise ValueError("line ids must be unique")
        return self

    def canonical_id(self) -> str:
        """Return the canonical semantic digest of this plan."""

        return canonical_record_id(self)

    @property
    def authoritative_duration_seconds(self) -> float:
        """The required output duration, defined by the timeline."""

        return self.timeline.authoritative_duration_seconds
