"""Four measured automated no-send artifacts supplement ten earlier goldens."""

from array import array
import hashlib

import pytest

from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_layers_public import layered_project
from tests.test_sound_layer_ducking_public import ducked_project
from tests.test_sound_automation_public import automated_project


@pytest.mark.parametrize(
    "layered,stereo,request_hash,archive_hash",
    [
        (
            False,
            False,
            "cade68f50adf09ba0137e708559bd848e1664b668684d10433402b404308cb5c",
            "bac356b14dc26dd713c2fb13d91019cbcd3c55dcdd576afc667ef6cfbae2e9aa",
        ),
        (
            False,
            True,
            "aff030879c7e24c2ee262aba44e436c16ee2f71600cf7ac2621c9c1aca935682",
            "a6626bf603463014bb2c13a8886d66d747b89df7acbb4bf553a1b41836416a8e",
        ),
        (
            True,
            False,
            "5a8a4f3338d6981239e393e5684738e4a1214cb2b1954a19bd9518e2f5ed9edc",
            "df676967492f0a5a61b0ee0333f5869aa9d5d0f103e4ec7fcb6c86afb21ce0e5",
        ),
        (
            True,
            True,
            "d75cf5ec2d289fc9ade9fdd0ace61dc6f623067a288cfc3ec45016bfd1a46eaf",
            "07f47deff0c827c46e8392c2101e4394beb7138ef827183bae5d592239eee5e0",
        ),
    ],
)
def test_no_send_automated_archives_unchanged(routed_project, layered, stereo, request_hash, archive_hash):  # noqa: F811
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
    else:
        root, request = automated_project.__wrapped__(routed_project)
    if stereo:
        make_stereo(root, request)
        if layered:
            data = pcm_to_wav(array("h", [10000, -5000] * 13230), sample_rate_hz=22050, channel_count=2)
            (root / "layer.wav").write_bytes(data)
            request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert load_mix_request(request).canonical_id() == "sha256:" + request_hash
    assert _render(root, request)["output_sha256"] == "sha256:" + archive_hash
