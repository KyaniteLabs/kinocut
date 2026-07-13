"""Completeness-enforcing S3 render fingerprint builder."""

from __future__ import annotations

from itertools import islice
import logging
from typing import Any

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256, canonical_digest
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


def _normalize_capabilities(value: object) -> tuple[tuple[str, bool, str], ...]:
    normalized: list[tuple[str, bool, str]] = []
    for row in _bounded_rows(value, "capability"):
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise ValueError("capability entries must be triples")
        adapter_id, available, probe_version = row
        if not isinstance(available, bool):
            raise ValueError("capability availability must be boolean")
        normalized.append((BoundedCode(adapter_id), available, _safe_version(probe_version)))
    names = tuple(name for name, _, _ in normalized)
    if len(set(names)) != len(names):
        raise ValueError("capability identifiers must be unique")
    return tuple(sorted(normalized))


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
    capability_manifest: tuple[tuple[str, bool, str], ...] = Field(min_length=1)
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
    def _capabilities(cls, value: object) -> tuple[tuple[str, bool, str], ...]:
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


def build_render_fingerprint(inputs: FingerprintInputs) -> RenderFingerprint:
    """Build a complete fingerprint; permissive partial contracts cannot enter cache."""

    checked = FingerprintInputs.model_validate({name: getattr(inputs, name) for name in FingerprintInputs.model_fields})
    components = (
        FingerprintComponent(role="plan_normalized", digest=checked.normalized_plan_digest),
        FingerprintComponent(role="bytes_manifest", digest=_vector_digest(checked.byte_digests)),
        FingerprintComponent(role="profile_versions", digest=_vector_digest(checked.profile_versions)),
        FingerprintComponent(role="preset_versions", digest=_vector_digest(checked.preset_versions)),
        FingerprintComponent(
            role="adapter_code_versions",
            digest=_vector_digest(checked.adapter_code_versions),
        ),
        FingerprintComponent(role="model_versions", digest=_vector_digest(checked.model_versions)),
        FingerprintComponent(
            role="consent_state_versions",
            digest=_vector_digest(checked.consent_state_versions),
        ),
        FingerprintComponent(role="config_normalized", digest=checked.configuration_digest),
        FingerprintComponent(role="codec_mux", digest=checked.codec_mux_digest),
        FingerprintComponent(role="conversions", digest=checked.conversion_digest),
        FingerprintComponent(
            role="capability_manifest",
            digest=_vector_digest(checked.capability_manifest),
        ),
    )
    return RenderFingerprint(
        determinism_class=checked.determinism_class,
        seed=checked.seed,
        locale=checked.locale,
        hardware_backend=checked.hardware_backend,
        concurrency_ordering=checked.concurrency_ordering,
        components=components,
        toolchain_versions=tuple(
            ToolchainVersion(component=name, version=version) for name, version in checked.toolchain_versions
        ),
        required_capability_manifest=tuple(name for name, _, _ in checked.capability_manifest),
    )
