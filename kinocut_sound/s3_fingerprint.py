"""Completeness-enforcing S3 render fingerprint builder."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
import logging
from typing import Any

from pydantic import Field, StrictBool, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256, canonical_digest
from kinocut_sound._errors import SoundContractError
from kinocut_sound.limits import MAX_FINGERPRINT_ITEMS, MAX_FINGERPRINT_VERSION_CHARS
from kinocut_sound.render_fingerprint import (
    DeterminismClass,
    FingerprintComponent,
    RenderFingerprint,
    ToolchainVersion,
)

logger = logging.getLogger(__name__)

S3_REQUIRED_COMPONENT_ROLES = frozenset(
    {
        "plan_normalized",
        "bytes_manifest",
        "profile_versions",
        "preset_versions",
        "adapter_code_versions",
        "model_versions",
        "consent_state_versions",
        "config_normalized",
        "codec_mux",
        "conversions",
        "capability_manifest",
    }
)


class FingerprintError(SoundContractError):
    """Stable complete-fingerprint construction failure."""


def _error(message: str, code: str) -> FingerprintError:
    return FingerprintError(message, code=code, suggested_action={"auto_fix": False})


class CapabilityRequirement(StrEnum):
    """Whether unavailable capability blocks the render."""

    REQUIRED = "required"
    ADVISORY = "advisory"


class CapabilitySnapshot(FrozenModel):
    """Bounded capability probe input with explicit requirement class."""

    adapter_id: str = Field(min_length=1)
    available: StrictBool
    probe_version: str = Field(min_length=1)
    requirement: CapabilityRequirement

    @field_validator("adapter_id")
    @classmethod
    def _adapter(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("probe_version")
    @classmethod
    def _version(cls, value: str) -> str:
        return _safe_version(value)


def _bounded_rows(value: object, label: str) -> tuple[object, ...]:
    try:
        rows = tuple(islice(iter(value), MAX_FINGERPRINT_ITEMS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("fingerprint vector traversal failed")
        raise ValueError(f"{label} vector is invalid") from None
    if not rows or len(rows) > MAX_FINGERPRINT_ITEMS:
        raise ValueError(f"{label} vector must be nonempty and bounded")
    return rows


def _safe_version(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_FINGERPRINT_VERSION_CHARS:
        raise ValueError("version must be a bounded string")
    if (
        any(ord(char) < 0x20 or char.isspace() for char in value)
        or "/" in value
        or "\\" in value
        or "://" in value
        or value.startswith("~")
    ):
        raise ValueError("version must not contain paths, URLs, or whitespace")
    return value


def _normalize_pairs(value: object, label: str, *, digests: bool = False) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for row in _bounded_rows(value, label):
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError(f"{label} entries must be pairs")
        name = BoundedCode(row[0])
        item = row[1]
        if digests:
            from pydantic import TypeAdapter

            item = TypeAdapter(Sha256).validate_python(item)
        else:
            item = _safe_version(item)
        normalized.append((name, item))
    names = tuple(name for name, _ in normalized)
    if len(set(names)) != len(names):
        raise ValueError(f"{label} names must be unique")
    return tuple(sorted(normalized))


def _normalize_capabilities(value: object) -> tuple[CapabilitySnapshot, ...]:
    normalized: list[CapabilitySnapshot] = []
    for row in _bounded_rows(value, "capability"):
        normalized.append(CapabilitySnapshot.model_validate(row, from_attributes=True))
    names = tuple(item.adapter_id for item in normalized)
    if len(set(names)) != len(names):
        raise ValueError("capability identifiers must be unique")
    return tuple(sorted(normalized, key=lambda item: item.adapter_id))


class FingerprintInputs(FrozenModel):
    """Every semantic category required to produce a cache-safe fingerprint."""

    normalized_plan_digest: Sha256
    byte_digests: tuple[tuple[str, Sha256], ...] = Field(min_length=1)
    profile_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    preset_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    adapter_code_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    model_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    consent_state_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    toolchain_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    configuration_digest: Sha256
    codec_mux_digest: Sha256
    conversion_digest: Sha256
    seed: str = Field(min_length=1)
    locale: str = Field(min_length=1)
    hardware_backend: str = Field(min_length=1)
    concurrency_ordering: str = Field(min_length=1)
    capability_manifest: tuple[CapabilitySnapshot, ...] = Field(min_length=1)
    determinism_class: DeterminismClass = DeterminismClass.SIGNAL_EQUIVALENT

    @field_validator("byte_digests", mode="before")
    @classmethod
    def _bytes(cls, value: object) -> tuple[tuple[str, str], ...]:
        return _normalize_pairs(value, "bytes", digests=True)

    @field_validator(
        "profile_versions",
        "preset_versions",
        "adapter_code_versions",
        "model_versions",
        "consent_state_versions",
        "toolchain_versions",
        mode="before",
    )
    @classmethod
    def _versions(cls, value: object, info: Any) -> tuple[tuple[str, str], ...]:
        return _normalize_pairs(value, info.field_name)

    @field_validator("capability_manifest", mode="before")
    @classmethod
    def _capabilities(cls, value: object) -> tuple[CapabilitySnapshot, ...]:
        return _normalize_capabilities(value)

    @field_validator("seed")
    @classmethod
    def _seed(cls, value: str) -> str:
        return _safe_version(value)

    @field_validator("hardware_backend", "concurrency_ordering")
    @classmethod
    def _codes(cls, value: str) -> str:
        return BoundedCode(value)


def _vector_digest(value: object) -> Sha256:
    return canonical_digest({"items": value})


_TOKEN = object()


@dataclass(frozen=True)
class CompleteRenderFingerprint:
    """Opaque validated fingerprint admitted to S3 cache APIs."""

    _fingerprint: RenderFingerprint
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise _error("complete fingerprint token is invalid", "incomplete_render_fingerprint")

    @property
    def components(self):  # type: ignore[no-untyped-def]
        return self._fingerprint.components

    @property
    def required_capability_manifest(self) -> tuple[str, ...]:
        return self._fingerprint.required_capability_manifest

    def digest(self) -> Sha256:
        return self._fingerprint.digest()

    def cache_key(self, stage_cue_id: str) -> Sha256:
        return self._fingerprint.cache_key(stage_cue_id)


def _components(checked: FingerprintInputs) -> tuple[FingerprintComponent, ...]:
    vectors = (
        ("plan_normalized", checked.normalized_plan_digest),
        ("bytes_manifest", _vector_digest(checked.byte_digests)),
        ("profile_versions", _vector_digest(checked.profile_versions)),
        ("preset_versions", _vector_digest(checked.preset_versions)),
        ("adapter_code_versions", _vector_digest(checked.adapter_code_versions)),
        ("model_versions", _vector_digest(checked.model_versions)),
        ("consent_state_versions", _vector_digest(checked.consent_state_versions)),
        ("config_normalized", checked.configuration_digest),
        ("codec_mux", checked.codec_mux_digest),
        ("conversions", checked.conversion_digest),
        (
            "capability_manifest",
            _vector_digest(tuple(item.model_dump(mode="json") for item in checked.capability_manifest)),
        ),
    )
    return tuple(FingerprintComponent(role=role, digest=digest) for role, digest in vectors)


def build_render_fingerprint(inputs: FingerprintInputs) -> CompleteRenderFingerprint:
    """Build the only fingerprint type admitted to the S3 cache."""

    try:
        checked = FingerprintInputs.model_validate(inputs.model_dump(mode="python"))
    except Exception:
        logger.warning("complete fingerprint input validation failed")
        raise _error("render fingerprint inputs are invalid", "invalid_fingerprint_inputs") from None
    unavailable = tuple(
        item.adapter_id
        for item in checked.capability_manifest
        if item.requirement is CapabilityRequirement.REQUIRED and not item.available
    )
    if unavailable:
        raise _error("required capability is unavailable", "required_capability_unavailable")
    required = tuple(
        item.adapter_id for item in checked.capability_manifest if item.requirement is CapabilityRequirement.REQUIRED
    )
    fingerprint = RenderFingerprint(
        determinism_class=checked.determinism_class,
        seed=checked.seed,
        locale=checked.locale,
        hardware_backend=checked.hardware_backend,
        concurrency_ordering=checked.concurrency_ordering,
        components=_components(checked),
        toolchain_versions=tuple(
            ToolchainVersion(component=name, version=version) for name, version in checked.toolchain_versions
        ),
        required_capability_manifest=required,
    )
    return CompleteRenderFingerprint(fingerprint, _TOKEN)
