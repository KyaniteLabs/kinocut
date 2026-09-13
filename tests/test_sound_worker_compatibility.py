"""Pre-runner-change sidechain archives remain byte-identical."""

from array import array
import hashlib
import pytest

from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_bus_sidechains_public import sidechain_project
from tests.test_sound_layers_public import layered_project
from tests.test_sound_layer_ducking_public import ducked_project
from tests.test_sound_sends_public import add_send


@pytest.mark.parametrize(
    "layered,stereo,request_hash,archive_hash",
    [
        (
            False,
            False,
            "5a0dd4fcab59acd51e6d84b8df6687c26a4471db50b47806752204730096193e",
            "cbf3cdf5f5a6fe2ee39c716628989a8457856a882a30f60902f3b3e20428cc04",
        ),
        (
            False,
            True,
            "4678b59747ba391f49ebb89e8479b7804f3f36b61879a593ac8a002652d80a49",
            "412bd2c21e242c6f35d6b9d517c7900ee9a6098c3217e3f013d6037c4a5dbcb8",
        ),
        (
            True,
            False,
            "2eca8ee3a099a82ef9f2020948e0a35de424084bffea7be7a39536a6a5843882",
            "5364e3ebbb5cf1f033c5b4a83ccfb37d414bebe6cd34a2b2e18572c110a06787",
        ),
        (
            True,
            True,
            "b2387f6cc0b6f7852da9a1b988b97f30a50ef3bfd07ef6f1eeda31506ed07eb0",
            "9ec170a55e1067b89a08a945464c1be58e788a6663a8aa9328b7da9ab9ae820e",
        ),
    ],
)
def test_sidechain_archive_identity(routed_project, layered, stereo, request_hash, archive_hash):  # noqa: F811
    if layered:
        root, request = ducked_project.__wrapped__(layered_project.__wrapped__(routed_project))
        request["plan"]["routing"]["envelopes"] = [
            {
                "target_track_id": "voice-a",
                "parameter": "gain_db",
                "points": [{"time_seconds": 0, "value": -60}, {"time_seconds": 0.1, "value": 0}],
            }
        ]
        add_send(request)
        request["plan"]["routing"]["sidechains"] = [
            {
                "source_bus_id": "dialogue",
                "target_bus_id": "ambience",
                "attenuation_db": 9,
                "attack_ms": 80,
                "release_ms": 100,
                "recovery_ms": 100,
            }
        ]
    else:
        root, request = sidechain_project.__wrapped__(routed_project)
    if stereo:
        make_stereo(root, request)
        data = pcm_to_wav(array("h", [10000, -5000] * 13230), sample_rate_hz=22050, channel_count=2)
        path = "layer.wav" if layered else "bed.wav"
        (root / path).write_bytes(data)
        binding = request["layer_assets"][0]["source"] if layered else request["bed"]
        binding["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert load_mix_request(request).canonical_id() == "sha256:" + request_hash
    assert _render(root, request)["output_sha256"] == "sha256:" + archive_hash
