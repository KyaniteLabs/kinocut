"""Actual V3 layer rendering through the shared public supplied-media path."""

from array import array
import copy
import hashlib
import json
import zipfile

import pytest

from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401


@pytest.fixture
def layered_project(routed_project):  # noqa: F811
    root, request = routed_project
    data = pcm_to_wav(array("h", [1000, 2000, -3000, -4000]), sample_rate_hz=22050)
    (root / "layer.wav").write_bytes(data)
    request.update(
        schema_version=3,
        layer_assets=[
            {
                "layer": {
                    "layer_id": "wind",
                    "asset_ref": "wind-recording",
                    "gain_db": 0,
                    "muted": False,
                    "soloed": False,
                },
                "source": {"path": "layer.wav", "sha256": "sha256:" + hashlib.sha256(data).hexdigest()},
                "fill_mode": "pad",
                "crossfade_frames": None,
            }
        ],
    )
    request["plan"]["layers"] = ["wind"]
    return root, request


def test_v3_admits_and_renders_declared_layer(layered_project):
    root, request = layered_project
    assert load_mix_request(request).schema_version == 3
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("stems/ambience.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert list(pcm[:6]) == [1000, 2000, -3000, -4000, 0, 0]
    assert result["schema_version"] == receipt["schema_version"] == 4
    assert result["request_schema_version"] == 3
    assert result["layer_count"] == 1
    assert len(pcm) == 13230


def inspect_layers(root, request):
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return decode_pcm_wav(archive.read("stems/ambience.wav"))[0], json.loads(archive.read("receipt.json"))


@pytest.mark.parametrize(
    "muted,solo,other_solo,expected",
    [
        (False, False, False, 2000),
        (True, False, False, 1000),
        (False, True, False, 1000),
        (False, False, True, 1000),
        (True, True, False, 0),
    ],
)
def test_layer_mute_solo_and_explicit_duplicate_contributions(layered_project, muted, solo, other_solo, expected):
    root, request = layered_project
    first = request["layer_assets"][0]
    second = copy.deepcopy(first)
    first["layer"].update(muted=muted, soloed=solo)
    second["layer"].update(layer_id="rain", soloed=other_solo)
    request["layer_assets"].append(second)
    request["plan"]["layers"].append("rain")
    pcm, receipt = inspect_layers(root, request)
    assert pcm[0] == expected
    assert len(receipt["layers"]["entries"]) == 2
    assert not any(pcm[4:])


def test_real_loop_fills_authoritative_tail(layered_project):
    root, request = layered_project
    request["layer_assets"][0].update(fill_mode="loop", crossfade_frames=2)
    pcm, receipt = inspect_layers(root, request)
    assert list(pcm[:6]) == [1000, 2000, -1000, 2000, -1000, 2000]
    assert list(pcm[-4:]) == [-1000, 2000, -3000, -4000]
    assert receipt["layers"]["entries"][0]["fill"]["copies"] == 6614


def test_layers_follow_existing_bed_and_precede_bus_gain(layered_project):
    from tests.test_sound_static_routing import add_bed

    root, request = layered_project
    add_bed(root, request, value=30000)
    request["layer_assets"][0]["layer"]["gain_db"] = 12
    request["plan"]["routing"]["buses"][1]["gain_db"] = -6.020599913279624
    pcm, _ = inspect_layers(root, request)
    assert pcm[0] == 16384  # Saturate bed+layer first, then halve the complete bus.


def test_layer_order_affects_saturation_and_identity(layered_project):
    root, request = layered_project
    for name, value in (("positive", 30000), ("negative", -30000)):
        item = copy.deepcopy(request["layer_assets"][0])
        data = pcm_to_wav(array("h", [value] * 4), sample_rate_hz=22050)
        path = name + ".wav"
        (root / path).write_bytes(data)
        item["layer"].update(layer_id=name, asset_ref=name)
        item["source"] = {"path": path, "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        request["layer_assets"].append(item)
        request["plan"]["layers"].append(name)
    request["layer_assets"][0]["layer"]["gain_db"] = 12
    first_hash = load_mix_request(request).canonical_id()
    first, _ = inspect_layers(root, request)
    request["layer_assets"].reverse()
    request["plan"]["layers"].reverse()
    assert load_mix_request(request).canonical_id() != first_hash
    request["output_path"] = "reordered.zip"
    second, _ = inspect_layers(root, request)
    assert first[0] == 2767 and second[0] == 3981


def test_silence_only_timeline_can_render_layers(layered_project):
    root, request = layered_project
    request["clips"] = []
    request["cue_tracks"] = []
    request["transitions"] = []
    request["plan"]["routing"]["tracks"] = []
    request["plan"]["timeline"]["cues"] = [request["plan"]["timeline"]["cues"][-1]]
    request["plan"]["timeline"]["cues"][0]["start_seconds"] = 0
    pcm, _ = inspect_layers(root, request)
    assert list(pcm[:4]) == [1000, 2000, -3000, -4000]


def test_existing_bed_ducking_does_not_duck_explicit_layers(layered_project):
    from tests.test_sound_static_routing import add_bed

    root, request = layered_project
    add_bed(root, request, value=10000)
    request["duck_bed"] = True
    layered, _ = inspect_layers(root, request)
    request.update(output_path="bed-only.zip", layer_assets=[])
    request["plan"]["layers"] = []
    bed_only, _ = inspect_layers(root, request)
    assert [a - b for a, b in zip(layered[:4], bed_only[:4], strict=True)] == [1000, 2000, -3000, -4000]
    assert layered[4:] == bed_only[4:]
