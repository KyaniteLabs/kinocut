"""Prosody/emotion normalization tests for the S5 voice leaf.

Covers W1.4 (per-character prosody base composed with line overrides) and
W1.6 (parametric emotion direction): the EffectiveProsody and
EmotionDirection composers respect the design envelope, an out-of-range
input fails closed, and known emotion labels produce distinct bounded
synthesis axes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound import Emotion, Prosody
from kinocut_sound.voice import (
    PROSODY_OUT_OF_RANGE,
    EffectiveProsody,
    EmotionDirection,
    VoiceError,
    known_emotion_labels,
    resolve_emotion,
    resolve_prosody,
)
from kinocut_sound.voice.roster import VoiceSlot, VoiceSlotBase


def _slot(
    *,
    pitch: float = 0.0,
    rate: float = 1.0,
    volume_db: float = 0.0,
    formant: float = 0.0,
) -> VoiceSlot:
    base = VoiceSlotBase(
        pitch_semitones=pitch,
        rate=rate,
        volume_db=volume_db,
        formant_offset=formant,
    )
    return VoiceSlot(
        slot_id="test_slot",
        display_label="test_slot",
        base=base,
        description_hash="sha256:" + "0" * 64,
    )


def test_resolve_prosody_combines_slot_base_with_line_overrides_additively():
    slot = _slot(pitch=-4.0, rate=0.9, volume_db=-2.0, formant=1.5)
    prosody = Prosody(rate=1.0, pitch=2.0, volume_db=1.0, emphasis=0.3)
    effective = resolve_prosody(slot, prosody)
    assert isinstance(effective, EffectiveProsody)
    assert effective.pitch_semitones == pytest.approx(-2.0)
    assert effective.rate == pytest.approx(0.9)
    assert effective.volume_db == pytest.approx(-1.0)
    assert effective.emphasis == pytest.approx(0.3)
    assert effective.formant_offset == pytest.approx(1.5)


def test_resolve_prosody_fails_closed_for_out_of_range_composed_values():
    # Prosody itself accepts pitch=1.0; combined with a slot base pitch of
    # 11.5 the composed value (12.5) crosses the 12-semitone ceiling and
    # must be caught at resolve_prosody.
    slot_over = _slot(pitch=11.5)
    prosody_over = Prosody(pitch=1.0)
    with pytest.raises(VoiceError) as exc:
        resolve_prosody(slot_over, prosody_over)
    assert exc.value.code == PROSODY_OUT_OF_RANGE


def test_resolve_prosody_rejects_non_slot_or_non_prosody_inputs():
    slot = _slot()
    with pytest.raises(VoiceError):
        resolve_prosody(slot, "not_prosody")  # type: ignore[arg-type]
    with pytest.raises(VoiceError):
        resolve_prosody("not_slot", Prosody())  # type: ignore[arg-type]


def test_prosody_contract_rejects_out_of_envelope_values():
    # The shared Prosody contract already enforces the design envelope; the
    # voice leaf composes within it. Out-of-envelope prosody fails at the
    # contract, before resolve_prosody is reached.
    with pytest.raises(ValidationError):
        Prosody(rate=4.0)  # above MAX_PROSODY_RATE (2.0)
    with pytest.raises(ValidationError):
        Prosody(pitch=15.0)  # at/above MAX_PROSODY_PITCH_SEMITONES (12.0)


def test_resolve_emotion_returns_known_label_shape_scaled_by_intensity():
    low = resolve_emotion(Emotion(label="joy", intensity=0.2))
    high = resolve_emotion(Emotion(label="joy", intensity=1.0))
    assert isinstance(low, EmotionDirection) and isinstance(high, EmotionDirection)
    # Brightness scales with intensity for joy (shape brightness > 0).
    assert high.brightness > low.brightness
    # Pitch drift sign and magnitude track the joy shape (positive).
    assert high.pitch_drift_cents > 0
    assert high.pitch_drift_cents > low.pitch_drift_cents


def test_resolve_emotion_normalizes_unknown_label_to_neutral():
    direction = resolve_emotion(Emotion(label="extrapolated_future_label", intensity=0.5))
    assert direction.brightness == pytest.approx(0.25 * 0.5)
    assert direction.pitch_drift_cents == pytest.approx(0.0)


def test_known_emotion_labels_form_a_bounded_closed_table():
    labels = known_emotion_labels()
    assert "neutral" in labels
    assert "joy" in labels
    assert "calm" in labels
    # Every label is a bounded code (no spaces, no path markers).
    for label in labels:
        assert " " not in label
        assert "/" not in label


def test_resolve_emotion_rejects_non_emotion_input():
    with pytest.raises(VoiceError):
        resolve_emotion("not_emotion")  # type: ignore[arg-type]


def test_emotion_intensity_out_of_range_fails_at_contract():
    with pytest.raises(ValidationError):
        Emotion(label="joy", intensity=1.5)
    with pytest.raises(ValidationError):
        Emotion(label="joy", intensity=-0.1)
