"""Shared base for canonical AI-video records: typed ids and stable hashing.

Every later-wave record model subclasses :class:`RecordBase`. Records are
immutable, forbid unknown fields on write, and derive their ``record_id`` from
canonical semantic content only — informational fields such as ``created_at``
never bind the identity. Hashing mirrors the proven
``kinocut/semantic/models.py:canonical_digest`` pattern.

The base is fail-closed: non-finite floats are rejected so canonical JSON can
never diverge, ``record_kind`` is a bounded safe identifier safe for filename
derivation, ``schema_version`` is a strict integer, and a supplied
``record_id`` must equal the record's own canonical digest.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticSerializationError

from kinocut.contracts._errors import INVALID_RECORD, contract_error

# Typed id aliases: a lowercase-hex sha256 digest carrying its algorithm prefix.
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
Sha256 = Annotated[str, Field(pattern=_SHA256_PATTERN)]
AssetId = Annotated[str, Field(pattern=_SHA256_PATTERN)]

# ``created_by`` is a bounded actor role, optionally qualified by a short id.
_CREATED_BY_PATTERN = r"^(human|agent|tool)(:[a-z0-9][a-z0-9_.-]{0,63})?$"

# ``record_kind`` becomes a filename component in the project store, so it is a
# bounded, lowercase identifier: no traversal, absolute paths, NUL, or spaces.
_RECORD_KIND_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"

# Fields excluded from the canonical record id by default: informational only.
# The exclude set may never contain a *semantic* field — excluding one would let
# two logically-distinct records collide on the same id.
_INFORMATIONAL_FIELDS = frozenset({"created_at"})
_DEFAULT_EXCLUDE = _INFORMATIONAL_FIELDS


class ValueObject(BaseModel):
    """Immutable, unknown-field-rejecting base for embedded (non-record) values.

    Value objects are the small nested structures carried inside records (a
    normalized region, a measurement, a parameter slot). They share the record
    strictness — frozen, no extra fields, no non-finite floats — but do not
    carry provenance or a canonical id of their own.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class NormalizedRegion(ValueObject):
    """A normalized rectangle with positive area that stays inside the frame.

    Every coordinate lies in ``[0, 1]``; ``width``/``height`` are strictly
    positive (no degenerate zero-area regions); and the far edges
    (``x + width``, ``y + height``) may not exceed the unit frame.
    """

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _stays_within_frame(self) -> NormalizedRegion:
        """The rectangle's far edges must remain inside the unit frame."""

        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("region must stay within the unit frame")
        return self


class RecordBase(BaseModel):
    """Immutable, unknown-field-rejecting, fail-closed base for all records."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    record_kind: str = Field(pattern=_RECORD_KIND_PATTERN)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version_is_strict_int(cls, value: Any) -> Any:
        """Reject coerced versions (``True``, ``"1"``, ``1.0``) before the literal.

        ``Literal[1]`` freezes the *value*, but its lax matching would otherwise
        accept ``True``/``1.0``; a written version must be the integer ``1``.
        """

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("schema_version must be the integer 1")
        return value

    record_id: Sha256 | None = None
    project_id: str = Field(min_length=1)
    created_at: str | None = None
    created_by: str = Field(pattern=_CREATED_BY_PATTERN)
    supersedes: Sha256 | None = None
    source_record_ids: tuple[Sha256, ...] = ()

    @model_validator(mode="after")
    def _record_id_matches_canonical_digest(self) -> RecordBase:
        """Reject any stored ``record_id`` that is not the canonical digest.

        A record may omit ``record_id`` (it is derived), but if one is supplied
        it must equal the record's own semantic digest — identity is
        fail-closed, never an arbitrary caller-chosen value.
        """

        if self.record_id is not None and self.record_id != canonical_record_id(self):
            raise ValueError("record_id does not match canonical semantic digest")
        return self


def canonical_record_id(model: RecordBase, *, exclude: frozenset[str] = _DEFAULT_EXCLUDE) -> Sha256:
    """Return ``sha256:<hex>`` over a record's canonical semantic content.

    Only a :class:`RecordBase` has a canonical identity, and ``exclude`` may name
    *informational* fields only (never a semantic one). ``record_id`` is always
    excluded (it is derived, not an input). Serialization uses sorted keys,
    compact separators, and ``allow_nan=False`` so logically-equal records hash
    identically and a non-finite float can never be encoded.
    """

    if not isinstance(model, RecordBase):
        raise TypeError("canonical_record_id requires a RecordBase instance")
    if not frozenset(exclude) <= _INFORMATIONAL_FIELDS:
        raise ValueError("exclude may only contain informational fields")
    try:
        payload: dict[str, Any] = model.model_dump(mode="json", exclude=set(exclude) | {"record_id"})
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (UnicodeError, PydanticSerializationError) as exc:
        # A lone surrogate or a tampered, unserializable field (e.g. slipped in via
        # ``model_copy``) cannot yield a canonical digest; surface it as a stable
        # contract error rather than leaking a raw serialization error.
        raise contract_error("record contains unencodable content", INVALID_RECORD) from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
