"""Capability and command discovery for sound public parity."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SoundCapabilityManifest:
    capabilities: tuple[str, ...]
    flat_commands: tuple[str, ...]
    namespaced_commands: tuple[str, ...]
    non_tty_json: bool = True
    local_first: bool = True


_FLAT = (
    "sound-plan-validate",
    "sound-voice-batch",
    "sound-mix-render",
    "sound-qa-loudness",
    "sound-qa-asr",
    "sound-capabilities",
)
_NS = (
    "sound.plan.validate",
    "sound.voice.batch",
    "sound.mix.render",
    "sound.qa.loudness",
    "sound.qa.asr",
    "sound.capabilities",
)
_CAPS = (
    "voice_local",
    "voice_clone",
    "mix_stems",
    "qa_loudness",
    "qa_asr_fake",
    "post_chain",
    "world_ambience",
)


def list_flat_commands() -> tuple[str, ...]:
    return _FLAT


def list_namespaced_commands() -> tuple[str, ...]:
    return _NS


def discover_sound_capabilities() -> SoundCapabilityManifest:
    return SoundCapabilityManifest(
        capabilities=_CAPS,
        flat_commands=_FLAT,
        namespaced_commands=_NS,
        non_tty_json=True,
        local_first=True,
    )
