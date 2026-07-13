"""Fake D41 port: neutral bed/audition interfaces plus local fake adapters.

G15 (one-shot audio beds / ``audio-bed``) and G16 (bed-audition reels) are
owned by the existing D41 implementation. The sonic-world design mandates
that M0 defines only backend-neutral *ports* and that the S8 leaf consumes
those ports through fakes; the real D41 binding happens only in S13. This
module defines those typed ports and ships local fake adapters so standalone
S8 tests exercise the contract without the real D41 code.

Optional cloud asset generation (Stable Audio / AudioLDM, W4.1 cloud path)
is descriptor-only and probes ``unavailable`` when not configured — it never
selects itself silently and never performs a network call. A typed
:class:`AssetAdapter` (W4.1) conforms to :class:`kinocut_sound.registry.Adapter`
so the S3 registry can compile it; only the local fake probes available.

Design references (sonic-world design):
* G15 / G16 — D41-owned beds and audition; M0/S8 use typed ports + fakes only.
* W4.1 — ambient bed generation via AssetAdapter; cloud capability-gated.
* §"Provider & Model Capability Behavior" — absence yields explicit
  unavailable, never a silent remote call.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
    CostDisclosure,
)
from kinocut_sound.defaults import DEFAULT_ADAPTER_TIMEOUT_SECONDS
from kinocut_sound.limits import (
    MAX_ADAPTER_TIMEOUT_SECONDS,
    MIN_COST_USD,
    MIN_RETENTION_DAYS,
    MIN_TIME_SECONDS,
)


class BedKind(StrEnum):
    """Closed set of bed kinds the neutral D41 port can describe."""

    ROOM_TONE = "room_tone"
    AMBIENT_BED = "ambient_bed"
    TEXTURE_BED = "texture_bed"


class BedSpec(FrozenModel):
    """Neutral bed specification handed to a D41 bed port (no host paths)."""

    bed_id: str = Field(min_length=1)
    kind: BedKind
    description_hash: Sha256
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS)

    @field_validator("bed_id")
    @classmethod
    def _bed_id_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("duration_seconds")
    @classmethod
    def _duration_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("duration_seconds must not be a boolean")
        return value


@dataclass(frozen=True)
class BedDescriptor:
    """Neutral result of preparing a bed via the D41 port (hash only)."""

    bed_id: str
    descriptor_hash: Sha256
    duration_seconds: float


@dataclass(frozen=True)
class AuditionReelResult:
    """Neutral result of building an audition reel via the D41 port."""

    bed_id: str
    reel_label: str
    reel_hash: Sha256
    human_review_required: bool


@runtime_checkable
class BedPort(Protocol):
    """Neutral typed port for D41 one-shot bed preparation (G15)."""

    def probe(self) -> CapabilityResult: ...

    def prepare_bed(self, spec: BedSpec) -> BedDescriptor: ...


@runtime_checkable
class AuditionPort(Protocol):
    """Neutral typed port for D41 bed-audition reels (G16)."""

    def probe(self) -> CapabilityResult: ...

    def build_audition_reel(
        self,
        *,
        bed_id: str,
        reel_label: str,
        description_hash: Sha256,
    ) -> AuditionReelResult: ...


def _hash_descriptor(*, bed_id: str, payload: dict[str, object]) -> Sha256:
    body = {"bed_id": bed_id, **payload}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class LocalFakeBedAdapter:
    """Local fake D41 bed adapter — probes available, returns neutral descriptors.

    This adapter does not call the real D41 ``audio-bed``; it produces a
    deterministic neutral :class:`BedDescriptor` so standalone S8 tests
    exercise the port contract. The real binding is S13's responsibility.
    """

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="d41_bed_fake_local",
            kind="asset",
            locality=AdapterLocality.LOCAL,
            provider_class="d41_bed_fake",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=True,
        )

    def prepare_bed(self, spec: BedSpec) -> BedDescriptor:
        descriptor_hash = _hash_descriptor(
            bed_id=spec.bed_id,
            payload={
                "kind": spec.kind.value,
                "description_hash": spec.description_hash,
                "duration_seconds": spec.duration_seconds,
            },
        )
        return BedDescriptor(
            bed_id=spec.bed_id,
            descriptor_hash=descriptor_hash,
            duration_seconds=spec.duration_seconds,
        )


class LocalFakeAuditionAdapter:
    """Local fake D41 audition adapter — probes available, neutral reel hash.

    Does not call the real D41 ``bed-audition``. The reel hash is deterministic
    over the bounded inputs so cache fingerprints stay stable. Audition is
    perceptual QA, so ``human_review_required`` is always ``True``.
    """

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="d41_audition_fake_local",
            kind="asset",
            locality=AdapterLocality.LOCAL,
            provider_class="d41_audition_fake",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=True,
        )

    def build_audition_reel(
        self,
        *,
        bed_id: str,
        reel_label: str,
        description_hash: Sha256,
    ) -> AuditionReelResult:
        BoundedCode(bed_id)
        BoundedCode(reel_label)
        reel_hash = _hash_descriptor(
            bed_id=bed_id,
            payload={
                "reel_label": reel_label,
                "description_hash": description_hash,
            },
        )
        return AuditionReelResult(
            bed_id=bed_id,
            reel_label=reel_label,
            reel_hash=reel_hash,
            human_review_required=True,
        )


@dataclass(frozen=True)
class FakeD41Port:
    """Combined fake D41 port facade exposing bed + audition ports.

    The facade is the handle S8 tests pass around. It conforms to neither the
    real D41 surface nor the S13 binding; it only exposes the typed neutral
    ports above so a caller can probe availability and exercise the contract.
    """

    bed: BedPort
    audition: AuditionPort

    def probe(self) -> tuple[CapabilityResult, CapabilityResult]:
        return (self.bed.probe(), self.audition.probe())


def default_fake_d41_port() -> FakeD41Port:
    """Return a fresh fake D41 port with local bed + audition adapters."""

    return FakeD41Port(bed=LocalFakeBedAdapter(), audition=LocalFakeAuditionAdapter())


# --- Optional cloud AssetAdapter (W4.1) — descriptor-only, always unavailable ---


def _cloud_cost_disclosure() -> CostDisclosure:
    # Descriptor-only disclosure shape. The cloud adapter is never called (it
    # probes unavailable), but the disclosure must be well-formed so the
    # AdapterDescriptor validates against the S3 registry contract.
    return CostDisclosure(
        provider_id="stable_audio_audioldm",
        region="us",
        data_classes=("text_prompt",),
        retention_ceiling_days=MIN_RETENTION_DAYS,
        estimated_cost_usd_per_call=MIN_COST_USD,
        confirmed=False,
    )


class CloudAssetAdapter:
    """Descriptor-only cloud asset generator (Stable Audio / AudioLDM).

    Per the design, optional cloud asset generation is capability-gated and
    discloses cost/retention/region before any call. This adapter declares its
    descriptor but always probes ``unavailable``: it never selects itself
    silently and never performs a network call. S13 binds a real cloud adapter
    if/when one is authorized and configured.
    """

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="asset_cloud_stable_audio",
            kind="asset",
            locality=AdapterLocality.CLOUD,
            provider_class="stable_audio_audioldm",
            cost_disclosure=_cloud_cost_disclosure(),
            timeout_seconds=DEFAULT_ADAPTER_TIMEOUT_SECONDS,
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code="cloud_asset_not_configured",
            remediation="Install and authorize a cloud asset generator or use a local asset adapter.",
        )


class LocalFakeAssetAdapter:
    """Local AssetAdapter (W4.1) — available, deterministic, no network.

    This is the local ambient-bed generation adapter used by standalone S8
    tests. It conforms to :class:`kinocut_sound.registry.Adapter` (``descriptor``
    attribute + ``probe`` method). A real local generator (S7/S13) replaces it.
    """

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="asset_local_fake",
            kind="asset",
            locality=AdapterLocality.LOCAL,
            provider_class="local_fake_asset",
            timeout_seconds=min(DEFAULT_ADAPTER_TIMEOUT_SECONDS, MAX_ADAPTER_TIMEOUT_SECONDS),
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=True,
        )


# Adapter ids declared by this module — a caller may pass these to a registry.
CLOUD_ASSET_ADAPTER_ID = "asset_cloud_stable_audio"
LOCAL_ASSET_ADAPTER_ID = "asset_local_fake"
D41_BED_FAKE_ADAPTER_ID = "d41_bed_fake_local"
D41_AUDITION_FAKE_ADAPTER_ID = "d41_audition_fake_local"
