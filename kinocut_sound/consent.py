"""ConsentGrant and supporting right-to-clone contracts.

A ConsentGrant records a subject's right-to-clone authorization. Subject
identity is an opaque bounded id; biometric material, prompts, and transcripts
are referenced by hash only; an explicit cloud-egress grant names provider,
data classes, territory, retention ceiling, and expiry. State transitions are
compare-before-replace: revocation blocks new leases; a revoked grant never
re-authorizes a cache hit.

This leaf owns the *contract shape*. The runtime ledger, revocation race,
generation lease, quarantine, and deletion belong to the S2 leaf.

Design references (sonic-world design):
* Core contracts §"ConsentGrant (right-to-clone)".
* Errors, Privacy & Security — fail-closed at every protected lifecycle.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256

# Short intended-use summary: bounded length, no path/control chars. Allows
# spaces so a human-readable scope can summarize, but rejects URLs/host paths.
_USE_SUMMARY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.\-_'()]{0,199}$")
_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ConsentState(StrEnum):
    """The closed state set of a grant's lifecycle."""

    LIVE = "live"
    EXPIRED = "expired"
    REVOKED = "revoked"
    MISSING = "missing"


class RetentionPolicy(FrozenModel):
    """How biometric and audit material is retained after expiry/revocation."""

    biometric_retention: str
    audit_retention: str

    @field_validator("biometric_retention", "audit_retention")
    @classmethod
    def _codes_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class ConsentScope(FrozenModel):
    """What a grant authorizes: projects, characters, ops, providers, territory."""

    project_ids: tuple[str, ...] = ()
    character_ids: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    provider_classes: tuple[str, ...] = ()
    territory: str = Field(min_length=1)
    intended_use_summary: str | None = None

    @field_validator("project_ids", "character_ids", "operations", "provider_classes")
    @classmethod
    def _code_lists_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("scope codes must be unique")
        return value

    @field_validator("territory")
    @classmethod
    def _territory_is_bounded(cls, value: str) -> str:
        # Territory is a short UN M49 / ISO 3166-style code; letters/digits only.
        if not re.match(r"^[A-Za-z0-9]{2,16}$", value):
            raise ValueError("territory must be a bounded code (2-16 alphanumeric chars)")
        return value

    @field_validator("intended_use_summary")
    @classmethod
    def _use_summary_is_advisory(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _USE_SUMMARY_RE.match(value):
            raise ValueError("intended_use_summary must be short and free of paths, URLs, or metacharacters")
        return value


class AuditEvent(FrozenModel):
    """One append-only audit log entry on a grant."""

    event: str
    at_iso: str
    actor: str

    @field_validator("event", "actor")
    @classmethod
    def _codes_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("at_iso")
    @classmethod
    def _iso8601(cls, value: str) -> str:
        if not _ISO8601_RE.match(value):
            raise ValueError("at_iso must be a UTC ISO-8601 timestamp (YYYY-MM-DDTHH:MM:SSZ)")
        return value


class CloudEgressGrant(FrozenModel):
    """Explicit cloud-egress grant: provider, data classes, territory, ceiling."""

    provider_id: str = Field(min_length=1)
    data_classes: tuple[str, ...] = Field(min_length=1)
    territory: str = Field(min_length=1)
    retention_ceiling_days: int = Field(ge=0)
    expiry_iso: str

    @field_validator("provider_id")
    @classmethod
    def _provider_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("data_classes")
    @classmethod
    def _data_classes_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("data_classes must be unique")
        return value

    @field_validator("territory")
    @classmethod
    def _territory_bounded(cls, value: str) -> str:
        if not re.match(r"^[A-Za-z0-9]{2,16}$", value):
            raise ValueError("territory must be a bounded code (2-16 alphanumeric chars)")
        return value

    @field_validator("retention_ceiling_days", mode="before")
    @classmethod
    def _retention_strict_int(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("retention_ceiling_days must be a non-negative integer")
        return value

    @field_validator("expiry_iso")
    @classmethod
    def _expiry_iso8601(cls, value: str) -> str:
        if not _ISO8601_RE.match(value):
            raise ValueError("expiry_iso must be a UTC ISO-8601 timestamp")
        return value


class BlendAuthorization(FrozenModel):
    """Per-source authorization for a blend of two or more profile sources."""

    source_grant_ids: tuple[str, ...] = Field(min_length=2)
    composite_subject_id: str = Field(min_length=1)

    @field_validator("source_grant_ids")
    @classmethod
    def _source_grants_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("source_grant_ids must be unique")
        return value

    @field_validator("composite_subject_id")
    @classmethod
    def _subject_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class ConsentGrant(FrozenModel):
    """Right-to-clone grant: subject, scope, evidence hashes, state, retention."""

    grant_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    rightsholder_id: str = Field(min_length=1)
    scope: ConsentScope
    reference_evidence_hash: Sha256
    transcript_evidence_hash: Sha256
    reviewer_id: str = Field(min_length=1)
    issue_iso: str
    expiry_iso: str
    state: ConsentState
    retention: RetentionPolicy
    cloud_egress: CloudEgressGrant | None = None
    blend: BlendAuthorization | None = None
    watermark_policy: str | None = None
    audit_log: tuple[AuditEvent, ...] = ()

    @field_validator("grant_id", "subject_id", "rightsholder_id", "reviewer_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("watermark_policy")
    @classmethod
    def _watermark_bounded(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else value

    @field_validator("issue_iso", "expiry_iso")
    @classmethod
    def _iso8601(cls, value: str) -> str:
        if not _ISO8601_RE.match(value):
            raise ValueError("timestamps must be UTC ISO-8601 (YYYY-MM-DDTHH:MM:SSZ)")
        return value

    @model_validator(mode="after")
    def _expiry_after_issue(self) -> ConsentGrant:
        if self.expiry_iso <= self.issue_iso:
            raise ValueError("expiry_iso must be after issue_iso")
        return self
