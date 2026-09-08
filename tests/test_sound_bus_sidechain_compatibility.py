"""Four measured send-bearing artifacts stay exact with no sidechains."""

from array import array
import hashlib
import pytest

from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_sends_public import sent_project, add_send
from tests.test_sound_layers_public import layered_project
from tests.test_sound_layer_ducking_public import ducked_project


@pytest.mark.parametrize(
    "layered,stereo,request_hash,archive_hash",
    [
        (
            False,
            False,
            "68ac453de488092aa30adc5073d8cf68a08f08e2b40fda7a97c2d630600573b2",
            "94a6fe7a0456d2913f3fac1aaa92dc59c7525ad95126330a5930b97d4c9c4d9b",
        ),
        (
            False,
            True,
            "68f92b6afe64577dfca56fc17080f5572232a2b9bcbc69e02621f24f2343a83a",
            "abc72bd3a97ea338556ffcd39e6460b5e74f988ead5831203af7e1f66f732bff",
        ),
        (
            True,
            False,
            "05ff2a24cde07e7025dde4a767c8bfa9b5e8713e60a1041a75e599c6a0dc0067",
            "ca5e7cd71a0ebc2cb2794f800eacea1df01436125f5c04dd43e2d9e15c21ec99",
        ),
        (
            True,
            True,
            "1ecb478d8f6528d68427f9af64571c1a2c501f6052aacdd44b0d7b9ff81db24d",
            "2d2aefb38259d776297ac4fe2e0c920c5a80a969688b4edfafea4a31678ee469",
        ),
    ],
)
def test_no_sidechain_send_archives_unchanged(routed_project, layered, stereo, request_hash, archive_hash):  # noqa: F811
    if layered:
        root, request = ducked_project.__wrapped__(layered_project.__wrapped__(routed_project))
        request["plan"]["routing"]["envelopes"] = [
            {
                "target_track_id": "voice-a",
                "parameter": "gain_db",
                "points": [
                    {"time_seconds": 0, "value": -60},
                    {"time_seconds": 0.1, "value": 0},
                ],
            }
        ]
        add_send(request)
    else:
        root, request = sent_project.__wrapped__(routed_project)
    if stereo:
        make_stereo(root, request)
        if layered:
            data = pcm_to_wav(array("h", [10000, -5000] * 13230), sample_rate_hz=22050, channel_count=2)
            (root / "layer.wav").write_bytes(data)
            request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert load_mix_request(request).canonical_id() == "sha256:" + request_hash
    assert _render(root, request)["output_sha256"] == "sha256:" + archive_hash
