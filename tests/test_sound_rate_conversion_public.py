"""Explicit V4 resampling must reach real supplied-media output."""

import json
from array import array
import hashlib
import asyncio
import zipfile
import pytest

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, add_bed, make_stereo  # noqa: F401


@pytest.fixture
def converted_project(routed_project):  # noqa: F811
    root, request = routed_project
    request.update(schema_version=4, layer_assets=[], source_resampling={"profile": "soxr_vhq_pcm16_guarded_v1"})
    request["plan"]["format"]["sample_rate_hz"] = 32000
    return root, request


def test_v4_converts_real_sources_before_mix_windows(converted_project):
    root, request = converted_project
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, rate, channels = decode_pcm_wav(archive.read("master.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert rate == 32000 and channels == 1 and len(pcm) == 19200
    assert receipt["schema_version"] == 5 and receipt["request_schema_version"] == 4
    assert receipt["sources"] == request["clips"]
    assert receipt["source_resampling"]["profile"] == "soxr_vhq_pcm16_guarded_v1"
    assert result["converted_source_count"] == 2
    assert result["resampling_sha256"] == canonical_digest(receipt["source_resampling"])
    assert len(receipt["source_resampling"]["entries"]) == 2
    assert "source_0000.wav" not in json.dumps(receipt)


@pytest.mark.parametrize("stereo", [False, True])
def test_bed_is_converted_and_independently_reported(converted_project, stereo):
    root, request = converted_project
    add_bed(root, request, value=1000)
    if stereo:
        make_stereo(root, request)
        data = pcm_to_wav(array("h", [1000, -500] * 13230), sample_rate_hz=22050, channel_count=2)
        (root / "bed.wav").write_bytes(data)
        request["bed"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, rate, channels = decode_pcm_wav(archive.read("stems/ambience.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert rate == 32000 and result["converted_source_count"] == 3
    bed = next(entry for entry in receipt["source_resampling"]["entries"] if entry["kind"] == "bed")
    assert bed["original"]["sha256"] == request["bed"]["sha256"]
    assert abs(pcm[2000 * channels] - 1000) <= 1


def test_trim_and_postroll_use_converted_rate(converted_project):
    root, request = converted_project
    data = pcm_to_wav(array("h", [8000] * 8820), sample_rate_hz=22050)
    (root / "a.wav").write_bytes(data)
    request["clips"][0]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    request["plan"]["timeline"]["cues"][0].update(in_point_seconds=0.05, out_point_seconds=0.4)
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
    window = next(row for row in receipt["source_windows"] if row["cue_id"] == "a")
    assert window["in_sample"] == 1600 and window["out_sample"] == 12800
    assert window["sample_count"] == 11200 and window["sample_rate_hz"] == 32000
    assert receipt["seams"]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_public_same_rate_works_without_ffmpeg(converted_project, monkeypatch, asynchronous):
    from kinocut_sound.public import mix_conversion_prepare
    from kinocut_sound.public.mix_job import render_mix_request_async

    root, request = converted_project
    request["plan"]["format"]["sample_rate_hz"] = 22050

    def forbidden():
        raise AssertionError("same-rate request resolved a backend")

    monkeypatch.setattr(mix_conversion_prepare, "_resolve_backend", forbidden)
    monkeypatch.setenv("PATH", "")
    result = asyncio.run(render_mix_request_async(request, str(root))) if asynchronous else _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
    assert result["converted_source_count"] == 0
    assert all(
        entry["mode"] == "copy"
        and entry["backend"] is None
        and entry["original"]["sha256"] == entry["derived"]["sha256"]
        for entry in receipt["source_resampling"]["entries"]
    )


def test_v4_never_overwrites_existing_archive(converted_project):
    from kinocut_sound.mix._errors import MixError

    root, request = converted_project
    _render(root, request)
    before = (root / "mix.zip").read_bytes()
    with pytest.raises(MixError) as error:
        _render(root, request)
    assert error.value.code == "mix_output_conflict"
    assert (root / "mix.zip").read_bytes() == before
