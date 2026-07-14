"""Consent-gated zero-shot voice cloning (S6 / W1.2).

Clone operations require a live consent grant at every protected boundary.
Local synthesis reuses the S5 adapter; cloud stubs remain fail-closed without
explicit opt-in and cloud-egress authorization.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    ConsentLedger,
)
from kinocut_sound.lines import Line
from kinocut_sound.voice._errors import (
    ADAPTER_INPUT_INVALID,
    VOICE_RENDER_FAILED,
    VoiceError,
    voice_error,
)
from kinocut_sound.voice.local_adapter import (
    CloudTtsAdapterStub,
    LocalSynthesisAdapter,
    SynthesisOutput,
    TtsAdapter,
)
from kinocut_sound.voice.roster import VoiceSlot

_SAFE_REL_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))(?!.*//)[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_LEASE_COUNTER = 0


def _next_lease_id() -> str:
    global _LEASE_COUNTER
    _LEASE_COUNTER += 1
    return f"lease_clone_{_LEASE_COUNTER:06d}"


@dataclass(frozen=True)
class CloneProfile:
    """Zero-shot clone profile bound to a consent grant and base roster slot."""

    profile_id: str
    subject_id: str
    grant_id: str
    reference_hash: str
    transcript_hash: str
    base_slot: VoiceSlot
    created_at_iso: str

    def __repr__(self) -> str:  # pragma: no cover - privacy surface
        return (
            f"CloneProfile(profile_id={self.profile_id!r}, subject_id={self.subject_id!r}, "
            f"grant_id={self.grant_id!r}, reference_hash={self.reference_hash!r}, "
            f"transcript_hash={self.transcript_hash!r}, base_slot_id={self.base_slot.slot_id!r}, "
            f"created_at_iso={self.created_at_iso!r})"
        )


class CloneRenderer:
    """Authorize, render, and export consent-gated clone audio."""

    __slots__ = ("_adapter",)

    def __init__(self, *, adapter: TtsAdapter | LocalSynthesisAdapter | CloudTtsAdapterStub) -> None:
        self._adapter = adapter

    def _authorize_generation(
        self,
        *,
        profile: CloneProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> tuple[str, ...]:
        return ledger.authorize(
            AuthorizationBoundary.GENERATION,
            grant_ids=(profile.grant_id,),
            context=context,
            at_iso=at_iso,
        )

    def _authorize_export(
        self,
        *,
        profile: CloneProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> tuple[str, ...]:
        return ledger.authorize(
            AuthorizationBoundary.EXPORT,
            grant_ids=(profile.grant_id,),
            context=context,
            at_iso=at_iso,
        )

    def _render_unlocked(
        self,
        *,
        line: Line,
        profile: CloneProfile,
    ) -> SynthesisOutput:
        if isinstance(self._adapter, CloudTtsAdapterStub):
            # Cloud stub raises CLOUD_NOT_ALLOWED; surface as VoiceError.
            return self._adapter.render(slot=profile.base_slot, line=line)
        return self._adapter.render(slot=profile.base_slot, line=line)

    def render(
        self,
        *,
        line: Line,
        profile: CloneProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> SynthesisOutput:
        self._authorize_generation(
            profile=profile,
            ledger=ledger,
            context=context,
            at_iso=at_iso,
        )
        try:
            return self._render_unlocked(line=line, profile=profile)
        except VoiceError:
            raise
        except Exception as exc:  # pragma: no cover
            raise voice_error("clone render failed", VOICE_RENDER_FAILED) from exc

    def render_with_lease(
        self,
        *,
        line: Line,
        profile: CloneProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
        ttl_seconds: int,
        actor_id: str,
    ) -> tuple[SynthesisOutput, str]:
        lease_id = _next_lease_id()
        lease = ledger.acquire_lease(
            lease_id,
            grant_ids=(profile.grant_id,),
            ttl_seconds=ttl_seconds,
            context=context,
            at_iso=at_iso,
            actor_id=actor_id,
        )
        output = self._render_unlocked(line=line, profile=profile)
        return output, lease.lease_id

    def export(
        self,
        *,
        output_path: str,
        output_dir: str,
        line: Line,
        profile: CloneProfile,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> str:
        if not isinstance(output_path, str) or not _SAFE_REL_PATH.match(output_path):
            raise voice_error(
                "clone export path must be a safe project-relative path",
                ADAPTER_INPUT_INVALID,
            )
        self._authorize_export(
            profile=profile,
            ledger=ledger,
            context=context,
            at_iso=at_iso,
        )
        output = self._render_unlocked(line=line, profile=profile)
        full = os.path.join(output_dir, *output_path.split("/"))
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(output.wav_bytes)
        return output_path

    def authorize_cloud_egress(
        self,
        *,
        grant_ids: tuple[str, ...],
        provider_id: str,
        data_classes: tuple[str, ...],
        territory: str,
        retention_days: int,
        ledger: ConsentLedger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> tuple[str, ...]:
        return ledger.authorize_cloud_egress(
            grant_ids=grant_ids,
            provider_id=provider_id,
            data_classes=data_classes,
            territory=territory,
            retention_days=retention_days,
            at_iso=at_iso,
            context=context,
        )


__all__ = ["CloneProfile", "CloneRenderer"]
