"""Canonical base, typed ids, and stable serialization for ``kinocut_sound``.

This module re-implements the repository's proven canonical-record pattern
(frozen Pydantic models, fail-closed typed ids, sorted-key JSON digests) inside
the sidecar package so ``kinocut_sound`` stays usable without importing any
``kinocut`` runtime module. The pattern is shared, not the code: nothing here
imports from ``kinocut.*``.

Conventions enforced:

* Every contract model is immutable (``frozen=True``), rejects unknown fields
  (``extra="forbid"``), and refuses non-finite floats (``allow_inf_nan=False``).
* A :class:`RecordBase` derives its canonical ``record_id`` from semantic
  content only — informational fields (``created_at``) never bind identity.
* A supplied ``record_id`` must equal the record's own canonical digest.
* Bounded codes and project-relative locations are structurally enforced so a
  secret, host path, URL, or uncontrolled prose can never serialize.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticSerializationError

from kinocut_sound._errors import INVALID_RECORD, contract_error
from kinocut_sound.validation import (
    CODE_RE,
    CREATED_BY_PATTERN,
    INFORMATIONAL_FIELDS,
    RECORD_KIND_PATTERN,
    SCHEME_RE,
    SHA256_PATTERN,
)

# A lowercase-hex sha256 digest carrying its algorithm prefix.
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]

_DEFAULT_EXCLUDE = INFORMATIONAL_FIELDS


class FrozenModel(BaseModel):
    """Immutable, unknown-field-rejecting base for embedded value objects.

    Value objects are the small nested structures carried inside records (a
    spatial point, a routing send, an automation envelope). They share the
    record strictness — frozen, no extra fields, no non-finite floats — but do
    not carry a canonical record id of their own.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RecordBase(BaseModel):
    """Immutable, unknown-field-rejecting, fail-closed base for all records."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    record_kind: str = Field(pattern=RECORD_KIND_PATTERN)
    record_id: Sha256 | None = None
    project_id: str = Field(min_length=1)
    created_at: str | None = None
    created_by: str = Field(pattern=CREATED_BY_PATTERN)
    supersedes: Sha256 | None = None
    source_record_ids: tuple[Sha256, ...] = ()

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version_is_strict_int(cls, value: Any) -> Any:
        """Reject coerced versions (``True``, ``"1"``, ``1.0``) before the literal."""

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("schema_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def _record_id_matches_canonical_digest(self) -> RecordBase:
        """Reject any stored ``record_id`` that is not the canonical digest."""

        if self.record_id is not None and self.record_id != canonical_record_id(self):
            raise ValueError("record_id does not match canonical semantic digest")
        return self


def BoundedCode(value: str) -> str:
    """Validate that ``value`` is a bounded code, not prose, a path, or a URL.

    Returned unchanged when acceptable so it can be used as a Pydantic
    ``BeforeValidator`` or called directly from a contract module.
    """

    if not CODE_RE.match(value):
        raise ValueError("value must be a bounded code (no spaces, paths, URLs, or prose)")
    return value


def location_violation(value: str) -> str | None:
    """Return why ``value`` is an unsafe stored location, or ``None`` when safe.

    Rejected: empty strings, NUL/control characters, URL schemes, absolute or
    home paths, Windows drive/UNC paths, parent-directory traversal, and empty
    path components (``a//b``). Everything else is a plain project-relative path.
    """

    if value == "":
        return "location must not be empty"
    if any(ord(char) < 0x20 for char in value):
        return "location must not contain control characters"
    if "://" in value or SCHEME_RE.match(value):
        return "location must not be a URL or scheme"
    if value.startswith(("/", "~", "\\")):
        return "location must be project-relative, not absolute"
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if ".." in parts:
        return "location must not traverse parent directories"
    if "" in parts:
        return "location must not contain empty path components"
    return None


def canonical_digest(value: BaseModel | dict[str, Any], *, exclude: set[str] | None = None) -> Sha256:
    """Hash one JSON-compatible payload with stable field and separator ordering.

    ``ensure_ascii=False`` keeps Unicode stable across serializers;
    ``allow_nan=False`` would have already rejected non-finite floats at model
    construction time, but is also passed here to refuse a tampered dict.
    """

    if isinstance(value, BaseModel):
        payload: dict[str, Any] = value.model_dump(mode="json", exclude=exclude or set())
    elif isinstance(value, dict):
        payload = value
    else:  # pragma: no cover - defensive: contract type is documented.
        raise TypeError("canonical_digest requires a BaseModel or dict")
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_record_id(
    model: RecordBase, *, exclude: frozenset[str] = _DEFAULT_EXCLUDE
) -> Sha256:
    """Return ``sha256:<hex>`` over a record's canonical semantic content.

    ``exclude`` may name *informational* fields only (never a semantic one).
    ``record_id`` is always excluded because it is derived, not an input.
    """

    if not isinstance(model, RecordBase):
        raise TypeError("canonical_record_id requires a RecordBase instance")
    if not frozenset(exclude) <= INFORMATIONAL_FIELDS:
        raise ValueError("exclude may only contain informational fields")
    try:
        payload = model.model_dump(
            mode="json", exclude=set(exclude) | {"record_id"}
        )
    except PydanticSerializationError as exc:  # pragma: no cover - hardening path.
        raise contract_error("record contains unencodable content", INVALID_RECORD) from exc
    return canonical_digest(payload)
