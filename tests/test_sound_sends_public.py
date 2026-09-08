"""Declared sends must transfer real PCM through the public mix path."""

import json
import zipfile

import pytest

from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, add_bed  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project  # noqa: F401
from tests.test_sound_automation_public import automated_project  # noqa: F401


@pytest.fixture
def sent_project(routed_project):  # noqa: F811
    root, request = routed_project
    request["plan"]["routing"]["sends"] = [
        {
            "send_id": "room",
            "source_bus_id": "dialogue",
            "destination_bus_id": "ambience",
            "gain_db": -6.020599913279624,
            "post_fader": True,
        }
    ]
    return root, request


def test_post_fader_send_changes_actual_destination_stem(sent_project):
    root, request = sent_project
    assert load_mix_request(request).plan.routing.sends
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("stems/ambience.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert pcm[0] == 8000
    assert result["send_count"] == 1
    assert receipt["routing"]["algorithm"] == "sent_pcm16_ties_even_v1"


def inspect(root, request, stem="ambience"):
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return decode_pcm_wav(archive.read(f"stems/{stem}.wav"))[0], json.loads(archive.read("receipt.json"))


def add_send(request, source="dialogue", target="ambience", post=True):
    request["plan"]["routing"]["sends"] = [
        {
            "send_id": "send",
            "source_bus_id": source,
            "destination_bus_id": target,
            "gain_db": -6.020599913279624,
            "post_fader": post,
        }
    ]


def test_send_composes_with_automated_track_dsp(automated_project):  # noqa: F811
    root, request = automated_project
    add_send(request)
    pcm, receipt = inspect(root, request)
    assert pcm[0] == 2000 and pcm[4410] == 4000
    assert receipt["routing"]["track_algorithm"] == "automated_pcm16_ties_even_v1"
    assert "automation" in receipt["routing"]


def test_send_adds_to_existing_bed_before_destination_gain(sent_project):
    root, request = sent_project
    add_bed(root, request, value=1000)
    request["plan"]["routing"]["buses"][1]["gain_db"] = 6.020599913279624
    pcm, _ = inspect(root, request)
    assert pcm[0] == 18000


def test_layer_duck_detector_stays_before_send_returns(ducked_project):  # noqa: F811
    root, request = ducked_project
    add_send(request, source="ambience", target="sfx")
    request["layer_ducking"]["source_bus_id"] = "sfx"  # No direct SFX clips.
    ambience, receipt = inspect(root, request)
    assert ambience[0] == 10000  # Returned layer audio does not feed its own detector.
    summary = receipt["layers"]["ducking"]["summary"]
    assert summary["active_frames"] == 0
    assert receipt["layers"]["ducking"]["source_position"] == "after_clips_before_sends_and_bus_gain"
    with zipfile.ZipFile(root / request["output_path"]) as archive:
        assert decode_pcm_wav(archive.read("stems/sfx.wav"))[0][0] == 5000
