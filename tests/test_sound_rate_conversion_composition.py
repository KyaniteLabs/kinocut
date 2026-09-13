"""Converted clips/layers retain all existing routed processing stages."""

from array import array
import copy
import hashlib
import json
import zipfile
import pytest

from kinocut_sound.mix._wav import pcm_to_wav, decode_pcm_wav
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_layers_public import layered_project
from tests.test_sound_layer_ducking_public import ducked_project
from tests.test_sound_sends_public import add_send


@pytest.fixture
def converted_layers(routed_project):  # noqa: F811
    root, request = ducked_project.__wrapped__(layered_project.__wrapped__(routed_project))
    request["schema_version"] = 4
    request["source_resampling"] = {"profile": "soxr_vhq_pcm16_guarded_v1"}
    request["plan"]["format"]["sample_rate_hz"] = 32000
    data = pcm_to_wav(array("h", [10000] * 2205), sample_rate_hz=22050)
    (root / "layer.wav").write_bytes(data)
    layer = request["layer_assets"][0]
    layer["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    layer.update(fill_mode="loop", crossfade_frames=200)
    request["plan"]["routing"]["envelopes"] = [
        {
            "target_track_id": "voice-a",
            "parameter": "gain_db",
            "points": [{"time_seconds": 0, "value": -60}, {"time_seconds": 0.1, "value": 0}],
        }
    ]
    add_send(request, source="dialogue", target="sfx")
    request["plan"]["routing"]["sidechains"] = [
        {
            "source_bus_id": "sfx",
            "target_bus_id": "ambience",
            "attenuation_db": 9,
            "attack_ms": 80,
            "release_ms": 100,
            "recovery_ms": 100,
        }
    ]
    return root, request


def _inspect(root, result):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return decode_pcm_wav(archive.read("stems/ambience.wav"))[0], json.loads(archive.read("receipt.json"))


@pytest.mark.parametrize("stereo", [False, True])
def test_conversion_composes_with_every_routed_stage(converted_layers, stereo):
    root, request = converted_layers
    if stereo:
        make_stereo(root, request)
        data = pcm_to_wav(array("h", [10000, -5000] * 2205), sample_rate_hz=22050, channel_count=2)
        (root / "layer.wav").write_bytes(data)
        request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    result = _render(root, request)
    pcm, receipt = _inspect(root, result)
    assert result["converted_source_count"] == 3
    assert result["automation_envelope_count"] == result["send_count"] == result["sidechain_count"] == 1
    assert result["layer_ducking_sha256"] and receipt["layers"]["entries"][0]["fill_mode"] == "loop"
    control = copy.deepcopy(request)
    control["output_path"] = "without-final.zip"
    control["plan"]["routing"]["sidechains"] = []
    control_pcm, _ = _inspect(root, _render(root, control))
    index = round(0.18 * 32000) * (2 if stereo else 1)
    assert control_pcm[index] != 0 and abs(pcm[index]) < abs(control_pcm[index]) / 2


def test_shared_asset_has_distinct_layer_role_entries(converted_layers):
    root, request = converted_layers
    extra = copy.deepcopy(request["layer_assets"][0])
    extra["layer"]["layer_id"] = "second-layer"
    request["layer_assets"].append(extra)
    request["plan"]["layers"].append("second-layer")
    result = _render(root, request)
    _pcm, receipt = _inspect(root, result)
    layers = [entry for entry in receipt["source_resampling"]["entries"] if entry["kind"] == "layer"]
    assert len(layers) == 2 and layers[0]["binding_id"] != layers[1]["binding_id"]
    assert layers[0]["asset_ref"] == layers[1]["asset_ref"]
    assert layers[0]["derived"]["sha256"] == layers[1]["derived"]["sha256"]
