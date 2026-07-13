"""Per-location ambient presets and per-deck sonic texture presets.

W4.5: per-location ambient presets (common-room, memory-care, etc.). W4.6:
per-deck sonic texture adds its declared tonal layer to a bed. A preset is a
pure declarative record: it names bed asset refs, base layer ids, declared
numeric parameters (gain, loop crossfade), and an optional ducking contract.
The S9 mix leaf interprets these; S8 only carries the declared shape.

Presets are deterministic: a preset serializes and reloads identically, and
the built-in catalogue of named presets is versioned inside this module so a
caller cannot inject an unregistered preset id.

Design references (sonic-world design):
* W4.5 / W4.6 — per-location and per-deck presets.
* W7.9 — preset system (beds among the four preset kinds).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel
from kinocut_sound.defaults import DEFAULT_BUS_GAIN_DB
from kinocut_sound.limits import MAX_GAIN_DB, MIN_GAIN_DB, MIN_TIME_SECONDS
from kinocut_sound.world._errors import world_error
from kinocut_sound.world.layers import DuckingContract
from kinocut_sound.world.loop import SeamlessLoop

_MAX_PRESET_LAYERS = 32
_MAX_DECK_TEXTURE_LAYERS = 16


class LocationId(StrEnum):
    """Closed set of built-in per-location ambient preset ids."""

    COMMON_ROOM = "common_room"
    MEMORY_CARE = "memory_care"
    GARDEN = "garden"
    CORRIDOR = "corridor"
    DINING_HALL = "dining_hall"


class DeckId(StrEnum):
    """Closed set of built-in per-deck texture preset ids."""

    UPPER_DECK = "upper_deck"
    LOWER_DECK = "lower_deck"
    PROMENADE = "promenade"
    BRIDGE = "bridge"


class LocationPreset(FrozenModel):
    """One per-location ambient preset: beds, layers, gain, loop, ducking."""

    preset_id: str = Field(min_length=1)
    bed_asset_refs: tuple[str, ...] = Field(min_length=1)
    base_layer_ids: tuple[str, ...] = ()
    base_gain_db: float = Field(default=DEFAULT_BUS_GAIN_DB, ge=MIN_GAIN_DB, le=MAX_GAIN_DB)
    loop_plan: SeamlessLoop | None = None
    ducking: DuckingContract | None = None
    description_hash: str | None = None

    @field_validator("preset_id")
    @classmethod
    def _preset_id_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("bed_asset_refs", "base_layer_ids")
    @classmethod
    def _ref_lists_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAX_PRESET_LAYERS:
            raise ValueError("preset ref list exceeds ceiling")
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("preset refs must be unique")
        return value

    @field_validator("base_gain_db")
    @classmethod
    def _gain_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("base_gain_db must not be a boolean")
        return value

    def reload(self) -> LocationPreset:
        """Return a re-validated copy (round-trip identity check)."""

        return LocationPreset.model_validate(self.model_dump(mode="python"))


class DeckTexturePreset(FrozenModel):
    """One per-deck sonic texture: tonal layer refs and a character code."""

    deck_id: str = Field(min_length=1)
    tonal_layer_refs: tuple[str, ...] = Field(min_length=1)
    character: str = Field(min_length=1)
    added_gain_db: float = Field(default=DEFAULT_BUS_GAIN_DB, ge=MIN_GAIN_DB, le=MAX_GAIN_DB)

    @field_validator("deck_id", "character")
    @classmethod
    def _ids_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("tonal_layer_refs")
    @classmethod
    def _layers_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAX_DECK_TEXTURE_LAYERS:
            raise ValueError("deck texture layer count exceeds ceiling")
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("deck tonal layer refs must be unique")
        return value

    @field_validator("added_gain_db")
    @classmethod
    def _gain_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("added_gain_db must not be a boolean")
        return value

    def reload(self) -> DeckTexturePreset:
        """Return a re-validated copy (round-trip identity check)."""

        return DeckTexturePreset.model_validate(self.model_dump(mode="python"))

    def merged_layer_refs(self, base_layer_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Return base layers followed by this deck's tonal layers (de-duped)."""

        merged: list[str] = list(base_layer_ids)
        for code in self.tonal_layer_refs:
            if code not in merged:
                merged.append(code)
        return tuple(merged)


def _loop(label: str, source: float, target: float, crossfade: float) -> SeamlessLoop:
    return SeamlessLoop(
        loop_label=label,
        source_duration_seconds=source,
        target_duration_seconds=target,
        crossfade_seconds=crossfade,
    )


def _builtin_location_presets() -> dict[str, LocationPreset]:
    """Return the versioned built-in per-location ambient preset catalogue."""

    crossfade = max(MIN_TIME_SECONDS + 0.001, 0.5)
    presets: list[LocationPreset] = [
        LocationPreset(
            preset_id=LocationId.COMMON_ROOM.value,
            bed_asset_refs=("bed_common_room",),
            base_layer_ids=("layer_common_room_hum", "layer_common_room_chatter"),
            base_gain_db=-6.0,
            loop_plan=_loop("common_room_loop", 120.0, 900.0, crossfade),
            ducking=DuckingContract(
                source_bus_id="bus_dialog",
                target_bus_id="bus_bed_common_room",
            ),
        ),
        LocationPreset(
            preset_id=LocationId.MEMORY_CARE.value,
            bed_asset_refs=("bed_memory_care",),
            base_layer_ids=("layer_memory_care_calm",),
            base_gain_db=-9.0,
            loop_plan=_loop("memory_care_loop", 180.0, 900.0, crossfade),
            ducking=DuckingContract(
                source_bus_id="bus_dialog",
                target_bus_id="bus_bed_memory_care",
                attenuation_db=12.0,
            ),
        ),
        LocationPreset(
            preset_id=LocationId.GARDEN.value,
            bed_asset_refs=("bed_garden",),
            base_layer_ids=("layer_garden_birds", "layer_garden_wind"),
            base_gain_db=-7.5,
            loop_plan=_loop("garden_loop", 240.0, 900.0, crossfade),
        ),
        LocationPreset(
            preset_id=LocationId.CORRIDOR.value,
            bed_asset_refs=("bed_corridor",),
            base_layer_ids=("layer_corridor_hvac",),
            base_gain_db=-12.0,
            loop_plan=_loop("corridor_loop", 90.0, 900.0, crossfade),
        ),
        LocationPreset(
            preset_id=LocationId.DINING_HALL.value,
            bed_asset_refs=("bed_dining_hall",),
            base_layer_ids=("layer_dining_clatter", "layer_dining_murmur"),
            base_gain_db=-5.0,
            loop_plan=_loop("dining_hall_loop", 150.0, 900.0, crossfade),
            ducking=DuckingContract(
                source_bus_id="bus_dialog",
                target_bus_id="bus_bed_dining_hall",
                attenuation_db=15.0,
            ),
        ),
    ]
    return {preset.preset_id: preset for preset in presets}


def _builtin_deck_presets() -> dict[str, DeckTexturePreset]:
    """Return the versioned built-in per-deck sonic-texture catalogue."""

    decks: list[DeckTexturePreset] = [
        DeckTexturePreset(
            deck_id=DeckId.UPPER_DECK.value,
            tonal_layer_refs=("layer_deck_upper_air",),
            character="bright",
            added_gain_db=-3.0,
        ),
        DeckTexturePreset(
            deck_id=DeckId.LOWER_DECK.value,
            tonal_layer_refs=("layer_deck_lower_rumble",),
            character="dark",
            added_gain_db=-4.5,
        ),
        DeckTexturePreset(
            deck_id=DeckId.PROMENADE.value,
            tonal_layer_refs=("layer_promenade_open", "layer_promenade_wind"),
            character="open",
            added_gain_db=-2.0,
        ),
        DeckTexturePreset(
            deck_id=DeckId.BRIDGE.value,
            tonal_layer_refs=("layer_bridge_hum",),
            character="neutral",
            added_gain_db=-3.5,
        ),
    ]
    return {deck.deck_id: deck for deck in decks}


_LOCATION_PRESETS = _builtin_location_presets()
_DECK_PRESETS = _builtin_deck_presets()


class PresetRegistry:
    """Sealed lookup of built-in location and deck presets by stable id."""

    __slots__ = ("_decks", "_locations")

    def __init__(self) -> None:
        # Copy into per-instance dicts so a caller cannot mutate the module
        # level frozen catalogue through the registry handle.
        self._locations = dict(_LOCATION_PRESETS)
        self._decks = dict(_DECK_PRESETS)

    def location_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._locations))

    def deck_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._decks))

    def location(self, preset_id: str) -> LocationPreset:
        checked = BoundedCode(preset_id)
        preset = self._locations.get(checked)
        if preset is None:
            raise world_error("location preset is not registered", "preset_invalid")
        return preset.reload()

    def deck(self, deck_id: str) -> DeckTexturePreset:
        checked = BoundedCode(deck_id)
        preset = self._decks.get(checked)
        if preset is None:
            raise world_error("deck texture preset is not registered", "preset_invalid")
        return preset.reload()

    def location_parameters(self, preset_id: str) -> dict[str, object]:
        """Return the declared parameters that distinguish one location."""

        preset = self.location(preset_id)
        return {
            "preset_id": preset.preset_id,
            "base_gain_db": preset.base_gain_db,
            "bed_asset_refs": preset.bed_asset_refs,
            "base_layer_ids": preset.base_layer_ids,
            "has_ducking": preset.ducking is not None,
            "loop_label": preset.loop_plan.loop_label if preset.loop_plan else None,
        }


def default_preset_registry() -> PresetRegistry:
    """Return a fresh :class:`PresetRegistry` (per-call to avoid shared state)."""

    return PresetRegistry()
