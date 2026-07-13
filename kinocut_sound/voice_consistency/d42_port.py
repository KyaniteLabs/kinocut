"""Fake D42 port: neutral style/identity interfaces plus local fake adapters.

G18 (voice style metrics) and G19 (voice identity comparison) are owned by
the existing D42 implementation. The sonic-world design mandates that M0
defines only backend-neutral *ports* and that the S10 leaf consumes those
ports through fakes; the real D42 binding happens only in S13. This module
defines those typed ports and ships local fake adapters so standalone S10
tests exercise the contract without the real D42 code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_D42_UNAVAILABLE,
    CONSISTENCY_METRIC_INVALID,
    bounded_consistency_error,
)


class StyleCheckSpec(FrozenModel):
    """Neutral style-check input handed to a D42 style port."""

    profile_id: str
    audio_hash: Sha256
    reference_hash: Sha256

    @field_validator("profile_id")
    @classmethod
    def _profile_id_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class IdentityCheckSpec(FrozenModel):
    """Neutral identity-check input handed to a D42 identity port."""

    audio_hash_a: Sha256
    audio_hash_b: Sha256


@dataclass(frozen=True)
class StyleCheckResult:
    """Neutral style-check result from a D42 style port."""

    profile_id: str
    similarity: float
    drift: bool
    flags: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True)
class IdentityCheckResult:
    """Neutral identity-check result from a D42 identity port."""

    similarity: float
    same_identity: bool
    reason: str | None = None


@runtime_checkable
class StylePort(Protocol):
    """Neutral typed port for D42 voice-style checks (G18)."""

    def probe(self) -> CapabilityResult: ...

    def check_style(self, spec: StyleCheckSpec) -> StyleCheckResult: ...


@runtime_checkable
class IdentityPort(Protocol):
    """Neutral typed port for D42 voice-identity checks (G19)."""

    def probe(self) -> CapabilityResult: ...

    def compare_identity(self, spec: IdentityCheckSpec) -> IdentityCheckResult: ...


def _hash_for_similarity(*, audio_hash: str, reference_hash: str) -> Sha256:
    body = {"audio_hash": audio_hash, "reference_hash": reference_hash}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _similarity_from_hashes(hash_a: str, hash_b: str) -> float:
    """Return a deterministic pseudo-similarity in ``[0, 1]``.

    Identical hashes yield ``1.0``. Completely different hashes yield a
    value near ``0.5`` so tests can observe drift without needing real
    spectral analysis. The value is stable across runs.
    """

    if hash_a == hash_b:
        return 1.0
    fused = _hash_for_similarity(audio_hash=hash_a, reference_hash=hash_b)
    hex_part = fused.removeprefix("sha256:")
    head = int(hex_part[:8], 16)
    # Map to [0.45, 0.75] so drift thresholds near 0.8/0.9 reliably flag.
    return 0.45 + (head / 0xFFFFFFFF) * 0.30


class LocalFakeStyleAdapter:
    """Local fake D42 style adapter — probes available, returns neutral metrics."""

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="d42_style_fake_local",
            kind="analyzer",
            locality=AdapterLocality.LOCAL,
            provider_class="d42_style_fake",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=True,
        )

    def check_style(self, spec: StyleCheckSpec) -> StyleCheckResult:
        similarity = _similarity_from_hashes(spec.audio_hash, spec.reference_hash)
        return StyleCheckResult(
            profile_id=spec.profile_id,
            similarity=similarity,
            drift=False,
            flags=(),
        )


class LocalFakeIdentityAdapter:
    """Local fake D42 identity adapter — probes available, neutral similarity."""

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="d42_identity_fake_local",
            kind="analyzer",
            locality=AdapterLocality.LOCAL,
            provider_class="d42_identity_fake",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=True,
        )

    def compare_identity(self, spec: IdentityCheckSpec) -> IdentityCheckResult:
        similarity = _similarity_from_hashes(spec.audio_hash_a, spec.audio_hash_b)
        return IdentityCheckResult(
            similarity=similarity,
            same_identity=False,
        )


class UnavailableStyleAdapter:
    """Fake adapter that probes unavailable for negative-path tests."""

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="d42_style_unavailable",
            kind="analyzer",
            locality=AdapterLocality.LOCAL,
            provider_class="d42_style_unavailable",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code=CONSISTENCY_D42_UNAVAILABLE,
            remediation="Configure or inject a FakeD42Port.",
        )

    def check_style(self, spec: StyleCheckSpec) -> StyleCheckResult:
        raise bounded_consistency_error(
            "D42 style port is unavailable",
            CONSISTENCY_D42_UNAVAILABLE,
        )


class UnavailableIdentityAdapter:
    """Fake adapter that probes unavailable for negative-path tests."""

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="d42_identity_unavailable",
            kind="analyzer",
            locality=AdapterLocality.LOCAL,
            provider_class="d42_identity_unavailable",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code=CONSISTENCY_D42_UNAVAILABLE,
            remediation="Configure or inject a FakeD42Port.",
        )

    def compare_identity(self, spec: IdentityCheckSpec) -> IdentityCheckResult:
        raise bounded_consistency_error(
            "D42 identity port is unavailable",
            CONSISTENCY_D42_UNAVAILABLE,
        )


@dataclass(frozen=True)
class FakeD42Port:
    """Combined fake D42 port facade exposing style + identity ports."""

    style: StylePort
    identity: IdentityPort

    def probe(self) -> tuple[CapabilityResult, CapabilityResult]:
        return (self.style.probe(), self.identity.probe())


def default_fake_d42_port() -> FakeD42Port:
    """Return a fresh fake D42 port with local style + identity adapters."""

    return FakeD42Port(
        style=LocalFakeStyleAdapter(),
        identity=LocalFakeIdentityAdapter(),
    )
