"""Measured no-duck V3 archives remain byte-identical when ducking is enabled."""

from array import array
import hashlib

import pytest

from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401


@pytest.mark.parametrize(
    "stereo,loop,request_hash,archive_hash",
    [
        (
            False,
            False,
            "cfcb83066b0bcb8cbb70bca931454e71ae3efb792493cf3b302421501ceed790",
            "9475c736a6faa01ee08c28187552b3b85f058c779d24c0affdc999d7858ec4cb",
        ),
        (
            False,
            True,
            "bb1021185dfe967cfa273aae2b3c412655983ee104c6c8148b91fac3e3192550",
            "36dfdf9f930dc3dae74a2a26065ddbf7fee04aee22a2f974bc638c57aaecaa29",
        ),
        (
            True,
            False,
            "09fb4befebdea5e120a595599b1796d77bfc619fbfd8d0a82a2c1e3d3a56a44a",
            "506f633718413a50d1ab6ec7068984a66d876349665806881e89b811d1d26da8",
        ),
        (
            True,
            True,
            "4ad50b50e8d2bad2442b02d90f4b14be8608209f40288420cfe8c05c41c55998",
            "1d2f11517b18dd4519042ecffbf948fc003e7a95c97c7e5272b0960d852dd36a",
        ),
    ],
)
def test_no_duck_v3_archive_identity(layered_project, stereo, loop, request_hash, archive_hash):  # noqa: F811
    root, request = layered_project
    if stereo:
        make_stereo(root, request)
        data = pcm_to_wav(
            array("h", [1000, -500, 2000, -1000, -3000, 1500, -4000, 2000]), sample_rate_hz=22050, channel_count=2
        )
        (root / "layer.wav").write_bytes(data)
        request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    if loop:
        request["layer_assets"][0].update(fill_mode="loop", crossfade_frames=2)
    assert load_mix_request(request).canonical_id() == "sha256:" + request_hash
    assert _render(root, request)["output_sha256"] == "sha256:" + archive_hash
