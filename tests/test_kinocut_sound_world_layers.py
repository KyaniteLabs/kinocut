"""Ambient layer stack tests for the S8 world leaf.

Covers required row:
* layer stack computes mixed gain correctly.

Plus hardening for mute/solo semantics, ducking contract validation, and the
W3.8 contract-side-only ducking declaration (S9 applies the envelope).
"""

from __future__ import annotations

import pytest

from kinocut_sound.world import (
    AmbientLayer,
    DuckingContract,
    LayerStack,
    WorldError,
)


def _layer(
    layer_id: str,
    *,
    gain_db: float = -6.0,
    muted: bool = False,
    soloed: bool = False,
    asset_ref: str = "bed_common",
) -> AmbientLayer:
    return AmbientLayer(
        layer_id=layer_id,
        asset_ref=asset_ref,
        gain_db=gain_db,
        muted=muted,
        soloed=soloed,
    )


def test_layer_stack_computes_mixed_gain_with_independent_layers():
    stack = LayerStack(
        (
            _layer("l_hum", gain_db=-9.0),
            _layer("l_chatter", gain_db=-4.5),
            _layer("l_music", gain_db=-12.0),
        )
    )
    mix = {m.layer_id: m for m in stack.mix()}
    # All unmuted, none soloed: every layer audible at its declared gain.
    assert mix["l_hum"].audible is True
    assert mix["l_chatter"].audible is True
    assert mix["l_music"].audible is True
    assert mix["l_hum"].effective_gain_db == pytest.approx(-9.0)
    assert mix["l_chatter"].effective_gain_db == pytest.approx(-4.5)
    assert mix["l_music"].effective_gain_db == pytest.approx(-12.0)
    # effective_layers returns ordered audible layers.
    assert [layer.layer_id for layer in stack.effective_layers()] == [
        "l_hum",
        "l_chatter",
        "l_music",
    ]


def test_muted_layer_is_silent_but_other_layers_remain_audible():
    stack = LayerStack(
        (
            _layer("l_hum", gain_db=-9.0),
            _layer("l_chatter", gain_db=-4.5, muted=True),
        )
    )
    mix = {m.layer_id: m for m in stack.mix()}
    assert mix["l_hum"].audible is True
    assert mix["l_chatter"].audible is False
    # Effective gain of a muted layer collapses to the silent floor.
    from kinocut_sound.limits import MIN_GAIN_DB

    assert mix["l_chatter"].effective_gain_db == MIN_GAIN_DB
    assert stack.mixed_gain_db("l_hum") == pytest.approx(-9.0)


def test_solo_suppresses_non_soloed_layers():
    stack = LayerStack(
        (
            _layer("l_hum", gain_db=-9.0),
            _layer("l_chatter", gain_db=-4.5, soloed=True),
            _layer("l_music", gain_db=-12.0, soloed=True, muted=True),
        )
    )
    mix = {m.layer_id: m for m in stack.mix()}
    # Soloed-but-muted is still inaudible; non-soloed is suppressed.
    assert mix["l_hum"].audible is False
    assert mix["l_chatter"].audible is True
    assert mix["l_music"].audible is False
    assert stack.has_solo() is True
    assert [layer.layer_id for layer in stack.effective_layers()] == ["l_chatter"]


def test_ducking_contract_is_carried_but_not_applied():
    duck = DuckingContract(
        source_bus_id="bus_dialog",
        target_bus_id="bus_bed",
        attenuation_db=9.0,
        attack_ms=80.0,
        release_ms=350.0,
        recovery_ms=500.0,
    )
    stack = LayerStack((_layer("l_hum"),), ducking=duck)
    # The ducking contract is declared (S9 will apply the envelope).
    assert stack.ducking is not None
    assert stack.ducking.attenuation_db == pytest.approx(9.0)
    assert stack.ducking.source_bus_id == "bus_dialog"
    # A layer with no ducking still mixes normally.
    assert stack.mixed_gain_db("l_hum") == pytest.approx(-6.0)


def test_ducking_contract_rejects_self_sidechain_and_bad_recovery():
    with pytest.raises(Exception):
        DuckingContract(source_bus_id="bus_dialog", target_bus_id="bus_dialog")
    with pytest.raises(Exception):
        DuckingContract(
            source_bus_id="bus_dialog",
            target_bus_id="bus_bed",
            release_ms=400.0,
            recovery_ms=300.0,  # recovery < release
        )


def test_layer_stack_rejects_duplicate_and_unbounded_ids():
    with pytest.raises(WorldError) as exc:
        LayerStack((_layer("l_dup"), _layer("l_dup")))
    assert exc.value.code == "layer_stack_invalid"
    # Unbounded asset_ref is rejected.
    with pytest.raises(Exception):
        AmbientLayer(layer_id="l_x", asset_ref="beds/with/slashes", gain_db=-3.0)


def test_layer_mix_is_deterministic_across_instances():
    layers = (_layer("l_hum", gain_db=-9.0), _layer("l_chatter", gain_db=-4.5))
    a = LayerStack(layers).mix()
    b = LayerStack(layers).mix()
    assert a == b
