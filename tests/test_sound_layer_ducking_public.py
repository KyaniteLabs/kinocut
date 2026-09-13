"""Real V3 layer ducking changes retained PCM and reports recovery honestly."""

from array import array
import hashlib
import json
import zipfile

import pytest

from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401


@pytest.fixture
def ducked_project(layered_project):  # noqa: F811
    root, request = layered_project
    data = pcm_to_wav(array("h", [10000] * 13230), sample_rate_hz=22050)
    (root / "layer.wav").write_bytes(data)
    request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    request["layer_ducking"] = dict(source_bus_id="dialogue", target_bus_id="ambience", release_ms=100, recovery_ms=100)
    return root, request


def test_declared_layer_ducking_changes_actual_pcm(ducked_project):
    root, request = ducked_project
    assert load_mix_request(request).layer_ducking is not None
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("stems/ambience.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert pcm[0] == 9996 and pcm[1763] == 3548 and pcm[11024] == 10000
    assert receipt["layers"]["ducking"]["summary"]["recovery_status"] == "pass"
    assert "layer_ducking_sha256" in result


def inspect_ducking(root, request):
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return decode_pcm_wav(archive.read("stems/ambience.wav"))[0], json.loads(archive.read("receipt.json"))


@pytest.mark.parametrize("change,expected", [("source_bus", 9996), ("target_bus", 19992), ("layer_gain", 19993)])
def test_ducking_signal_order_is_explicit(ducked_project, change, expected):
    root, request = ducked_project
    if change == "source_bus":
        request["plan"]["routing"]["buses"][0]["gain_db"] = -60
    elif change == "target_bus":
        request["plan"]["routing"]["buses"][1]["gain_db"] = 6.020599913279624
    else:
        request["layer_assets"][0]["layer"]["gain_db"] = 6.020599913279624
    pcm, _ = inspect_ducking(root, request)
    assert pcm[0] == expected


def test_non_dialogue_source_bus_and_all_muted_evidence(ducked_project):
    root, request = ducked_project
    for clip in request["clips"]:
        clip["stem_id"] = "sfx"
    for track in request["plan"]["routing"]["tracks"]:
        track["destination_bus_id"] = "sfx"
    request["layer_ducking"]["source_bus_id"] = "sfx"
    pcm, _ = inspect_ducking(root, request)
    assert pcm[1763] == 3548
    request["output_path"] = "muted.zip"
    request["layer_assets"][0]["layer"]["muted"] = True
    pcm, receipt = inspect_ducking(root, request)
    assert not any(pcm)
    assert receipt["layers"]["ducking"]["summary"]["active_frames"] > 0


def test_bed_ducking_and_layer_ducking_remain_independent(ducked_project):
    from tests.test_sound_static_routing import add_bed

    root, request = ducked_project
    add_bed(root, request, value=1000)
    request["duck_bed"] = True
    combined, _ = inspect_ducking(root, request)
    request.update(output_path="bed-only.zip", layer_assets=[], layer_ducking=None)
    request["plan"]["layers"] = []
    bed, _ = inspect_ducking(root, request)
    assert combined[0] - bed[0] == 9996
    assert combined[1763] - bed[1763] == 3548


def test_truncated_public_release_is_not_reported_as_complete(ducked_project):
    root, request = ducked_project
    request["layer_ducking"].update(release_ms=350, recovery_ms=500)
    _, receipt = inspect_ducking(root, request)
    summary = receipt["layers"]["ducking"]["summary"]
    assert summary["truncated_recovery"] and summary["truncated_release_frames"] == 4410
    assert summary["recovery_status"] == "not_exercised"
