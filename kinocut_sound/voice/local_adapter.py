"""Local synthetic TTS adapter and the typed ``TtsAdapter`` protocol.

The local adapter renders deterministic synthetic audio from a
:class:`kinocut_sound.Line` plus a project :class:`PronunciationDictionary`
without reaching for any cloud provider, embedding, or model download. It
synthesizes a small PCM waveform in pure Python so the leaf's tests need no
external TTS engine, no FFmpeg/SoX binary, and no network. The output is
signal-equivalent deterministic across identical inputs: same slot + same
line + same dictionary + same adapter configuration produces byte-identical
WAV data.

Cloud adapters exist only as descriptors plus a fail-closed stub. The stub
never constructs a cloud client, opens a socket, or reads a credential; its
``probe()`` always returns ``available=False`` with a bounded reason. A cloud
render is raised as :class:`VoiceError(code=CLOUD_NOT_ALLOWED)` so a host
path, provider name, or raw provider error can never leak.

Design references (sonic-world design):
* M1 — Voice Generation: typed TTS adapter, local-first, cloud-opt-in.
* Capability & Adapter Registry — Adapter protocol + descriptor + probe.
* Privacy & security — never leak raw text, host paths, or provider errors.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from kinocut_sound._canonical import BoundedCode, Sha256, canonical_digest
from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
    CostDisclosure,
)
from kinocut_sound.lines import Line
from kinocut_sound.registry import Adapter

from kinocut_sound.voice._errors import (
    ADAPTER_INPUT_INVALID,
    ADAPTER_OUTPUT_INVALID,
    CLOUD_NOT_ALLOWED,
    VoiceError,
    bounded_voice_error,
    voice_error,
)
from kinocut_sound.voice.pronunciation import PronunciationDictionary
from kinocut_sound.voice.prosody import (
    EffectiveProsody,
    EmotionDirection,
    resolve_emotion,
    resolve_prosody,
)
from kinocut_sound.voice.roster import VoiceSlot

# --- Voice-leaf private defaults ---
# TODO(controller): consider promoting these to ``kinocut_sound/defaults.py``
# if S6/S10 share the same synthesis reference defaults.
DEFAULT_SAMPLE_RATE_HZ: int = 22050
DEFAULT_CHANNEL_COUNT: int = 1
DEFAULT_REFERENCE_PITCH_HZ: float = 220.0  # A3
DEFAULT_SECONDS_PER_CHAR: float = 0.08
DEFAULT_MIN_DURATION_SECONDS: float = 0.25
DEFAULT_MAX_DURATION_SECONDS: float = 60.0
DEFAULT_PEAK_AMPLITUDE_LINEAR: float = 0.94  # leaves headroom under 0 dBFS
DEFAULT_ATTACK_SECONDS: float = 0.012
DEFAULT_RELEASE_SECONDS: float = 0.020
DEFAULT_HARMONIC_RATIO: float = 0.30

# Bounded synthesis envelope. The recipe is built inside these limits so an
# out-of-range slot/prosody/emotion combination cannot overflow.
_MAX_TREMOLO_DEPTH: float = 1.0
_MAX_BRIGHTNESS: float = 1.0
_MAX_PITCH_DRIFT_CENTS: float = 100.0


@dataclass(frozen=True)
class SynthesisRecipe:
    """Deterministic synthesis parameters derived from a slot + line.

    Every field is a plain number, so two recipes that compare equal produce
    byte-identical WAV data. ``text_hash`` and ``pronunciation_fingerprint``
    are part of the recipe so identity-affecting inputs alter the output
    bytes (and therefore the output hash) even when synthesis parameters are
    otherwise identical.
    """

    base_frequency_hz: float
    duration_seconds: float
    gain_linear: float
    brightness: float
    tremolo_depth: float
    tremolo_rate_hz: float
    pitch_drift_cents: float
    pitch_drift_rate_hz: float
    attack_seconds: float
    release_seconds: float
    harmonic_ratio: float
    text_phase_offset: float
    text_hash: Sha256
    slot_id: str
    pronunciation_fingerprint: Sha256
    sample_rate_hz: int


@dataclass(frozen=True)
class SynthesisOutput:
    """The rendered PCM bytes plus the derived identity."""

    wav_bytes: bytes
    output_hash: Sha256
    duration_seconds: float
    sample_rate_hz: int
    channel_count: int
    recipe_digest: Sha256


@runtime_checkable
class TtsAdapter(Adapter, Protocol):
    """Typed TTS adapter surface: ``Adapter`` plus a ``render`` method."""

    def render(
        self,
        *,
        slot: VoiceSlot,
        line: Line,
        dictionary: PronunciationDictionary | None = None,
    ) -> SynthesisOutput:
        """Render one line to a deterministic WAV-byte synthesis output."""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _bounded_duration(text_length_chars: int, rate: float) -> float:
    raw = DEFAULT_SECONDS_PER_CHAR * max(1, int(text_length_chars)) / max(0.1, rate)
    return _clamp(raw, DEFAULT_MIN_DURATION_SECONDS, DEFAULT_MAX_DURATION_SECONDS)


def _text_phase_offset(text_hash: Sha256) -> float:
    """Return a bounded phase offset (radians) derived from a text hash.

    Maps the leading 8 hex chars of a bounded SHA-256 into ``[0, 2π)`` so
    distinct text inputs yield distinct starting phases for the second
    harmonic. The result is bounded and deterministic — same hash always
    produces the same offset.
    """

    hex_part = text_hash.removeprefix("sha256:")
    try:
        head = int(hex_part[:8], 16)
    except (ValueError, IndexError):
        head = 0
    return (head / 0xFFFFFFFF) * (2.0 * math.pi)


def _harmonic_mix(
    *,
    brightness: float,
    pronunciation_fingerprint: Sha256,
    base_harmonic_ratio: float,
) -> float:
    """Bind the dictionary fingerprint into the harmonic mix.

    A non-empty dictionary shifts the second-harmonic amplitude by a small
    deterministic delta derived from the fingerprint's leading bytes. This
    guarantees a pronunciation override measurably changes the rendered
    bytes, not just the output hash.
    """

    delta = 0.0
    hex_part = pronunciation_fingerprint.removeprefix("sha256:")
    if hex_part:
        try:
            head = int(hex_part[:8], 16)
        except ValueError:
            head = 0
        # Map a 32-bit value to [-0.08, +0.08].
        delta = ((head / 0xFFFFFFFF) - 0.5) * 0.16
    return _clamp(base_harmonic_ratio + delta * brightness, 0.0, 0.6)


def build_recipe(
    *,
    slot: VoiceSlot,
    line: Line,
    dictionary: PronunciationDictionary | None,
    effective: EffectiveProsody,
    emotion: EmotionDirection,
    sample_rate_hz: int,
    pronunciation_fingerprint: Sha256,
) -> SynthesisRecipe:
    """Build a deterministic synthesis recipe from validated inputs."""

    semitones = effective.pitch_semitones
    base_frequency_hz = DEFAULT_REFERENCE_PITCH_HZ * (2.0 ** (semitones / 12.0))
    duration_seconds = _bounded_duration(line.text_length_chars, effective.rate)

    # Linear gain from dB. Cap under the peak amplitude so true-peak stays < 0.
    gain_linear = DEFAULT_PEAK_AMPLITUDE_LINEAR * (10.0 ** (effective.volume_db / 20.0))
    gain_linear = _clamp(gain_linear, 0.0, DEFAULT_PEAK_AMPLITUDE_LINEAR)

    # Brightness blends slot formant offset, per-line emphasis, and emotion.
    formant_brightness = _clamp(0.5 + (effective.formant_offset / 12.0) * 0.5, 0.0, _MAX_BRIGHTNESS)
    emphasis_brightness = _clamp(effective.emphasis, 0.0, _MAX_BRIGHTNESS)
    brightness = _clamp(
        0.5 * formant_brightness + 0.3 * emotion.brightness + 0.2 * emphasis_brightness,
        0.0,
        _MAX_BRIGHTNESS,
    )

    harmonic_ratio = _harmonic_mix(
        brightness=brightness,
        pronunciation_fingerprint=pronunciation_fingerprint,
        base_harmonic_ratio=DEFAULT_HARMONIC_RATIO,
    )

    tremolo_depth = _clamp(abs(emotion.tremolo_depth), 0.0, _MAX_TREMOLO_DEPTH)
    tremolo_rate_hz = 4.5 + 0.5 * emotion.intensity
    pitch_drift_cents = _clamp(emotion.pitch_drift_cents, -_MAX_PITCH_DRIFT_CENTS, _MAX_PITCH_DRIFT_CENTS)
    pitch_drift_rate_hz = 0.7

    attack_seconds = DEFAULT_ATTACK_SECONDS * (0.5 + emotion.attack_smoothness)
    release_seconds = DEFAULT_RELEASE_SECONDS

    return SynthesisRecipe(
        base_frequency_hz=base_frequency_hz,
        duration_seconds=duration_seconds,
        gain_linear=gain_linear,
        brightness=brightness,
        tremolo_depth=tremolo_depth,
        tremolo_rate_hz=tremolo_rate_hz,
        pitch_drift_cents=pitch_drift_cents,
        pitch_drift_rate_hz=pitch_drift_rate_hz,
        attack_seconds=attack_seconds,
        release_seconds=release_seconds,
        harmonic_ratio=harmonic_ratio,
        text_phase_offset=_text_phase_offset(line.text_hash),
        text_hash=line.text_hash,
        slot_id=slot.slot_id,
        pronunciation_fingerprint=pronunciation_fingerprint,
        sample_rate_hz=sample_rate_hz,
    )


def _recipe_digest(recipe: SynthesisRecipe) -> Sha256:
    payload = {
        "base_frequency_hz": recipe.base_frequency_hz,
        "duration_seconds": recipe.duration_seconds,
        "gain_linear": recipe.gain_linear,
        "brightness": recipe.brightness,
        "tremolo_depth": recipe.tremolo_depth,
        "tremolo_rate_hz": recipe.tremolo_rate_hz,
        "pitch_drift_cents": recipe.pitch_drift_cents,
        "pitch_drift_rate_hz": recipe.pitch_drift_rate_hz,
        "attack_seconds": recipe.attack_seconds,
        "release_seconds": recipe.release_seconds,
        "harmonic_ratio": recipe.harmonic_ratio,
        "text_phase_offset": recipe.text_phase_offset,
        "text_hash": recipe.text_hash,
        "slot_id": recipe.slot_id,
        "pronunciation_fingerprint": recipe.pronunciation_fingerprint,
        "sample_rate_hz": recipe.sample_rate_hz,
    }
    return canonical_digest(payload)


def _synthesize_pcm(recipe: SynthesisRecipe) -> tuple[bytes, float]:
    """Render a deterministic mono 16-bit PCM byte string."""

    sample_rate = int(recipe.sample_rate_hz)
    if sample_rate <= 0:
        raise voice_error("sample rate must be positive", ADAPTER_OUTPUT_INVALID)
    n_samples = max(1, math.ceil(recipe.duration_seconds * sample_rate))
    attack_samples = max(0, int(recipe.attack_seconds * sample_rate))
    release_samples = max(0, int(recipe.release_seconds * sample_rate))

    base_freq = recipe.base_frequency_hz
    gain = recipe.gain_linear
    brightness = recipe.brightness
    harmonic_ratio = recipe.harmonic_ratio
    tremolo_depth = recipe.tremolo_depth
    tremolo_rate = recipe.tremolo_rate_hz
    drift_cents = recipe.pitch_drift_cents
    drift_rate = recipe.pitch_drift_rate_hz
    text_phase = recipe.text_phase_offset

    two_pi = 2.0 * math.pi
    phase = 0.0
    drift_ratio_factor = 2.0 ** (drift_cents / 1200.0) - 1.0
    samples = bytearray(n_samples * 2)
    for i in range(n_samples):
        t = i / sample_rate
        # Slow pitch drift modulates the instantaneous frequency.
        drift = 1.0 + drift_ratio_factor * math.sin(two_pi * drift_rate * t)
        freq_instant = base_freq * drift
        phase += two_pi * freq_instant / sample_rate
        # Tremolo shapes amplitude; center it at 1.0.
        amp_mod = 1.0 - tremolo_depth * 0.5 * (1.0 - math.sin(two_pi * tremolo_rate * t))
        fundamental = math.sin(phase)
        # The second harmonic carries the text-derived phase offset so
        # distinct text inputs produce measurably distinct output bytes.
        harmonic = math.sin(2.0 * phase + text_phase) if harmonic_ratio > 0 else 0.0
        # Brightness shapes how much harmonic reaches the mix.
        harmonic_amp = harmonic_ratio * brightness
        sample_value = gain * amp_mod * (fundamental + harmonic_amp * harmonic)
        # Attack/release envelope to avoid clicks at the boundaries.
        if attack_samples > 0 and i < attack_samples:
            sample_value *= i / attack_samples
        if release_samples > 0 and i >= n_samples - release_samples:
            tail_index = n_samples - 1 - i
            sample_value *= max(0, tail_index) / release_samples
        # Saturate softly to ensure no overflow past 16-bit range.
        saturated = max(-1.0, min(1.0, sample_value))
        pcm = int(saturated * 32767.0)
        struct.pack_into("<h", samples, i * 2, pcm)
    duration = n_samples / sample_rate
    return bytes(samples), duration


def _wav_bytes(pcm: bytes, *, sample_rate_hz: int, channel_count: int) -> bytes:
    """Wrap raw little-endian PCM into a canonical WAV container."""

    if channel_count != 1:
        raise voice_error(
            "only mono PCM synthesis is supported",
            ADAPTER_OUTPUT_INVALID,
        )
    byte_rate = sample_rate_hz * channel_count * 2
    block_align = channel_count * 2
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channel_count,
        sample_rate_hz,
        byte_rate,
        block_align,
        16,  # bits per sample
        b"data",
        data_size,
    )
    return header + pcm


def _hash_bytes(wav_bytes: bytes) -> Sha256:
    return "sha256:" + hashlib.sha256(wav_bytes).hexdigest()


def dictionary_fingerprint(
    dictionary: PronunciationDictionary | None,
    line: Line,
) -> Sha256:
    """Return a bounded fingerprint of the dictionary + line overrides.

    A line carries its own pronunciation overrides; a project dictionary
    supplies overrides for any term hash. The combined fingerprint is the
    canonical hash of both, sorted by term hash. The empty fingerprint is a
    stable zero-marker so a missing dictionary produces a deterministic
    fallback rather than an unspecified value.
    """

    entries: list[tuple[str, str]] = []
    if dictionary is not None:
        for term_hash in dictionary.term_hashes:
            override = dictionary.resolve(term_hash)
            if override is not None:
                entries.append((term_hash, override.ipa))
    for override in line.pronunciation_overrides:
        entries.append((override.term_hash, override.ipa))
    entries.sort(key=lambda item: item[0])
    payload = {"entries": [{"term_hash": t, "ipa": i} for t, i in entries]}
    return canonical_digest(payload)


class LocalSynthesisAdapter:
    """Local-first synthetic TTS adapter.

    Renders a deterministic PCM WAV from a roster slot, a line, and an
    optional pronunciation dictionary. The adapter never reaches for a
    cloud provider, never reads a credential, and never opens a socket. Its
    descriptor is statically code-owned and its probe always returns
    ``available=True`` because the synthesizer is pure Python.
    """

    __slots__ = ("_channel_count", "_descriptor", "_sample_rate_hz")

    def __init__(
        self,
        *,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        channel_count: int = DEFAULT_CHANNEL_COUNT,
    ) -> None:
        if isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, int):
            raise voice_error("sample_rate_hz must be an integer", ADAPTER_INPUT_INVALID)
        if sample_rate_hz <= 0:
            raise voice_error("sample_rate_hz must be positive", ADAPTER_INPUT_INVALID)
        if channel_count != DEFAULT_CHANNEL_COUNT:
            raise voice_error(
                "LocalSynthesisAdapter supports mono output only",
                ADAPTER_INPUT_INVALID,
            )
        self._sample_rate_hz = sample_rate_hz
        self._channel_count = channel_count
        self._descriptor = AdapterDescriptor(
            adapter_id="tts_local_synth",
            kind="tts",
            locality=AdapterLocality.LOCAL,
            provider_class="local_synth",
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    @property
    def sample_rate_hz(self) -> int:
        return self._sample_rate_hz

    @property
    def channel_count(self) -> int:
        return self._channel_count

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self._descriptor.adapter_id,
            available=True,
        )

    def render(
        self,
        *,
        slot: VoiceSlot,
        line: Line,
        dictionary: PronunciationDictionary | None = None,
    ) -> SynthesisOutput:
        effective = resolve_prosody(slot, line.prosody)
        emotion = resolve_emotion(line.emotion)
        fingerprint = dictionary_fingerprint(dictionary, line)
        recipe = build_recipe(
            slot=slot,
            line=line,
            dictionary=dictionary,
            effective=effective,
            emotion=emotion,
            sample_rate_hz=self._sample_rate_hz,
            pronunciation_fingerprint=fingerprint,
        )
        pcm, duration = _synthesize_pcm(recipe)
        wav = _wav_bytes(pcm, sample_rate_hz=self._sample_rate_hz, channel_count=self._channel_count)
        return SynthesisOutput(
            wav_bytes=wav,
            output_hash=_hash_bytes(wav),
            duration_seconds=duration,
            sample_rate_hz=self._sample_rate_hz,
            channel_count=self._channel_count,
            recipe_digest=_recipe_digest(recipe),
        )


# --- Cloud-adapter stub ------------------------------------------------
# A cloud adapter is a typed descriptor plus a fail-closed stub. It never
# constructs a network client, never reads a credential, and never opens a
# socket. Its ``probe()`` is always unavailable with a bounded reason, and
# ``render()`` raises before any I/O.

DEFAULT_CLOUD_PROVIDER_ID = "elevenlabs"
DEFAULT_CLOUD_REGION = "us-east-1"
DEFAULT_CLOUD_DATA_CLASSES: tuple[str, ...] = ("reference_audio", "transcript_text")
DEFAULT_CLOUD_RETENTION_DAYS: int = 30
DEFAULT_CLOUD_COST_USD: float = 0.05


def cloud_descriptor(
    *,
    provider_id: str = DEFAULT_CLOUD_PROVIDER_ID,
    region: str = DEFAULT_CLOUD_REGION,
) -> AdapterDescriptor:
    """Return a static cloud-adapter descriptor with a cost disclosure.

    The disclosure is always ``confirmed=False``: a caller must explicitly
    confirm cost, region, and retention through the authorization layer
    before this descriptor could ever be selected for a render.
    """

    disclosure = CostDisclosure(
        provider_id=provider_id,
        region=region,
        data_classes=DEFAULT_CLOUD_DATA_CLASSES,
        retention_ceiling_days=DEFAULT_CLOUD_RETENTION_DAYS,
        estimated_cost_usd_per_call=DEFAULT_CLOUD_COST_USD,
        confirmed=False,
    )
    return AdapterDescriptor(
        adapter_id=f"tts_cloud_{provider_id}",
        kind="tts",
        locality=AdapterLocality.CLOUD,
        provider_class=provider_id,
        cost_disclosure=disclosure,
    )


class CloudTtsAdapterStub:
    """Fail-closed cloud TTS adapter stub.

    Holds a static cloud descriptor so the registry can expose it, but its
    ``probe()`` always returns ``available=False`` with a bounded reason
    (``cloud_not_allowed``) and ``render()`` raises before any I/O. No
    credential handle, URL, or provider client is constructed at any point.
    """

    __slots__ = ("_descriptor",)

    def __init__(self, descriptor: AdapterDescriptor | None = None) -> None:
        if descriptor is None:
            descriptor = cloud_descriptor()
        if descriptor.locality is not AdapterLocality.CLOUD:
            raise voice_error(
                "CloudTtsAdapterStub requires a cloud-locality descriptor",
                ADAPTER_INPUT_INVALID,
            )
        self._descriptor = descriptor

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self._descriptor.adapter_id,
            available=False,
            reason_code=CLOUD_NOT_ALLOWED,
            remediation="Confirm cloud opt-in and authorization before use.",
        )

    def render(
        self,
        *,
        slot: VoiceSlot,
        line: Line,
        dictionary: PronunciationDictionary | None = None,
    ) -> SynthesisOutput:
        raise bounded_voice_error(
            "cloud TTS render requires explicit opt-in and a confirmed disclosure",
            CLOUD_NOT_ALLOWED,
        )


def cloud_allowed(*, policy: Mapping[str, object] | None, descriptor: AdapterDescriptor) -> bool:
    """Return whether a cloud descriptor is permitted under ``policy``.

    A cloud render is allowed only when ``policy["allow_cloud"]`` is the
    literal ``True`` and ``policy["cloud_approval"]`` is a bounded code that
    matches the descriptor's adapter_id. Anything else — missing policy,
    wrong shape, ``allow_cloud`` set but no approval, a different provider —
    returns ``False``. The function never opens a socket or reads a secret.
    """

    if not isinstance(policy, Mapping):
        return False
    allow = policy.get("allow_cloud")
    if allow is not True:
        return False
    approval = policy.get("cloud_approval")
    if not isinstance(approval, str):
        return False
    try:
        BoundedCode(approval)
    except (TypeError, ValueError):
        return False
    return approval == descriptor.adapter_id


__all__ = [
    "DEFAULT_CHANNEL_COUNT",
    "DEFAULT_CLOUD_COST_USD",
    "DEFAULT_CLOUD_DATA_CLASSES",
    "DEFAULT_CLOUD_PROVIDER_ID",
    "DEFAULT_CLOUD_REGION",
    "DEFAULT_CLOUD_RETENTION_DAYS",
    "DEFAULT_MAX_DURATION_SECONDS",
    "DEFAULT_MIN_DURATION_SECONDS",
    "DEFAULT_PEAK_AMPLITUDE_LINEAR",
    "DEFAULT_REFERENCE_PITCH_HZ",
    "DEFAULT_SAMPLE_RATE_HZ",
    "DEFAULT_SECONDS_PER_CHAR",
    "CloudTtsAdapterStub",
    "LocalSynthesisAdapter",
    "PronunciationDictionary",
    "SynthesisOutput",
    "SynthesisRecipe",
    "TtsAdapter",
    "VoiceError",
    "VoiceSlot",
    "build_recipe",
    "cloud_allowed",
    "cloud_descriptor",
    "dictionary_fingerprint",
]
