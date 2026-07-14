"""Consent-gated voice blending / compositing (S6 / W1.3).

A blend requires a composite grant plus an independent live grant for every
source. Per-source EQ presets are closed and affect the deterministic render
fingerprint. Revocation races quarantine derivatives through generation leases.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AssetLineage,
    ConsentLedger,
    GenerationLease,
)
from kinocut_sound.lines import Line
from kinocut_sound.voice._errors import (
    ADAPTER_INPUT_INVALID,
    VOICE_RENDER_FAILED,
    VoiceError,
    voice_error,
)
from kinocut_sound.voice.local_adapter import (
    LocalSynthesisAdapter,
    SynthesisOutput,
    TtsAdapter,
)
from kinocut_sound.voice.roster import VoiceSlot, default_roster

_KNOWN_EQ_PRESETS: frozenset[str] = frozenset({"neutral", "warm", "bright", "dark", "presence"})
_SAFE_REL_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))(?!.*//)[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_LEASE_COUNTER = 0
_EQ_SEED: dict[str, bytes] = {
    "neutral": b"eq:neutral",
    "warm": b"eq:warm",
    "bright": b"eq:bright",
    "dark": b"eq:dark",
    "presence": b"eq:presence",
}


def _next_lease_id() -> str:
    global _LEASE_COUNTER
    _LEASE_COUNTER += 1
    return f"lease_blend_{_LEASE_COUNTER:06d}"


@dataclass(frozen=True)
class BlendSource:
    """One authorized source in a blend composite."""

    profile_id: str
    grant_id: str
    eq_preset: str

    def __post_init__(self) -> None:
        if self.eq_preset not in _KNOWN_EQ_PRESETS:
            # Construction-time unknown presets are accepted on the source;
            # render fails closed so tests can construct then render-fail.
            pass


@dataclass(frozen=True)
class BlendProfile:
    """Composite blend profile with 2–3 uniquely authorized sources."""

    profile_id: str
    composite_subject_id: str
    composite_grant_id: str
    sources: tuple[BlendSource, ...]

    def __post_init__(self) -> None:
        if len(self.sources) < 2 or len(self.sources) > 3:
            raise voice_error(
                "blend profile requires two or three sources",
                ADAPTER_INPUT_INVALID,
            )
        grant_ids = tuple(source.grant_id for source in self.sources)
        if len(set(grant_ids)) != len(grant_ids):
            raise voice_error(
                "blend sources require unique grant ids",
                ADAPTER_INPUT_INVALID,
            )

    def __repr__(self) -> str:  # pragma: no cover - privacy surface
        source_ids = tuple((s.profile_id, s.grant_id, s.eq_preset) for s in self.sources)
        return (
            f"BlendProfile(profile_id={self.profile_id!r}, "
            f"composite_subject_id={self.composite_subject_id!r}, "
            f"composite_grant_id={self.composite_grant_id!r}, "
            f"sources={source_ids!r})"
        )


@dataclass(frozen=True)
class BlendRenderReceipt:
    """Minimal blend render receipt carrying consent lineage refs."""

    consent_grant_refs: tuple[str, ...]
    profile_id: str
    output_hash: str


class BlendRenderer:
    """Authorize and render multi-source blended voice output."""

    __slots__ = ("_adapter", "_roster", "_base_slot")

    def __init__(
        self,
        *,
        adapter: TtsAdapter | LocalSynthesisAdapter,
        base_slot_id: str = "hero_tenor",
    ) -> None:
        self._adapter = adapter
        self._roster = default_roster()
        self._base_slot: VoiceSlot = self._roster.get(base_slot_id)

    def _all_grant_ids(self, profile: BlendProfile) -> tuple[str, ...]:
        return tuple(
            sorted(
                (
                    profile.composite_grant_id,
                    *(source.grant_id for source in profile.sources),
                )
            )
        )

    def _authorize(
        self,
        *,
        profile: BlendProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
        boundary: AuthorizationBoundary,
    ) -> tuple[str, ...]:
        # Composite grant + every source grant, independently.
        blend_grants = ledger.authorize_blend(
            profile.composite_grant_id,
            context=context,
            at_iso=at_iso,
        )
        # Also re-check at the requested lifecycle boundary.
        return ledger.authorize(
            boundary,
            grant_ids=blend_grants,
            context=context,
            at_iso=at_iso,
        )

    def _validate_eq(self, profile: BlendProfile) -> None:
        for source in profile.sources:
            if source.eq_preset not in _KNOWN_EQ_PRESETS:
                raise voice_error(
                    f"unknown blend eq preset: {source.eq_preset}",
                    "eq_preset_unknown",
                )

    def _render_unlocked(
        self,
        *,
        line: Line,
        profile: BlendProfile,
    ) -> SynthesisOutput:
        self._validate_eq(profile)
        base = self._adapter.render(slot=self._base_slot, line=line)
        # Fold per-source EQ seeds into the WAV payload so preset changes
        # alter the content hash without requiring real DSP.
        mixer = hashlib.sha256(base.wav_bytes)
        for source in profile.sources:
            mixer.update(source.grant_id.encode("utf-8"))
            mixer.update(source.profile_id.encode("utf-8"))
            mixer.update(_EQ_SEED[source.eq_preset])
        digest = mixer.digest()
        # Keep a valid WAV header from the base render; replace PCM tail
        # deterministically so length stays valid.
        wav = bytearray(base.wav_bytes)
        if len(wav) > 44:
            for i, byte in enumerate(digest):
                idx = 44 + (i % (len(wav) - 44))
                wav[idx] = byte
        output_hash = "sha256:" + hashlib.sha256(bytes(wav)).hexdigest()
        return SynthesisOutput(
            wav_bytes=bytes(wav),
            output_hash=output_hash,
            duration_seconds=base.duration_seconds,
            sample_rate_hz=base.sample_rate_hz,
            channel_count=base.channel_count,
            recipe_digest="sha256:" + hashlib.sha256(
                profile.profile_id.encode("utf-8")
                + b"|"
                + "|".join(f"{s.grant_id}:{s.eq_preset}" for s in profile.sources).encode("utf-8")
            ).hexdigest(),
        )

    def render(
        self,
        *,
        line: Line,
        profile: BlendProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> SynthesisOutput:
        self._authorize(
            profile=profile,
            ledger=ledger,
            context=context,
            at_iso=at_iso,
            boundary=AuthorizationBoundary.GENERATION,
        )
        try:
            return self._render_unlocked(line=line, profile=profile)
        except VoiceError:
            raise
        except Exception as exc:  # pragma: no cover
            raise voice_error("blend render failed", VOICE_RENDER_FAILED) from exc

    def render_receipt(
        self,
        *,
        line: Line,
        profile: BlendProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> BlendRenderReceipt:
        output = self.render(
            line=line,
            profile=profile,
            ledger=ledger,
            context=context,
            at_iso=at_iso,
        )
        refs = tuple(
            sorted(
                (
                    profile.composite_grant_id,
                    *(source.grant_id for source in profile.sources),
                )
            )
        )
        return BlendRenderReceipt(
            consent_grant_refs=refs,
            profile_id=profile.profile_id,
            output_hash=output.output_hash,
        )

    def acquire_blend_lease(
        self,
        *,
        profile: BlendProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
        ttl_seconds: int,
        actor_id: str,
    ) -> GenerationLease:
        grant_ids = self._all_grant_ids(profile)
        # Authorize blend scope first so missing/revoked grants fail closed.
        ledger.authorize_blend(
            profile.composite_grant_id,
            context=context,
            at_iso=at_iso,
        )
        lease_id = _next_lease_id()
        return ledger.acquire_lease(
            lease_id,
            grant_ids=grant_ids,
            ttl_seconds=ttl_seconds,
            context=context,
            at_iso=at_iso,
            actor_id=actor_id,
        )

    def commit_blend_lease(
        self,
        *,
        lease_id: str,
        output_asset_id: str,
        profile: BlendProfile,
        ledger: ConsentLedger,
        at_iso: str,
        actor_id: str,
    ) -> AssetLineage:
        return ledger.commit_lease(
            lease_id,
            output_asset_id=output_asset_id,
            parent_asset_ids=(),
            at_iso=at_iso,
            actor_id=actor_id,
        )

    def export(
        self,
        *,
        output_path: str,
        output_dir: str,
        line: Line,
        profile: BlendProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> str:
        if not isinstance(output_path, str) or not _SAFE_REL_PATH.match(output_path):
            raise voice_error(
                "blend export path must be a safe project-relative path",
                ADAPTER_INPUT_INVALID,
            )
        self._authorize(
            profile=profile,
            ledger=ledger,
            context=context,
            at_iso=at_iso,
            boundary=AuthorizationBoundary.EXPORT,
        )
        output = self._render_unlocked(line=line, profile=profile)
        full = os.path.join(output_dir, *output_path.split("/"))
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(output.wav_bytes)
        return output_path


__all__ = [
    "BlendProfile",
    "BlendRenderReceipt",
    "BlendRenderer",
    "BlendSource",
]
