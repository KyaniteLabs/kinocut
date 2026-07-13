"""Static base-voice roster — 15+ distinct, bounded voice slots.

A ``VoiceSlot`` is a stable, code-owned voice identity: a bounded id plus the
parametric base (pitch, rate, volume, formant offset) that the local TTS
adapter composes with a Line's per-call prosody/emotion overrides. Slot ids
are stable public identifiers — a serialized plan, receipt, or fingerprint
refers to voices by slot id only, never by a host path, model name, or
speaker identity. Raw descriptions are represented by their bounded SHA-256
hash so prose, PII, or model provenance cannot ride in on a slot.

The roster is a sealed, code-owned map: project configuration may *select* an
identifier already compiled into the map but can never supply an import path,
model name, or arbitrary string. An unlisted or malformed identifier yields
:class:`VoiceError(code=ROSTER_UNKNOWN)` rather than a silent fallback to a
different voice.

Design references (sonic-world design):
* M1 — Voice Generation: 15+ distinct voices (W1.1), per-character prosody
  base (W1.4).
* Capability & Adapter Registry — static code-owned constructor map.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import islice
from types import MappingProxyType

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256, canonical_digest
from kinocut_sound._errors import contract_error
from kinocut_sound.validation import CODE_RE

from kinocut_sound.voice._errors import (
    ROSTER_EXCEEDS_CEILING,
    ROSTER_INVALID,
    ROSTER_UNKNOWN,
    bounded_voice_error,
    voice_error,
)

# --- Voice-leaf private ceilings ---
# TODO(controller): consider promoting these to ``kinocut_sound/limits.py`` if
# S6/S10/S14 need to share the same roster ceilings.
MAX_ROSTER_SLOTS: int = 64
MIN_ROSTER_SLOTS: int = 15
MIN_BASE_PITCH_SEMITONES: float = -24.0
MAX_BASE_PITCH_SEMITONES: float = 24.0
MIN_BASE_RATE: float = 0.5
MAX_BASE_RATE: float = 2.0
MIN_BASE_VOLUME_DB: float = -24.0
MAX_BASE_VOLUME_DB: float = 12.0
MIN_FORMANT_OFFSET: float = -12.0
MAX_FORMANT_OFFSET: float = 12.0


class VoiceSlotBase(FrozenModel):
    """The parametric base of a voice slot.

    ``pitch`` is a semitone offset around the adapter's reference pitch
    (A3 = 220 Hz for the local adapter). ``rate`` is a multiplier around 1.0.
    ``volume_db`` is a dB offset around 0. ``formant_offset`` shifts the
    spectral envelope (a simple timbre axis) in arbitrary slot units. Every
    field is bounded so a configuration error cannot produce an unreasonable
    render or overflow the synthesis expression.
    """

    pitch_semitones: float = Field(ge=MIN_BASE_PITCH_SEMITONES, le=MAX_BASE_PITCH_SEMITONES)
    rate: float = Field(gt=MIN_BASE_RATE, le=MAX_BASE_RATE)
    volume_db: float = Field(ge=MIN_BASE_VOLUME_DB, le=MAX_BASE_VOLUME_DB)
    formant_offset: float = Field(ge=MIN_FORMANT_OFFSET, le=MAX_FORMANT_OFFSET)

    @field_validator("pitch_semitones", "rate", "volume_db", "formant_offset")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("voice base parameter must not be a boolean")
        return value


@dataclass(frozen=True)
class VoiceSlot:
    """One stable, code-owned voice identity.

    ``slot_id`` is a bounded code: it is the only identifier a plan, receipt,
    or fingerprint carries. ``display_label`` is a short bounded code used in
    advisory logs only — it is never serialized into a receipt. ``base`` is
    the parametric shape the adapter composes with per-line overrides.
    ``description_hash`` is the bounded SHA-256 of the human-readable slot
    description: prose never rides in on a slot.
    """

    slot_id: str
    display_label: str
    base: VoiceSlotBase
    description_hash: Sha256


def _validate_slot(slot: VoiceSlot) -> VoiceSlot:
    if not isinstance(slot, VoiceSlot):
        raise voice_error("voice slot must be a VoiceSlot instance", ROSTER_INVALID)
    try:
        BoundedCode(slot.slot_id)
    except ValueError as exc:
        raise voice_error(
            "voice slot id must be a bounded code",
            ROSTER_INVALID,
        ) from exc
    if not CODE_RE.match(slot.display_label):
        raise voice_error(
            "voice slot display label must be a bounded code",
            ROSTER_INVALID,
        ) from None
    if not isinstance(slot.base, VoiceSlotBase):
        raise voice_error(
            "voice slot base must be a VoiceSlotBase instance",
            ROSTER_INVALID,
        ) from None
    # Re-validate the base so a model_construct bypass is caught here.
    VoiceSlotBase.model_validate(slot.base.model_dump(mode="python"))
    return slot


def _slot(
    slot_id: str,
    display_label: str,
    *,
    pitch_semitones: float,
    rate: float,
    volume_db: float,
    formant_offset: float,
    description: str,
) -> VoiceSlot:
    """Build a code-owned :class:`VoiceSlot` from a private description string.

    The description is hashed immediately and never retained on the slot, so a
    prose description can be useful at construction time without becoming
    serialized, logged, or leaked.
    """

    base = VoiceSlotBase(
        pitch_semitones=pitch_semitones,
        rate=rate,
        volume_db=volume_db,
        formant_offset=formant_offset,
    )
    digest = canonical_digest({"description": description, "base": base.model_dump(mode="json")})
    slot = VoiceSlot(
        slot_id=slot_id,
        display_label=display_label,
        base=base,
        description_hash=digest,
    )
    return _validate_slot(slot)


# --- Code-owned base roster (15+ distinct slots) ---
# Each slot pairs a stable bounded id with a distinct parametric base. The
# ids are the only public identifier; descriptions are hashed immediately.
_BASE_ROSTER: tuple[VoiceSlot, ...] = (
    _slot(
        "narrator_male_deep",
        "narrator_male_deep",
        pitch_semitones=-8.0,
        rate=0.92,
        volume_db=0.0,
        formant_offset=-2.0,
        description="Deep male narrator voice, measured pace.",
    ),
    _slot(
        "narrator_male_warm",
        "narrator_male_warm",
        pitch_semitones=-4.0,
        rate=0.96,
        volume_db=0.0,
        formant_offset=-1.0,
        description="Warm male narrator voice, neutral pace.",
    ),
    _slot(
        "narrator_female_warm",
        "narrator_female_warm",
        pitch_semitones=5.0,
        rate=0.98,
        volume_db=0.0,
        formant_offset=1.5,
        description="Warm female narrator voice, neutral pace.",
    ),
    _slot(
        "narrator_female_bright",
        "narrator_female_bright",
        pitch_semitones=8.0,
        rate=1.04,
        volume_db=0.5,
        formant_offset=2.5,
        description="Bright female narrator voice, slightly quicker.",
    ),
    _slot(
        "hero_tenor",
        "hero_tenor",
        pitch_semitones=2.0,
        rate=1.05,
        volume_db=1.0,
        formant_offset=0.5,
        description="Bright tenor hero voice, energetic pace.",
    ),
    _slot(
        "heroine_soprano",
        "heroine_soprano",
        pitch_semitones=7.0,
        rate=1.02,
        volume_db=0.5,
        formant_offset=2.0,
        description="Soprano heroine voice, confident pace.",
    ),
    _slot(
        "elder_bass",
        "elder_bass",
        pitch_semitones=-12.0,
        rate=0.85,
        volume_db=-1.0,
        formant_offset=-3.0,
        description="Deep bass elder voice, slow and deliberate.",
    ),
    _slot(
        "child_treble",
        "child_treble",
        pitch_semitones=12.0,
        rate=1.15,
        volume_db=0.0,
        formant_offset=3.5,
        description="Treble child voice, quick and bright.",
    ),
    _slot(
        "villain_baritone",
        "villain_baritone",
        pitch_semitones=-6.0,
        rate=0.88,
        volume_db=-0.5,
        formant_offset=-1.5,
        description="Dark baritone villain voice, measured pace.",
    ),
    _slot(
        "sidekick_tenor",
        "sidekick_tenor",
        pitch_semitones=3.0,
        rate=1.10,
        volume_db=0.0,
        formant_offset=0.0,
        description="Light tenor sidekick voice, lively pace.",
    ),
    _slot(
        "mentor_bass_baritone",
        "mentor_bass_baritone",
        pitch_semitones=-5.0,
        rate=0.90,
        volume_db=0.0,
        formant_offset=-1.0,
        description="Bass-baritone mentor voice, steady pace.",
    ),
    _slot(
        "android_neutral",
        "android_neutral",
        pitch_semitones=0.0,
        rate=1.00,
        volume_db=-1.5,
        formant_offset=0.0,
        description="Neutral android voice, flat and even.",
    ),
    _slot(
        "creature_guttural",
        "creature_guttural",
        pitch_semitones=-10.0,
        rate=0.82,
        volume_db=-1.0,
        formant_offset=-4.0,
        description="Guttural creature voice, slow and rough.",
    ),
    _slot(
        "spirit_ethereal",
        "spirit_ethereal",
        pitch_semitones=9.0,
        rate=0.94,
        volume_db=-2.0,
        formant_offset=4.0,
        description="Ethereal spirit voice, airy and slow.",
    ),
    _slot(
        "royal_mezzo",
        "royal_mezzo",
        pitch_semitones=4.0,
        rate=0.93,
        volume_db=1.0,
        formant_offset=1.0,
        description="Mezzo royal voice, poised and unhurried.",
    ),
    _slot(
        "cabbie_gravel",
        "cabbie_gravel",
        pitch_semitones=-3.0,
        rate=1.08,
        volume_db=-1.0,
        formant_offset=-2.5,
        description="Gravelly cabbie voice, quick and clipped.",
    ),
    _slot(
        "newscaster_mid",
        "newscaster_mid",
        pitch_semitones=1.0,
        rate=1.00,
        volume_db=0.0,
        formant_offset=0.0,
        description="Neutral newscaster voice, even and clear.",
    ),
)


class VoiceRoster:
    """Sealed, code-owned voice roster with bounded lookup.

    The default roster is the S5 base roster of 15+ slots. A caller may pass a
    private mapping at construction to extend or shrink the roster (e.g. for
    tests), but the mapping is copied into a sealed ``MappingProxyType`` so a
    later mutation cannot silently change which slots resolve. Lookup is
    fail-closed: an unknown id raises :class:`VoiceError(code=ROSTER_UNKNOWN)`.
    """

    __slots__ = ("_slots",)

    def __init__(self, slots: Mapping[str, VoiceSlot] | None = None) -> None:
        if slots is None:
            source: Mapping[str, VoiceSlot] = {slot.slot_id: slot for slot in _BASE_ROSTER}
        else:
            if not isinstance(slots, Mapping):
                raise voice_error(
                    "voice roster must be built from a mapping",
                    ROSTER_INVALID,
                )
            try:
                bounded = tuple(islice(slots.items(), MAX_ROSTER_SLOTS + 1))
            except Exception as exc:
                raise voice_error(
                    "voice roster source is not iterable",
                    ROSTER_INVALID,
                ) from exc
            if len(bounded) > MAX_ROSTER_SLOTS:
                raise bounded_voice_error(
                    "voice roster exceeds its ceiling",
                    ROSTER_EXCEEDS_CEILING,
                )
            if len(bounded) < MIN_ROSTER_SLOTS:
                raise bounded_voice_error(
                    "voice roster must declare at least 15 slots",
                    ROSTER_INVALID,
                )
            source = {}
            for raw_id, slot in bounded:
                checked_slot = _validate_slot(slot)
                if checked_slot.slot_id != raw_id:
                    raise voice_error(
                        "voice roster key must match slot id",
                        ROSTER_INVALID,
                    ) from None
                if checked_slot.slot_id in source:
                    raise voice_error(
                        "voice roster slot ids must be unique",
                        ROSTER_INVALID,
                    ) from None
                source[checked_slot.slot_id] = checked_slot
        self._slots: Mapping[str, VoiceSlot] = MappingProxyType(source)

    @property
    def slot_ids(self) -> tuple[str, ...]:
        """Return the sorted sealed slot identifiers."""

        return tuple(sorted(self._slots))

    @property
    def count(self) -> int:
        """Return the number of slots compiled into this roster."""

        return len(self._slots)

    def contains(self, slot_id: str) -> bool:
        """Return whether ``slot_id`` is compiled into this roster."""

        try:
            BoundedCode(slot_id)
        except (TypeError, ValueError):
            return False
        return slot_id in self._slots

    def get(self, slot_id: str) -> VoiceSlot:
        """Return the slot for ``slot_id``; raise on unknown or malformed id."""

        try:
            BoundedCode(slot_id)
        except (TypeError, ValueError) as exc:
            raise voice_error(
                "voice slot id must be a bounded code",
                ROSTER_UNKNOWN,
            ) from exc
        slot = self._slots.get(slot_id)
        if slot is None:
            raise bounded_voice_error(
                "voice slot id is not compiled into the roster",
                ROSTER_UNKNOWN,
            )
        return slot

    def require(self, slot_id: str) -> VoiceSlot:
        """Alias for :meth:`get` — explicit demand semantics for callers."""

        return self.get(slot_id)

    def describe_hash(self, slot_id: str) -> Sha256:
        """Return the bounded description hash for ``slot_id``."""

        return self.get(slot_id).description_hash

    def fingerprint_payload(self) -> dict[str, object]:
        """Return a canonical, sorted JSON payload identifying this roster."""

        return {
            "kind": "voice_roster",
            "slot_ids": list(self.slot_ids),
            "slots": [
                {
                    "slot_id": slot.slot_id,
                    "base": slot.base.model_dump(mode="json"),
                    "description_hash": slot.description_hash,
                }
                for slot in (self._slots[sid] for sid in self.slot_ids)
            ],
        }

    def digest(self) -> Sha256:
        """Return ``sha256:<hex>`` over the canonical roster payload."""

        return canonical_digest(self.fingerprint_payload())


def default_roster() -> VoiceRoster:
    """Return the code-owned base :class:`VoiceRoster` (15+ distinct slots)."""

    return VoiceRoster()


def _roster_invariant(roster: VoiceRoster) -> None:
    if roster.count < MIN_ROSTER_SLOTS:
        raise contract_error(
            "voice roster must declare at least 15 slots",
            "invalid_record",
        )
    ids = roster.slot_ids
    if len(set(ids)) != len(ids):
        raise contract_error(
            "voice roster slot ids must be unique",
            "invalid_record",
        )


# Module-import invariant — fails the import loudly if the static roster is
# ever mis-edited below the design's 15-slot floor.
_ROSTER_INVARIANT = default_roster()
_roster_invariant(_ROSTER_INVARIANT)
