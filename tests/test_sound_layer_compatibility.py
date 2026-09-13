"""Pre-V3 measured archive/hash controls and unchanged world contracts."""

import pytest

from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo


@pytest.mark.parametrize(
    "version,stereo,request_hash,archive_hash",
    [
        (
            1,
            False,
            "2d374968efa06411fd9b993ebd47da07c0475fcd867d308d2db6ae84b662c536",
            "47ccb879a5bbda14a80c356503940aba73e6d1285a02af93e69b6095a83790c4",
        ),
        (
            1,
            True,
            "1b0d75473380e277e3ea6747567ae66092d160e6d8ed26146410956bc4abb1c9",
            "b24201cd5409c60c0f3b3c5c03132173b8bfc5c4a8790525c3de5e66cf821807",
        ),
        (
            2,
            False,
            "a77991f182689aecdffa217368b267b2a8ece6934ebb2c5ce862a587b6ad7ad0",
            "e37b548719473be168fb4545d678e5d9bfd88211edf541fdaab30569cc40a4b1",
        ),
        (
            2,
            True,
            "9eee84918799f3fa2d540a75a731b9293fc30cb4213fee87cdad20e6f142d978",
            "9974e6bab51ad51d5c0255d64e5fcd90d3905cab63390443c81eaa4391f48cb4",
        ),
    ],
)
def test_measured_v1_v2_archive_identity(mix_project, version, stereo, request_hash, archive_hash):  # noqa: F811
    pair = routed_project.__wrapped__(mix_project) if version == 2 else mix_project
    root, request = pair
    if stereo:
        if version == 1:
            request["plan"]["routing"] = {"tracks": []}
        make_stereo(root, request)
    assert load_mix_request(request).canonical_id() == "sha256:" + request_hash
    assert _render(root, request)["output_sha256"] == "sha256:" + archive_hash


def test_layer_defaults_and_legacy_stack_gain_preserved():
    from kinocut_sound import defaults, limits
    from kinocut_sound.world import layers, loop

    assert layers.DEFAULT_LAYER_DUCKING_ATTENUATION_DB == defaults.DEFAULT_LAYER_DUCKING_ATTENUATION_DB == 9
    assert layers.DEFAULT_LAYER_DUCKING_ATTACK_MS == defaults.DEFAULT_LAYER_DUCKING_ATTACK_MS == 80
    assert layers.DEFAULT_LAYER_DUCKING_RELEASE_MS == defaults.DEFAULT_LAYER_DUCKING_RELEASE_MS == 350
    assert layers.DEFAULT_LAYER_DUCKING_RECOVERY_MS == defaults.DEFAULT_LAYER_DUCKING_RECOVERY_MS == 500
    assert layers._MAX_LAYERS == limits.MAX_AMBIENT_LAYERS == 64
    assert loop._MAX_REPEATS == limits.MAX_AMBIENT_EXTRA_REPEATS == 10000
    assert layers.LayerStack(()).bus_gain_db() == -6
