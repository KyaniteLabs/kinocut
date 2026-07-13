"""Prosody & emotion normalization for the voice leaf.

Composes a :class:`kinocut_sound.VoiceSlot`'s base parametric shape with a
:class:`kinocut_sound.Line`'s per-call :class:`Prosody` and :class:`Emotion`
overrides, producing the effective synthesis parameters the local TTS adapter
consumes. All outputs are validated against the existing
``kinocut_sound.limits`` envelope so a slot base cannot push a render past
the plan's hard bounds.

This module performs no I/O and synthesizes no audio — it is a pure
deterministic function over the existing typed contracts. The bounded
emotion direction maps a small closed set of emotion labels to numeric
synthesis axes (brightness, tremolo depth, attack) that the local adapter
threads into its deterministic signal expression.

Design references (sonic-world design):
* M1 — Voice Generation: per-character prosody (W1.4), parametric emotion
  direction (W1.6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from kinocut_sound.lines import Emotion, Prosody
from kinocut_sound.limits import (
    MAX_NORMALIZED_LEVEL,
    MAX_PROSODY_PITCH_SEMITONES,
    MAX_PROSODY_RATE,
    MAX_PROSODY_VOLUME_DB,
    MIN_NORMALIZED_LEVEL,
    MIN_PROSODY_PITCH_SEMITONES,
    MIN_PROSODY_RATE,
    MIN_PROSODY_VOLUME_DB,
)

from kinocut_sound.voice._errors import (
    EMOTION_OUT_OF_RANGE,
    PROSODY_OUT_OF_RANGE,
    bounded_voice_error,
)
from kinocut_sound.voice.roster import VoiceSlot

# --- Voice-leaf private envelope (mirrors the lines.Prosody envelope) ---
# TODO(controller): these mirror kinocut_sound/limits.py exactly so the voice
# leaf never has to reach across modules; promote to limits.py if shared.
_PROSODY_RATE_BAND: tuple[float, float] = (MIN_PROSODY_RATE, MAX_PROSODY_RATE)
_PITCH_BAND: tuple[float, float] = (MIN_PROSODY_PITCH_SEMITONES, MAX_PROSODY_PITCH_SEMITONES)
_VOLUME_BAND: tuple[float, float] = (MIN_PROSODY_VOLUME_DB, MAX_PROSODY_VOLUME_DB)
_LEVEL_BAND: tuple[float, float] = (MIN_NORMALIZED_LEVEL, MAX_NORMALIZED_LEVEL)


@dataclass(frozen=True)
class EffectiveProsody:
    """Composed synthesis parameters ready for the local adapter.

    ``pitch_semitones`` is the slot base plus the per-line pitch offset.
    ``rate`` is the slot base multiplied by the per-line rate. ``volume_db``
    is the slot base plus the per-line volume. ``emphasis`` is the per-line
    emphasis (a slot may declare a base emphasis in the future; today the
    base is zero). ``formant_offset`` is the slot's base formant offset
    threaded through untouched.
    """

    pitch_semitones: float
    rate: float
    volume_db: float
    emphasis: float
    formant_offset: float


@dataclass(frozen=True)
class EmotionDirection:
    """Bounded numeric axes the local adapter threads into its signal.

    ``brightness`` shifts the second-harmonic amplitude. ``tremolo_depth``
    shapes a slow amplitude modulation. ``attack_smoothness`` shapes the
    envelope's onset. ``pitch_drift_cents`` adds a slow pitch wobble. All
    fields are bounded into ``[-1, 1]`` (or ``[0, 1]`` for brightness and
    attack_smoothness) so an out-of-range emotion label or intensity cannot
    overflow the synthesis expression.
    """

    label: str
    intensity: float
    brightness: float
    tremolo_depth: float
    attack_smoothness: float
    pitch_drift_cents: float


# Closed emotion-label → axis-shape table. Intensity scales each axis. A
# label outside this set is normalized to ``neutral`` with a zeroed shape.
_EMOTION_SHAPES: Mapping[str, tuple[float, float, float, float]] = {
    # brightness, tremolo_depth, attack_smoothness, pitch_drift_cents
    "neutral": (0.25, 0.0, 0.5, 0.0),
    "calm": (0.20, 0.05, 0.85, -5.0),
    "warm": (0.30, 0.05, 0.75, 0.0),
    "confessional_dread": (0.10, 0.30, 0.95, -25.0),
    "joy": (0.85, 0.10, 0.20, 10.0),
    "excited": (0.90, 0.20, 0.10, 15.0),
    "sad": (0.15, 0.25, 0.95, -30.0),
    "fear": (0.40, 0.55, 0.30, 35.0),
    "anger": (0.55, 0.45, 0.05, 5.0),
    "tenderness": (0.30, 0.05, 0.90, -5.0),
    "awe": (0.50, 0.10, 0.85, 0.0),
    "resolve": (0.40, 0.0, 0.25, 0.0),
    "playful": (0.70, 0.15, 0.20, 8.0),
    "irony": (0.45, 0.05, 0.40, -8.0),
    "urgency": (0.60, 0.30, 0.05, 20.0),
    "mirth": (0.80, 0.20, 0.15, 12.0),
}


def _check_band(value: float, band: tuple[float, float], label: str, code: str) -> float:
    low, high = band
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise bounded_voice_error(f"{label} must be numeric", code)
    if value < low or value > high:
        raise bounded_voice_error(
            f"{label} is outside the voice envelope",
            code,
        )
    return float(value)


def resolve_prosody(slot: VoiceSlot, prosody: Prosody) -> EffectiveProsody:
    """Compose ``slot.base`` with per-line ``prosody`` overrides.

    ``rate`` is multiplicative; pitch and volume are additive; emphasis and
    formant offset come from the slot base / line directly. The composed
    values are clamped into the plan envelope so a slot base cannot push a
    render past the design's hard bounds.
    """

    if not isinstance(slot, VoiceSlot):
        raise bounded_voice_error(
            "voice slot is required to resolve prosody",
            PROSODY_OUT_OF_RANGE,
        )
    if not isinstance(prosody, Prosody):
        raise bounded_voice_error(
            "prosody must be a Prosody instance",
            PROSODY_OUT_OF_RANGE,
        )

    base = slot.base
    rate = base.rate * prosody.rate
    pitch = base.pitch_semitones + prosody.pitch
    volume = base.volume_db + prosody.volume_db
    emphasis = prosody.emphasis
    formant_offset = base.formant_offset

    rate = _check_band(rate, _PROSODY_RATE_BAND, "composed rate", PROSODY_OUT_OF_RANGE)
    pitch = _check_band(pitch, _PITCH_BAND, "composed pitch", PROSODY_OUT_OF_RANGE)
    volume = _check_band(volume, _VOLUME_BAND, "composed volume", PROSODY_OUT_OF_RANGE)
    emphasis = _check_band(emphasis, _LEVEL_BAND, "emphasis", PROSODY_OUT_OF_RANGE)
    formant_offset = _check_band(
        formant_offset,
        (-12.0, 12.0),
        "formant offset",
        PROSODY_OUT_OF_RANGE,
    )
    return EffectiveProsody(
        pitch_semitones=pitch,
        rate=rate,
        volume_db=volume,
        emphasis=emphasis,
        formant_offset=formant_offset,
    )


def resolve_emotion(emotion: Emotion) -> EmotionDirection:
    """Map a bounded :class:`Emotion` to bounded numeric synthesis axes.

    Unknown labels (not in the closed table) are normalized to ``neutral``;
    this is *not* an error because the line contract accepts any bounded
    label, and a future label may ride in before its shape table entry is
    added. Intensity is bounded into ``[0, 1]`` regardless of the source.
    """

    if not isinstance(emotion, Emotion):
        raise bounded_voice_error(
            "emotion must be an Emotion instance",
            EMOTION_OUT_OF_RANGE,
        )
    intensity = _check_band(
        emotion.intensity,
        _LEVEL_BAND,
        "emotion intensity",
        EMOTION_OUT_OF_RANGE,
    )
    shape = _EMOTION_SHAPES.get(emotion.label, _EMOTION_SHAPES["neutral"])
    brightness_raw, tremolo_raw, attack_raw, drift_raw = shape
    brightness = _check_band(
        max(MIN_NORMALIZED_LEVEL, min(MAX_NORMALIZED_LEVEL, brightness_raw * intensity)),
        _LEVEL_BAND,
        "emotion brightness",
        EMOTION_OUT_OF_RANGE,
    )
    tremolo_depth = _check_band(
        max(-1.0, min(1.0, tremolo_raw * intensity)),
        (-1.0, 1.0),
        "emotion tremolo depth",
        EMOTION_OUT_OF_RANGE,
    )
    attack_smoothness = _check_band(
        max(MIN_NORMALIZED_LEVEL, min(MAX_NORMALIZED_LEVEL, attack_raw * (0.5 + 0.5 * intensity))),
        _LEVEL_BAND,
        "emotion attack smoothness",
        EMOTION_OUT_OF_RANGE,
    )
    pitch_drift_cents = _check_band(
        max(-100.0, min(100.0, drift_raw * intensity)),
        (-100.0, 100.0),
        "emotion pitch drift",
        EMOTION_OUT_OF_RANGE,
    )
    return EmotionDirection(
        label=emotion.label,
        intensity=intensity,
        brightness=brightness,
        tremolo_depth=tremolo_depth,
        attack_smoothness=attack_smoothness,
        pitch_drift_cents=pitch_drift_cents,
    )


def known_emotion_labels() -> tuple[str, ...]:
    """Return the closed set of emotion labels with a known shape."""

    return tuple(sorted(_EMOTION_SHAPES))
