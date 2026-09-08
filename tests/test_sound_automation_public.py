"""Public automation must change actual PCM on the authoritative timeline."""

from array import array
import hashlib
import json
import zipfile

import pytest

from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project  # noqa: F401


@pytest.fixture
def automated_project(routed_project):  # noqa: F811
    root, request = routed_project
    request["plan"]["routing"]["envelopes"] = [
        {
            "target_track_id": "voice-a",
            "parameter": "gain_db",
            "points": [{"time_seconds": 0, "value": -6.020599913279624}, {"time_seconds": 0.2, "value": 0}],
        }
    ]
    return root, request


def test_global_gain_automation_replaces_static_value(automated_project):
    root, request = automated_project
    assert load_mix_request(request).plan.routing.envelopes
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("master.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert pcm[0] == 4000 and pcm[4409] == 7999 and pcm[4410] == 8000
    assert receipt["routing"]["algorithm"] == "automated_pcm16_ties_even_v1"
    assert result["automation_envelope_count"] == 1 and result["automation_point_count"] == 2


def rendered(root, request):
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return decode_pcm_wav(archive.read("master.wav"))[0], json.loads(archive.read("receipt.json"))


def test_in_point_selects_media_without_shifting_automation_clock(automated_project):
    root, request = automated_project
    data = pcm_to_wav(array("h", [1234] * 1102 + [8000] * 6615), sample_rate_hz=22050)
    (root / "a.wav").write_bytes(data)
    request["clips"][0]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    request["plan"]["timeline"]["cues"][0].update(in_point_seconds=1102 / 22050, out_point_seconds=7717 / 22050)
    pcm, receipt = rendered(root, request)
    assert pcm[0] == 4000 and pcm[4409] == 7999
    assert receipt["source_windows"][0]["in_sample"] == 1102


def share_track(request):
    request["plan"]["routing"]["tracks"].pop()
    request["cue_tracks"][1]["track_id"] = "voice-a"


def test_multiple_cues_use_global_time_and_explicit_parameter_sources(automated_project):
    root, request = automated_project
    share_track(request)
    pcm, receipt = rendered(root, request)
    assert pcm[0] == 4000 and pcm[7000] == -6000
    track = receipt["routing"]["tracks"][0]
    assert "channel_factors" not in track
    assert track["parameter_sources"] == {"gain_db": "envelope", "pan_position": "track"}
    assert receipt["routing"]["cue_tracks"][1]["start_frame"] == 4410


def test_crossfade_automates_both_sources_at_same_global_frames(automated_project):
    root, request = automated_project
    share_track(request)
    request["plan"]["routing"]["envelopes"][0]["points"] = [
        {"time_seconds": 0.2, "value": -6.020599913279624},
        {"time_seconds": 0.3, "value": 0},
    ]
    pcm, _ = rendered(root, request)
    assert pcm[4410] == 4000 and pcm[5512] == 709 and pcm[7000] == -6000


@pytest.mark.parametrize(
    "law,expected",
    [
        ("linear", [8000, 0, 6000, 1000, 4000, 2000, 2000, 3000, 0, 4000]),
        ("balanced", [8000, 0, 8000, 2000, 8000, 4000, 4000, 4000, 0, 4000]),
        ("constant_power", [8000, 0, 7391, 1531, 5657, 2828, 3061, 3696, 0, 4000]),
    ],
)
def test_pan_curves_use_each_existing_law(automated_project, law, expected):
    root, request = automated_project
    make_stereo(root, request)
    request["plan"]["routing"]["tracks"][0]["pan_law"] = law
    request["plan"]["routing"]["envelopes"] = [
        {
            "target_track_id": "voice-a",
            "parameter": "pan_position",
            "points": [{"time_seconds": 0, "value": -1}, {"time_seconds": 4 / 22050, "value": 1}],
        }
    ]
    pcm, _ = rendered(root, request)
    assert list(pcm[:10]) == expected


def test_declaration_order_changes_identity_but_not_pcm(automated_project):
    root, request = automated_project
    rows = request["plan"]["routing"]["envelopes"]
    rows.append(
        {"target_track_id": "voice-a", "parameter": "pan_position", "points": [{"time_seconds": 0, "value": 0}]}
    )
    first_hash = load_mix_request(request).canonical_id()
    first, first_receipt = rendered(root, request)
    rows.reverse()
    assert load_mix_request(request).canonical_id() != first_hash
    request["clips"].reverse()
    request["cue_tracks"].reverse()
    request["output_path"] = "reordered.zip"
    second, second_receipt = rendered(root, request)
    assert first == second
    assert first_receipt["routing"]["automation"] == second_receipt["routing"]["automation"]


def test_mute_and_solo_still_win_over_automation(automated_project):
    root, request = automated_project
    request["plan"]["routing"]["tracks"][0].update(muted=True, soloed=True)
    pcm, _ = rendered(root, request)
    assert not any(pcm)


def test_layer_ducking_detects_automated_source_before_bus_gain(ducked_project):  # noqa: F811
    root, request = ducked_project
    request["plan"]["routing"]["envelopes"] = [
        {
            "target_track_id": "voice-a",
            "parameter": "gain_db",
            "points": [{"time_seconds": 0, "value": -60}, {"time_seconds": 0.1, "value": 0}],
        }
    ]
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("stems/ambience.wav"))
    assert pcm[0] == 10000 and pcm[2205] < 10000
