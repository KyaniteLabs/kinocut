"""Stereo frames and linked control preserve channel separation and mono bytes."""

from array import array
import hashlib
import json
import zipfile

import pytest

from kinocut_sound.delivery import StemLayout
from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import decode_pcm_wav, parse_wav, pcm_to_wav
from kinocut_sound.mix.crossfade import crossfade_pair
from kinocut_sound.mix.ducking import duck_bed_under_speech
from kinocut_sound.mix.stems import StemBundle, build_stem_bundle, recombine_stems
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401


def stereo(values, rate=22050):
    return pcm_to_wav(array("h", values), sample_rate_hz=rate, channel_count=2)


@pytest.fixture
def stereo_project(mix_project):  # noqa: F811
    root, request = mix_project
    request["plan"]["format"]["channel_layout"] = "stereo"
    for clip, right in zip(request["clips"], (3000, 1000), strict=True):
        left, rate = parse_wav((root / clip["path"]).read_bytes())
        data = stereo([value for sample in left for value in (sample, right)], rate)
        (root / clip["path"]).write_bytes(data)
        clip["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    return root, request


def test_mono_archive_is_byte_identical(mix_project):  # noqa: F811
    root, request = mix_project
    assert (
        _render(root, request)["output_sha256"]
        == "sha256:47ccb879a5bbda14a80c356503940aba73e6d1285a02af93e69b6095a83790c4"
    )


def inspect_stereo(root, result):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, rate, channels = decode_pcm_wav(archive.read("master.wav"))
        assert channels == 2 and len(pcm) == 2 * round(0.6 * rate)
        assert tuple(pcm[:2]) == (8000, 3000)
        assert tuple(pcm[14000:14002]) == (-6000, 1000)
        assert not any(pcm[17640:])
        assert pcm[8820] > 0 and pcm[8821] > 1000
        for name, metadata in receipt["media"].items():
            data = archive.read(name)
            assert metadata == {"bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        assert receipt["schema_version"] == 2
        assert receipt["frame_count"] == receipt["sample_count"] == len(pcm) // 2
        assert receipt["interleaved_sample_count"] == len(pcm)
        assert receipt["source_windows"][0]["out_frame"] == 6615
        assert "in_sample" not in receipt["source_windows"][0]
    return receipt


def test_stereo_public_frames_and_channels(stereo_project):
    root, request = stereo_project
    result = _render(root, request)
    assert result["channel_count"] == 2 and result["schema_version"] == 2
    inspect_stereo(root, result)


@pytest.mark.parametrize("speech_frame", [(16000, 0), (16000, -16000)])
def test_linked_ducking_handles_left_only_and_antiphase(speech_frame):
    speech = stereo(list(speech_frame) * 1000)
    bed = stereo([10000, 5000] * 1000)
    output, _, _ = decode_pcm_wav(duck_bed_under_speech(speech, bed))
    assert output[-2] < 3000 and output[-1] < 1500
    assert abs(output[-2] - 2 * output[-1]) <= 1


def test_one_frame_fade_has_one_shared_gain():
    output = crossfade_pair(stereo([1000, -2000]), stereo([8000, 6000]), fade_seconds=1 / 22050)
    assert tuple(decode_pcm_wav(output)[0]) == (1000, -2000)


@pytest.mark.parametrize("channels", [1, 2])
def test_saturated_stems_preserve_nonsorted_insertion_order(channels):
    layout = StemLayout(stem_ids=("z", "a", "m"))
    data = {
        name: pcm_to_wav(array("h", [sample] * channels), sample_rate_hz=22050, channel_count=channels)
        for name, sample in (("z", 30000), ("a", 30000), ("m", -30000))
    }
    result = recombine_stems(build_stem_bundle(layout=layout, stem_wavs=data))
    assert tuple(decode_pcm_wav(result)[0]) == (2767,) * channels


@pytest.mark.parametrize("kind", ["metadata", "channels", "rate", "frames"])
def test_manually_constructed_stereo_bundle_is_validated(kind):
    first, second = stereo([100, 200]), stereo([300, 400])
    channel_count, rate = 2, 22050
    if kind == "metadata":
        channel_count = 1
    elif kind == "channels":
        second = pcm_to_wav(array("h", [300]), sample_rate_hz=22050)
    elif kind == "rate":
        rate = 48000
    else:
        second = stereo([300, 400] * 2)
    bundle = StemBundle(StemLayout(stem_ids=("a", "b")), {"a": first, "b": second}, rate, channel_count)
    with pytest.raises(MixError):
        recombine_stems(bundle)


def test_mono_parser_remains_closed_and_stereo_requires_complete_frames():
    with pytest.raises(MixError):
        parse_wav(stereo([100, 200]))
    with pytest.raises(MixError):
        stereo([100])


def test_stereo_trim_selects_frames_before_crossfade(stereo_project):
    root, request = stereo_project
    path = root / "a.wav"
    samples, rate, _ = decode_pcm_wav(path.read_bytes())
    data = stereo([123, 456] * 1100 + list(samples))
    path.write_bytes(data)
    request["clips"][0]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    cue = request["plan"]["timeline"]["cues"][0]
    cue.update(in_point_seconds=1100 / rate, out_point_seconds=7715 / rate)
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("master.wav"))
        assert tuple(pcm[:2]) == (8000, 3000)
        window = json.loads(archive.read("receipt.json"))["source_windows"][0]
        assert (window["in_frame"], window["out_frame"], window["frame_count"]) == (1100, 7715, 6615)


def test_stereo_bed_uses_linked_ducking_through_public_mix(stereo_project):
    root, request = stereo_project
    data = stereo([10000, 5000] * 13230)
    (root / "bed.wav").write_bytes(data)
    request["bed"] = {"path": "bed.wav", "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    request["plan"]["beds"] = ["bed.wav"]
    request["duck_bed"] = True
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        bed, _, _ = decode_pcm_wav(archive.read("stems/ambience.wav"))
    assert bed[8000] < 3000 and abs(bed[8000] - 2 * bed[8001]) <= 1


@pytest.mark.parametrize("offset,value", [(22, 3), (32, 2), (34, 24)])
def test_stereo_rejects_inconsistent_frame_headers(offset, value):
    import struct

    data = bytearray(stereo([100, 200]))
    struct.pack_into("<H", data, offset, value)
    with pytest.raises(MixError):
        decode_pcm_wav(bytes(data))


def test_stereo_memory_admission_counts_both_channels(stereo_project, monkeypatch):
    from kinocut_sound.public import mix_request

    _, request = stereo_project
    parsed = mix_request.SoundMixRequest.model_validate(request)
    # The same 0.6-second timeline fits as mono but exceeds this stereo budget.
    monkeypatch.setattr(mix_request, "MAX_MIX_MEMORY_BYTES", 900000)
    with pytest.raises(MixError, match="memory limits"):
        mix_request.check_mix_resources(parsed, 0)
    request["plan"]["format"]["channel_layout"] = "mono"
    mix_request.check_mix_resources(mix_request.SoundMixRequest.model_validate(request), 0)


@pytest.mark.parametrize("kind", ["clip_channels", "clip_rate", "bed_channels"])
def test_stereo_rejects_mismatched_sources_without_publication(stereo_project, kind):
    root, request = stereo_project
    if kind == "bed_channels":
        data = pcm_to_wav(array("h", [1000] * 13230), sample_rate_hz=22050)
        (root / "bed.wav").write_bytes(data)
        request["bed"] = {"path": "bed.wav", "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        request["plan"]["beds"] = ["bed.wav"]
    else:
        data = (
            pcm_to_wav(array("h", [1000] * 6615), sample_rate_hz=22050)
            if kind == "clip_channels"
            else stereo([1000, 2000] * 6615, 48000)
        )
        (root / request["clips"][0]["path"]).write_bytes(data)
        request["clips"][0]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    with pytest.raises(MixError):
        _render(root, request)
    assert not (root / request["output_path"]).exists()
