"""Render fingerprint and determinism class contracts.

A render fingerprint covers the normalized SoundPlan, every byte hash, every
version vector, the codec/mux/conversion settings, the seed, locale,
hardware/backend, the concurrency ordering policy, and the required-capability
manifest. Its hash plus the stage/cue id forms the cache key. A determinism
class declares what replay guarantee the render provides.

Design references (sonic-world design):
* Core contracts §"RenderFingerprint & numeric mix policy".
* Cache, Idempotency & Resume — cache key is fingerprint hash + stage/cue id.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256

# Closed set of determinism classes. A stage declares exactly one.
DETERMINISM_CLASSES: frozenset[str] = frozenset(
    {"byte_deterministic", "signal_equivalent", "non_reproducible"}
)

# Locale is a bounded UN/LIBC-style identifier (e.g. ``en_US``, ``es_ES.UTF-8``).
_LOCALE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.@+=-]{0,63}$")


class DeterminismClass(StrEnum):
    """What replay guarantee a render provides."""

    BYTE_DETERMINISTIC = "byte_deterministic"
    SIGNAL_EQUIVALENT = "signal_equivalent"
    NON_REPRODUCIBLE = "non_reproducible"


class ToolchainVersion(FrozenModel):
    """One toolchain component and its declared version."""

    component: str = Field(min_length=1)
    version: str = Field(min_length=1)

    @field_validator("component")
    @classmethod
    def _component_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class FingerprintComponent(FrozenModel):
    """One named role and its content digest in the fingerprint."""

    role: str = Field(min_length=1)
    digest: Sha256

    @field_validator("role")
    @classmethod
    def _role_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class RenderFingerprint(FrozenModel):
    """Complete fingerprint of a render — the cache key input.

    The fingerprint is the entire set of inputs that affect a render's
    reproducibility. Its canonical hash plus a stage/cue id forms a stable
    cache key. Components must have unique roles; the required-capability
    manifest must be unique; and the determinism class must be closed.
    """

    determinism_class: DeterminismClass
    seed: str = Field(min_length=1, max_length=128)
    locale: str = Field(min_length=1)
    hardware_backend: str = Field(min_length=1)
    concurrency_ordering: str = Field(min_length=1)
    components: tuple[FingerprintComponent, ...] = Field(min_length=1)
    toolchain_versions: tuple[ToolchainVersion, ...] = ()
    required_capability_manifest: tuple[str, ...] = ()

    @field_validator("locale")
    @classmethod
    def _locale_bounded(cls, value: str) -> str:
        if not _LOCALE_RE.match(value):
            raise ValueError("locale must be a bounded identifier (no spaces or paths)")
        return value

    @field_validator("hardware_backend", "concurrency_ordering")
    @classmethod
    def _codes_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("required_capability_manifest")
    @classmethod
    def _manifest_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        return value

    @model_validator(mode="after")
    def _unique_roles_and_manifest(self) -> RenderFingerprint:
        roles = [c.role for c in self.components]
        if len(set(roles)) != len(roles):
            raise ValueError("component roles must be unique")
        if len(set(self.required_capability_manifest)) != len(self.required_capability_manifest):
            raise ValueError("required_capability_manifest must be unique")
        return self

    def canonical_payload(self) -> dict[str, object]:
        """Return the canonical, sorted-key JSON payload used for hashing."""

        return self.model_dump(mode="json")

    def digest(self) -> Sha256:
        """Return ``sha256:<hex>`` over this fingerprint's canonical payload."""

        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def cache_key(self, stage_cue_id: str) -> Sha256:
        """Return the stable cache key for ``stage_cue_id`` under this fingerprint.

        The cache key is ``sha256(<fingerprint_digest> + stage_cue_id)``. A
        ``stage_cue_id`` is a bounded code so a path or uncontrolled prose
        cannot ride in.
        """

        BoundedCode(stage_cue_id)
        fused = self.digest() + "|" + stage_cue_id
        return "sha256:" + hashlib.sha256(fused.encode("utf-8")).hexdigest()
