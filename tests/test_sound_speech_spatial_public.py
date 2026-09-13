"""Real caption speech, not the plan-mode tone demo, receives spatial effects."""

import hashlib
import json
import zipfile
import pytest

from kinocut_sound.public.dub_job import render_dub_request
from kinocut_sound.mix._wav import parse_wav
from tests.test_sound_dub_render import dub_project, _require_engine  # noqa: F401


@pytest.fixture
def spatial_project(dub_project):  # noqa: F811
    root, request = dub_project
    request.update(schema_version=2, spatial_profile="off_screen_distance")
    return root, request


def test_real_v2_speech_is_processed_and_retained(spatial_project):
    _require_engine()
    root, request = spatial_project
    result = render_dub_request(request, str(root))
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        manifest = json.loads(archive.read("mix-request.json"))
        dialogue = archive.read("dialogue.wav")
    pcm, rate = parse_wav(dialogue)
    assert result["demo"] is False and rate == 22050 and len(pcm) == 176422
    assert result["spatial_profile"] == "off_screen_distance"
    assert receipt["spatial"]["cues"][0]["dry_sha256"] != receipt["spatial"]["cues"][0]["processed_sha256"]
    assert manifest["clips"][0]["sha256"] == "sha256:" + hashlib.sha256(dialogue).hexdigest()
