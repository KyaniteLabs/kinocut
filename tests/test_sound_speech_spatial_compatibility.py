"""V1 and dry V2 keep identical generated audio on the same installation."""

import hashlib
import json
import zipfile
import pytest

from kinocut_sound.public import dub_spatial
from kinocut_sound.public.dub_job import render_dub_request
from kinocut_sound.public.dub_request import load_dub_request
from tests.test_sound_dub_render import dub_project, _require_engine  # noqa: F401


def _media(root, result):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name.endswith(".wav")}, json.loads(
            archive.read("receipt.json")
        )


@pytest.mark.parametrize(
    "language,request_hash",
    [
        ("en", "73f24226721e51ffce04cd44caef89e1445ddb35be7ede1f6b3179377b8cccaf"),
        ("es", "e54f1365aefd5364d05044d7cf5957eec3dd38a20d896e647d8f4a2ef86daa43"),
    ],
)
def test_v1_and_dry_v2_audio_are_exact(dub_project, monkeypatch, language, request_hash):  # noqa: F811
    _require_engine()
    root, request = dub_project
    request["target_lang"] = language
    if language == "en":
        data = (
            (root / "captions.srt")
            .read_bytes()
            .replace(b"Hola mundo", b"Hello world")
            .replace(b"Gracias", b"Thank you")
        )
        (root / "captions.srt").write_bytes(data)
        request["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert load_dub_request(request).canonical_id() == "sha256:" + request_hash
    legacy, legacy_receipt = _media(root, render_dub_request(request, str(root)))
    assert "spatial" not in legacy_receipt and "request_schema_version" not in legacy_receipt

    def forbidden():
        raise AssertionError("dry profile resolved FFmpeg")

    monkeypatch.setattr(dub_spatial, "_binary", forbidden)
    request.update(schema_version=2, spatial_profile="close_mic_dry", output_path="dry.zip")
    dry, receipt = _media(root, render_dub_request(request, str(root)))
    assert dry == legacy
    assert receipt["spatial"]["backend"] is None
    assert all(
        not cue["applied"] and cue["dry_sha256"] == cue["processed_sha256"] for cue in receipt["spatial"]["cues"]
    )
