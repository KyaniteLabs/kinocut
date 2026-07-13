"""``kinocut_sound.voice`` — base voice generation leaf (S5).

A sidecar package that implements the Sonic World base-voice leaf on top of
the existing :mod:`kinocut_sound` typed contracts. It owns:

* A static, code-owned roster of 15+ distinct :class:`VoiceSlot` identities
  with stable bounded ids.
* A local-first :class:`LocalSynthesisAdapter` that probes available and
  renders signal-equivalent deterministic synthetic audio without implicit
  cloud selection or model download.
* A fail-closed :class:`CloudTtsAdapterStub` that exists only as a typed
  descriptor and refuses to render without explicit opt-in.
* A project :class:`PronunciationDictionary` keyed by bounded term hashes.
* Prosody/emotion normalization and bounded synthesis-direction axes.
* A deterministic :class:`BatchPlanner` that walks a SoundPlan's lines and
  emits per-cue rendered clip receipts plus a single additive
  :class:`SoundReceiptSection`.

The package imports nothing from any ``kinocut.*`` runtime module. It composes
the public :mod:`kinocut_sound` contracts (Line, ProfileRef, Prosody, Emotion,
SoundPlan, SoundReceiptSection, AdapterDescriptor, CapabilityResult, etc.)
without widening their surfaces.

Design references: ``docs/superpowers/specs/2026-07-11-kinocut-sound-sonic-world-design.md``
(M1 — Voice Generation; W1.1, W1.4, W1.5, W1.6, W1.7).
"""

from __future__ import annotations

from kinocut_sound.voice._errors import (
    ADAPTER_CANCELLED,
    ADAPTER_INPUT_INVALID,
    ADAPTER_LIMIT_EXCEEDED,
    ADAPTER_OUTPUT_INVALID,
    ADAPTER_TIMEOUT,
    BATCH_PLAN_INVALID,
    CLOUD_NOT_ALLOWED,
    EMOTION_OUT_OF_RANGE,
    PRONUNCIATION_INVALID,
    PROSODY_OUT_OF_RANGE,
    ROSTER_EXCEEDS_CEILING,
    ROSTER_INVALID,
    ROSTER_UNKNOWN,
    VOICE_UNAVAILABLE,
    VoiceError,
    bounded_voice_error,
    voice_error,
)
from kinocut_sound.voice.batch import (
    DEFAULT_BATCH_OPERATION,
    DEFAULT_BATCH_ROLE,
    DEFAULT_BATCH_TOOL,
    DEFAULT_MAX_BATCH_LINES,
    BatchPlanner,
    BatchResult,
    CancelCheck,
    RenderedClip,
    SlotResolver,
    default_slot_resolver,
)
from kinocut_sound.voice.local_adapter import (
    DEFAULT_CHANNEL_COUNT,
    DEFAULT_CLOUD_COST_USD,
    DEFAULT_CLOUD_DATA_CLASSES,
    DEFAULT_CLOUD_PROVIDER_ID,
    DEFAULT_CLOUD_REGION,
    DEFAULT_CLOUD_RETENTION_DAYS,
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_MIN_DURATION_SECONDS,
    DEFAULT_PEAK_AMPLITUDE_LINEAR,
    DEFAULT_REFERENCE_PITCH_HZ,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_SECONDS_PER_CHAR,
    CloudTtsAdapterStub,
    LocalSynthesisAdapter,
    SynthesisOutput,
    SynthesisRecipe,
    TtsAdapter,
    build_recipe,
    cloud_allowed,
    cloud_descriptor,
    dictionary_fingerprint,
)
from kinocut_sound.voice.pronunciation import (
    MAX_DICTIONARY_ENTRIES,
    PronunciationDictionary,
)
from kinocut_sound.voice.prosody import (
    EffectiveProsody,
    EmotionDirection,
    known_emotion_labels,
    resolve_emotion,
    resolve_prosody,
)
from kinocut_sound.voice.roster import (
    MAX_BASE_PITCH_SEMITONES,
    MAX_BASE_RATE,
    MAX_BASE_VOLUME_DB,
    MAX_FORMANT_OFFSET,
    MAX_ROSTER_SLOTS,
    MIN_BASE_PITCH_SEMITONES,
    MIN_BASE_RATE,
    MIN_BASE_VOLUME_DB,
    MIN_FORMANT_OFFSET,
    MIN_ROSTER_SLOTS,
    VoiceRoster,
    VoiceSlot,
    VoiceSlotBase,
    default_roster,
)

__version__ = "0.1.0"

__all__ = [
    "ADAPTER_CANCELLED",
    "ADAPTER_INPUT_INVALID",
    "ADAPTER_LIMIT_EXCEEDED",
    "ADAPTER_OUTPUT_INVALID",
    "ADAPTER_TIMEOUT",
    "BATCH_PLAN_INVALID",
    "CLOUD_NOT_ALLOWED",
    "DEFAULT_BATCH_OPERATION",
    "DEFAULT_BATCH_ROLE",
    "DEFAULT_BATCH_TOOL",
    "DEFAULT_CHANNEL_COUNT",
    "DEFAULT_CLOUD_COST_USD",
    "DEFAULT_CLOUD_DATA_CLASSES",
    "DEFAULT_CLOUD_PROVIDER_ID",
    "DEFAULT_CLOUD_REGION",
    "DEFAULT_CLOUD_RETENTION_DAYS",
    "DEFAULT_MAX_BATCH_LINES",
    "DEFAULT_MAX_DURATION_SECONDS",
    "DEFAULT_MIN_DURATION_SECONDS",
    "DEFAULT_PEAK_AMPLITUDE_LINEAR",
    "DEFAULT_REFERENCE_PITCH_HZ",
    "DEFAULT_SAMPLE_RATE_HZ",
    "DEFAULT_SECONDS_PER_CHAR",
    "EMOTION_OUT_OF_RANGE",
    "MAX_BASE_PITCH_SEMITONES",
    "MAX_BASE_RATE",
    "MAX_BASE_VOLUME_DB",
    "MAX_DICTIONARY_ENTRIES",
    "MAX_FORMANT_OFFSET",
    "MAX_ROSTER_SLOTS",
    "MIN_BASE_PITCH_SEMITONES",
    "MIN_BASE_RATE",
    "MIN_BASE_VOLUME_DB",
    "MIN_FORMANT_OFFSET",
    "MIN_ROSTER_SLOTS",
    "PRONUNCIATION_INVALID",
    "PROSODY_OUT_OF_RANGE",
    "ROSTER_EXCEEDS_CEILING",
    "ROSTER_INVALID",
    "ROSTER_UNKNOWN",
    "VOICE_UNAVAILABLE",
    "BatchPlanner",
    "BatchResult",
    "CancelCheck",
    "CloudTtsAdapterStub",
    "EffectiveProsody",
    "EmotionDirection",
    "LocalSynthesisAdapter",
    "PronunciationDictionary",
    "RenderedClip",
    "SlotResolver",
    "SynthesisOutput",
    "SynthesisRecipe",
    "TtsAdapter",
    "VoiceError",
    "VoiceRoster",
    "VoiceSlot",
    "VoiceSlotBase",
    "bounded_voice_error",
    "build_recipe",
    "cloud_allowed",
    "cloud_descriptor",
    "default_roster",
    "default_slot_resolver",
    "dictionary_fingerprint",
    "known_emotion_labels",
    "resolve_emotion",
    "resolve_prosody",
    "voice_error",
]
