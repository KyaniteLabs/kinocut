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
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticSerializationError

from kinocut_sound._errors import INVALID_RECORD, contract_error

# A lowercase-hex sha256 digest carrying its algorithm prefix.
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
Sha256 = Annotated[str, Field(pattern=_SHA256_PATTERN)]

# ``created_by`` is a bounded actor role, optionally qualified by a short id.
_CREATED_BY_PATTERN = r"^(human|agent|tool)(:[a-z0-9][a-z0-9_.-]{0,63})?$"

# ``record_kind`` is a bounded lowercase identifier safe for filename use.
_RECORD_KIND_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"

# Bounded code: letter start, then alnum / underscore / dot / colon / hyphen,
# up to 64 chars. No spaces, slashes, or control characters — prose, paths,
# URLs, and shell metacharacters simply cannot match. A leading digit would
# collide with numeric values, so codes must start with a letter.
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")

# A leading ``scheme:`` (http, file, data, ...) or a Windows drive letter.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Fields excluded from the canonical record id by default: informational only.
# This set may never contain a semantic field; excluding one would let two
# logically distinct records collide on the same id.
_INFORMATIONAL_FIELDS = frozenset({"created_at"})
_DEFAULT_EXCLUDE = _INFORMATIONAL_FIELDS


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
    record_kind: str = Field(pattern=_RECORD_KIND_PATTERN)
    record_id: Sha256 | None = None
    project_id: str = Field(min_length=1)
    created_at: str | None = None
    created_by: str = Field(pattern=_CREATED_BY_PATTERN)
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

    if not _CODE_RE.match(value):
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
    if "://" in value or _SCHEME_RE.match(value):
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
    if not frozenset(exclude) <= _INFORMATIONAL_FIELDS:
        raise ValueError("exclude may only contain informational fields")
    try:
        payload = model.model_dump(
            mode="json", exclude=set(exclude) | {"record_id"}
        )
    except PydanticSerializationError as exc:  # pragma: no cover - hardening path.
        raise contract_error("record contains unencodable content", INVALID_RECORD) from exc
    return canonical_digest(payload)
