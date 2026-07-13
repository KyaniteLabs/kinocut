"""Per-location and per-deck preset tests for the S8 world leaf.

Covers required rows:
* location presets differ in declared parameters and reload identically.
* deck textures add tonal layer refs correctly.

Plus hardening: unknown preset ids fail closed; preset refs must be bounded.
"""

from __future__ import annotations

import pytest

from kinocut_sound.world import (
    DeckId,
    DeckTexturePreset,
    LocationId,
    LocationPreset,
    WorldError,
    default_preset_registry,
)


def test_location_presets_differ_in_declared_parameters():
    registry = default_preset_registry()
    common = registry.location(LocationId.COMMON_ROOM.value)
    memory = registry.location(LocationId.MEMORY_CARE.value)
    garden = registry.location(LocationId.GARDEN.value)
    # Differ in bed asset refs, base gain, and ducking presence.
    assert common.bed_asset_refs != memory.bed_asset_refs
    assert common.base_gain_db != memory.base_gain_db
    assert common.ducking is not None or memory.ducking is not None
    # Garden is distinct from both.
    assert garden.bed_asset_refs not in (common.bed_asset_refs, memory.bed_asset_refs)
    # Declared parameter snapshots are distinct.
    assert registry.location_parameters(LocationId.COMMON_ROOM.value) != (
        registry.location_parameters(LocationId.MEMORY_CARE.value)
    )


def test_location_presets_reload_identically():
    registry = default_preset_registry()
    for location_id in registry.location_ids():
        preset = registry.location(location_id)
        reloaded = preset.reload()
        assert preset.model_dump() == reloaded.model_dump()
        # And the registry hands back a re-validated snapshot each time.
        again = registry.location(location_id)
        assert again.model_dump() == preset.model_dump()


def test_unknown_location_preset_fails_closed():
    registry = default_preset_registry()
    with pytest.raises(WorldError) as exc:
        registry.location("not_a_real_location")
    assert exc.value.code == "preset_invalid"


def test_deck_textures_add_tonal_layer_refs_correctly():
    registry = default_preset_registry()
    base_layers = ("layer_base_hum",)
    seen_merged: set[tuple[str, ...]] = set()
    for deck_id in registry.deck_ids():
        deck = registry.deck(deck_id)
        merged = deck.merged_layer_refs(base_layers)
        # The base layers are preserved, and every tonal layer is appended.
        assert merged[: len(base_layers)] == base_layers
        for tonal in deck.tonal_layer_refs:
            assert tonal in merged
        # Each deck contributes a distinct tonal set.
        seen_merged.add(merged[1:])
    assert len(seen_merged) == len(registry.deck_ids())


def test_deck_texture_round_trips_and_rejects_duplicates():
    deck = DeckTexturePreset(
        deck_id="custom_deck",
        tonal_layer_refs=("layer_a", "layer_b"),
        character="bright",
    )
    reloaded = deck.reload()
    assert deck.model_dump() == reloaded.model_dump()
    # Duplicate tonal layers are rejected.
    with pytest.raises(Exception):
        DeckTexturePreset(
            deck_id="custom_deck",
            tonal_layer_refs=("layer_a", "layer_a"),
            character="bright",
        )


def test_builtin_preset_catalogue_is_versioned_and_complete():
    registry = default_preset_registry()
    expected_locations = {item.value for item in LocationId}
    expected_decks = {item.value for item in DeckId}
    assert set(registry.location_ids()) == expected_locations
    assert set(registry.deck_ids()) == expected_decks
    # A second registry is independent (no shared mutable state).
    other = default_preset_registry()
    assert other.location_ids() == registry.location_ids()


def test_location_preset_rejects_unbounded_refs():
    with pytest.raises(Exception):
        LocationPreset(
            preset_id="bad",
            bed_asset_refs=("beds/with/slashes",),  # path-shaped
            base_layer_ids=("layer_ok",),
        )
