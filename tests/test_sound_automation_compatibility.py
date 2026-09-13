"""Pre-automation ducked artifacts remain exact, alongside eight older goldens."""

from array import array
import hashlib

import pytest

from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project  # noqa: F401


@pytest.mark.parametrize(
    "stereo,request_hash,archive_hash",
    [
        (
            False,
            "7a15e857a0d307607ebd8b7c76620bf435742838f26c89e327b10fa850be2278",
            "1a9939d61c70c11a62683a71792afcfc8f11ffc0ea17b0d433ff435debf8e4c3",
        ),
        (
            True,
            "807a658e4a2a35baffcda3ddb22c2e9ab206570c2a9a30876f0d31ed8bd06a24",
            "8f5b4a3079404f0835dfe32e0274bd9dad84873b1efaee1891f6a5e02b214012",
        ),
    ],
)
def test_no_envelope_ducked_archives_are_unchanged(ducked_project, stereo, request_hash, archive_hash):  # noqa: F811
    root, request = ducked_project
    if stereo:
        make_stereo(root, request)
        data = pcm_to_wav(array("h", [10000, -5000] * 13230), sample_rate_hz=22050, channel_count=2)
        (root / "layer.wav").write_bytes(data)
        request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert load_mix_request(request).canonical_id() == "sha256:" + request_hash
    assert _render(root, request)["output_sha256"] == "sha256:" + archive_hash
