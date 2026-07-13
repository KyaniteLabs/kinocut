"""RED-first tests for the ``kinocut_sound`` line and profile-ref contracts.

A line binds a character id to a profile ref plus prosody, emotion, spatial
preset, pronunciation overrides, and loudness inheritance. Raw text is never
carried — only its bounded hash and length. Profile refs are bounded codes that
carry version, so a render is reproducible and auditable.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.lines import Emotion, Line, ProfileRef, PronunciationOverride, Prosody


def test_profile_ref_requires_bounded_codes_and_strict_version():
    ProfileRef(profile_id="voice_narrator", version=1)
    for bad in ("with space", "../x", "1lead"):
        with pytest.raises(ValidationError):
            ProfileRef(profile_id=bad, version=1)
    for bad in (0, -1, True, "1", 1.0):
        with pytest.raises(ValidationError):
            ProfileRef(profile_id="voice_narrator", version=bad)


def test_prosody_bounds_rate_pitch_volume_and_emphasis():
    Prosody(rate=1.0, pitch=0.0, volume_db=0.0, emphasis=0.5)
    for field, bad in (("rate", 0.0), ("rate", 5.01), ("pitch", -13.0), ("pitch", 13.0), ("volume_db", 100.0)):
        with pytest.raises(ValidationError):
            Prosody(**{field: bad})
    for bad in (-0.01, 1.01):
        with pytest.raises(ValidationError):
            Prosody(emphasis=bad)


def test_emotion_label_is_bounded_and_intensity_bounded():
    Emotion(label="confessional_dread", intensity=0.7)
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            Emotion(label=bad, intensity=0.5)
    for bad in (-0.01, 1.01):
        with pytest.raises(ValidationError):
            Emotion(label="calm", intensity=bad)


def test_pronunciation_override_rejects_raw_term_prose():
    PronunciationOverride(term_hash="sha256:" + "a" * 64, ipa="kon.fɛ.ʃən.al")
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            PronunciationOverride(term_hash="sha256:" + "a" * 64, ipa=bad)


def test_line_rejects_raw_text_and_requires_hash():
    good_hash = "sha256:" + "0" * 64
    Line(
        line_id="line_001",
        character_id="character_a",
        profile=ProfileRef(profile_id="voice_a", version=1),
        text_hash=good_hash,
        text_length_chars=42,
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        spatial_preset="close_mic_dry",
        pronunciation_overrides=(),
        inherit_loudness=True,
    )
    with pytest.raises(ValidationError):
        Line(
            line_id="line_001",
            character_id="character_a",
            profile=ProfileRef(profile_id="voice_a", version=1),
            text_hash="not-a-hash",
            text_length_chars=42,
            prosody=Prosody(),
            emotion=Emotion(label="neutral", intensity=0.0),
            spatial_preset="close_mic_dry",
            pronunciation_overrides=(),
            inherit_loudness=True,
        )


def test_line_rejects_unbounded_ids_and_unsafe_preset():
    good_hash = "sha256:" + "0" * 64
    base = dict(
        character_id="character_a",
        profile=ProfileRef(profile_id="voice_a", version=1),
        text_hash=good_hash,
        text_length_chars=1,
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        spatial_preset="close_mic_dry",
        pronunciation_overrides=(),
        inherit_loudness=True,
    )
    for bad in ("with space", "../x", "1lead"):
        with pytest.raises(ValidationError):
            Line(line_id=bad, **base)
    for bad in ("with space", "../x", "https://x"):
        with pytest.raises(ValidationError):
            Line(line_id="line_001", spatial_preset=bad, **{k: v for k, v in base.items() if k != "spatial_preset"})
