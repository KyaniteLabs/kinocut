"""Exact linked-envelope oracles, including recovery and interrupted ramps."""

from array import array

import pytest

from kinocut_sound.world.layers import DuckingContract


def contract(**overrides):
    values = dict(
        source_bus_id="dialogue",
        target_bus_id="ambience",
        attenuation_db=6.020599913279624,
        attack_ms=2,
        release_ms=2,
        recovery_ms=2,
    )
    return DuckingContract(**(values | overrides))


def test_exact_attack_release_and_equal_recovery_deadline():
    from kinocut_sound.mix.layer_ducking import duck_layer_in_place

    samples = array("h", [10000] * 5)
    summary = duck_layer_in_place(samples, array("h", [10000, 10000, 0, 0, 0]), 1, 1000, contract())
    assert list(samples) == [7500, 5000, 7500, 10000, 10000]
    assert summary["active_frames"] == 2 and summary["activity_runs"] == 1
    assert summary["minimum_gain"] == 0.5 and summary["final_gain"] == 1.0
    assert summary["completed_releases"] == 1 and summary["max_release_frames"] == 2
    assert summary["recovery_status"] == "pass"
    assert summary["truncated_release_frames"] == 0


def test_interrupted_ramp_restarts_from_current_gain():
    from kinocut_sound.mix.layer_ducking import duck_layer_in_place

    samples = array("h", [16000] * 5)
    summary = duck_layer_in_place(samples, array("h", [10000, 0, 10000, 0, 0]), 1, 1000, contract())
    assert list(samples) == [12000, 14000, 11000, 13500, 16000]
    assert summary["activity_runs"] == 2 and summary["completed_releases"] == 1


def test_stereo_detector_is_linked_and_one_frame_ramps_finish():
    from kinocut_sound.mix.layer_ducking import duck_layer_in_place

    samples = array("h", [10000, -20000, 10000, -20000])
    summary = duck_layer_in_place(
        samples, array("h", [0, 10000, 0, 0]), 2, 1000, contract(attack_ms=1, release_ms=1, recovery_ms=1)
    )
    assert list(samples) == [5000, -10000, 10000, -20000]
    assert summary["max_release_frames"] == 1


@pytest.mark.parametrize(
    "detector,active,truncated,final",
    [
        ([0, 0, 0], 0, 0, 1.0),
        ([10000, 10000, 10000], 3, 0, 0.5),
        ([10000, 10000, 0], 2, 1, 0.75),
    ],
)
def test_unexercised_or_truncated_recovery_is_not_a_pass(detector, active, truncated, final):
    from kinocut_sound.mix.layer_ducking import duck_layer_in_place

    samples = array("h", [10000] * len(detector))
    summary = duck_layer_in_place(samples, array("h", detector), 1, 1000, contract())
    assert summary["active_frames"] == active
    assert summary["truncated_release_frames"] == truncated
    assert summary["final_gain"] == final
    assert summary["recovery_status"] == "not_exercised"


def test_detector_threshold_is_strict_and_uses_actual_pcm_boundary(monkeypatch):
    from kinocut_sound.mix import layer_ducking

    samples = array("h", [10000, 10000])
    layer_ducking.duck_layer_in_place(samples, array("h", [655, 656]), 1, 1000, contract())
    assert list(samples) == [10000, 7500]
    monkeypatch.setattr(layer_ducking, "DEFAULT_MIX_DUCK_THRESHOLD", 1 / 32)
    samples = array("h", [10000] * 3)
    layer_ducking.duck_layer_in_place(samples, array("h", [1023, 1024, 1025]), 1, 1000, contract())
    assert list(samples) == [10000, 10000, 7500]


def test_fractional_timing_rounds_up_and_recovers_at_exact_endpoint():
    from kinocut_sound.mix.layer_ducking import duck_layer_in_place, ducking_parameters

    policy = contract(attack_ms=0.1, release_ms=0.1, recovery_ms=0.1)
    parameters = ducking_parameters(policy, 22050)
    assert parameters["attack_frames"] == parameters["release_frames"] == parameters["recovery_frames"] == 3
    samples = array("h", [12000] * 6)
    summary = duck_layer_in_place(samples, array("h", [10000] * 3 + [0] * 3), 1, 22050, policy)
    assert list(samples) == [10000, 8000, 6000, 8000, 10000, 12000]
    assert summary["max_release_frames"] == 3 and summary["final_gain"] == 1


def test_core_does_not_silently_drop_ducking_without_layers():
    from kinocut_sound.mix.layers import apply_layers
    from kinocut_sound.mix._errors import MixError

    with pytest.raises(MixError):
        apply_layers({"ambience": array("h", [0])}, (), 1000, 1, contract())


@pytest.mark.parametrize("invalid", [False, {}, {"source_bus_id": "dialogue"}])
def test_core_invalid_ducking_uses_typed_error(invalid):
    from kinocut_sound.mix.layers import apply_layers, MixLayer
    from kinocut_sound.mix._errors import MixError
    from kinocut_sound.mix._wav import pcm_to_wav
    from kinocut_sound.world.layers import AmbientLayer

    layer = MixLayer(
        AmbientLayer(layer_id="x", asset_ref="x"), pcm_to_wav(array("h", [1000]), sample_rate_hz=1000), "pad", None
    )
    with pytest.raises(MixError):
        apply_layers({"ambience": array("h", [0]), "dialogue": array("h", [1000])}, (layer,), 1000, 1, invalid)
