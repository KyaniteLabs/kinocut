"""Roster tests for the S5 voice leaf.

Covers W1.1 (15+ distinct voices) and W1.4 (per-character prosody base):
the base roster has 15+ slots, every slot has a stable bounded id, every
slot's parametric base is inside the design envelope, unknown ids fail
closed, and a hostile mapping (prose, duplicate, over-ceiling, lying
slot_id) is rejected with bounded errors.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.voice import (
    MAX_ROSTER_SLOTS,
    MIN_ROSTER_SLOTS,
    ROSTER_INVALID,
    ROSTER_UNKNOWN,
    VoiceError,
    VoiceRoster,
    VoiceSlot,
    VoiceSlotBase,
    default_roster,
)
from kinocut_sound.voice.roster import _BASE_ROSTER


def test_base_roster_has_at_least_fifteen_distinct_slots():
    roster = default_roster()
    assert roster.count >= MIN_ROSTER_SLOTS
    ids = roster.slot_ids
    assert len(ids) == roster.count
    assert len(set(ids)) == len(ids)


def test_base_roster_slots_have_stable_bounded_ids_and_distinct_bases():
    seen_bases: set[tuple[float, float, float, float]] = set()
    for slot in _BASE_ROSTER:
        # Bounded id, no prose/path/URL leakage.
        assert isinstance(slot.slot_id, str)
        assert slot.slot_id == slot.slot_id.lower()
        assert " " not in slot.slot_id
        assert "/" not in slot.slot_id and "\\" not in slot.slot_id
        # Bounded display label.
        assert slot.display_label == slot.slot_id
        # Description hash is bounded sha256.
        assert slot.description_hash.startswith("sha256:")
        assert len(slot.description_hash) == 71
        base_key = (
            round(slot.base.pitch_semitones, 6),
            round(slot.base.rate, 6),
            round(slot.base.volume_db, 6),
            round(slot.base.formant_offset, 6),
        )
        # Distinct base shape (no two slots share every base field).
        assert base_key not in seen_bases, f"duplicate base shape on {slot.slot_id}"
        seen_bases.add(base_key)


def test_default_roster_lookup_returns_slot_for_known_id():
    roster = default_roster()
    first_id = roster.slot_ids[0]
    slot = roster.get(first_id)
    assert isinstance(slot, VoiceSlot)
    assert slot.slot_id == first_id


def test_unknown_roster_id_fails_with_bounded_error():
    roster = default_roster()
    with pytest.raises(VoiceError) as exc:
        roster.get("totally_unknown_slot_id")
    assert exc.value.code == ROSTER_UNKNOWN
    assert exc.value.suggested_action["auto_fix"] is False
    remediation = exc.value.suggested_action.get("remediation", "")
    # Remediation is bounded advisory: no paths, URLs, or secrets.
    assert "/home/" not in remediation
    assert "http" not in remediation
    # No private marker or local path in the str representation.
    assert "/home/" not in str(exc.value)


def test_malformed_roster_id_fails_closed():
    roster = default_roster()
    for bad in ("with space", "../escape", "1lead", ""):
        with pytest.raises(VoiceError) as exc:
            roster.get(bad)
        assert exc.value.code == ROSTER_UNKNOWN


def test_contains_returns_bool_for_unknown_id_without_raising():
    roster = default_roster()
    assert roster.contains("hero_tenor") is True
    assert roster.contains("missing_slot") is False
    assert roster.contains("with space") is False


def test_default_roster_digest_is_stable_and_bounded():
    roster = default_roster()
    digest = roster.digest()
    assert digest.startswith("sha256:")
    assert len(digest) == 71
    again = default_roster().digest()
    assert again == digest


def test_custom_roster_rejects_mapping_below_floor():
    one_slot = default_roster().get("hero_tenor")
    with pytest.raises(VoiceError) as exc:
        VoiceRoster({"only_one": one_slot})
    assert exc.value.code == ROSTER_INVALID


def test_custom_roster_rejects_non_mapping_input():
    with pytest.raises(VoiceError) as exc:
        VoiceRoster([("hero_tenor", default_roster().get("hero_tenor"))])  # type: ignore[arg-type]
    assert exc.value.code == ROSTER_INVALID


def test_custom_roster_rejects_lying_slot_id_mapping():
    slot = default_roster().get("hero_tenor")
    with pytest.raises(VoiceError) as exc:
        VoiceRoster({"different_id": slot})
    assert exc.value.code == ROSTER_INVALID


def test_custom_roster_rejects_duplicate_slot_ids_in_input():
    slot = default_roster().get("hero_tenor")
    with pytest.raises(VoiceError) as exc:
        VoiceRoster({"hero_tenor": slot, "hero_tenor_dup": slot})
    assert exc.value.code == ROSTER_INVALID


def test_voice_slot_base_rejects_out_of_envelope_values():
    # The voice slot base is bounded by the design envelope; out-of-envelope
    # values fail at construction.
    with pytest.raises(ValidationError):
        VoiceSlotBase(
            pitch_semitones=99.0,
            rate=1.0,
            volume_db=0.0,
            formant_offset=0.0,
        )
    with pytest.raises(ValidationError):
        VoiceSlotBase(
            pitch_semitones=0.0,
            rate=0.0,
            volume_db=0.0,
            formant_offset=0.0,
        )
    with pytest.raises(ValidationError):
        VoiceSlotBase(
            pitch_semitones=0.0,
            rate=1.0,
            volume_db=99.0,
            formant_offset=0.0,
        )


def test_voice_roster_does_not_leak_local_paths_or_credentials():
    roster = default_roster()
    payload = roster.fingerprint_payload()
    serialized = repr(payload)
    assert "/home/" not in serialized
    assert "password" not in serialized.lower()
    assert "secret" not in serialized.lower()


def test_roster_ceiling_is_bounded_and_at_or_under_design_max():
    # The static ceiling is itself bounded; a future slot addition cannot
    # blow past it without changing the leaf's private constant.
    assert MAX_ROSTER_SLOTS >= MIN_ROSTER_SLOTS
    assert default_roster().count <= MAX_ROSTER_SLOTS
