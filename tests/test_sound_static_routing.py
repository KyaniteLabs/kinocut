"""Versioned static routing must alter actual PCM while preserving V1 bytes."""

import copy
from array import array
import hashlib
import json
import zipfile

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401


@pytest.fixture
def routed_project(mix_project):  # noqa: F811
    root, request = mix_project
    request["schema_version"] = 2
    request["cue_tracks"] = [{"cue_id": name, "track_id": "voice-" + name} for name in ("a", "b")]
    request["plan"]["routing"] = {
        "tracks": [
            {
                "track_id": "voice-" + name,
                "destination_bus_id": "dialogue",
                "gain_db": gain,
                "pan_law": "linear",
                "pan_position": 0,
                "muted": False,
                "soloed": False,
            }
            for name, gain in (("a", 6.020599913279624), ("b", 0))
        ],
        "buses": [
            {"bus_id": name, "kind": name, "gain_db": 0, "pan_law": "linear"}
            for name in ("dialogue", "ambience", "sfx")
        ],
    }
    return root, request


def test_v2_track_gain_changes_retained_pcm(routed_project):
    root, request = routed_project
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("master.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert pcm[0] == 16000 and pcm[7000] == -6000
    assert pcm[5512] == 5004  # Legacy 1102/2205 fade fraction uses both routed sources.
    assert result["schema_version"] == receipt["schema_version"] == 3
    assert receipt["request_schema_version"] == result["request_schema_version"] == 2
    assert receipt["routing"]["cue_tracks"] == request["cue_tracks"]
    assert receipt["routing"]["algorithm"] == "static_pcm16_ties_even_v1"


def test_v2_binding_order_is_canonical(routed_project):
    _, request = routed_project
    original = load_mix_request(request).canonical_id()
    changed = copy.deepcopy(request)
    changed["cue_tracks"].reverse()
    assert load_mix_request(changed).canonical_id() == original
    changed["cue_tracks"][0]["track_id"], changed["cue_tracks"][1]["track_id"] = (
        changed["cue_tracks"][1]["track_id"],
        changed["cue_tracks"][0]["track_id"],
    )
    assert load_mix_request(changed).canonical_id() != original


def test_v1_archive_bytes_remain_unchanged(mix_project):  # noqa: F811
    root, request = mix_project
    assert (
        _render(root, request)["output_sha256"]
        == "sha256:47ccb879a5bbda14a80c356503940aba73e6d1285a02af93e69b6095a83790c4"
    )


@pytest.mark.parametrize("version", [True, 2.0, "2", 3])
def test_v2_version_must_be_exact_supported_integer(routed_project, version):
    _, request = routed_project
    request["schema_version"] = version
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.fixture
def stereo_routed_project(routed_project):
    return make_stereo(*routed_project)


def make_stereo(root, request):
    request["plan"]["format"]["channel_layout"] = "stereo"
    for clip in request["clips"]:
        samples, rate, _ = decode_pcm_wav((root / clip["path"]).read_bytes())
        stereo = array("h", (value for sample in samples for value in (sample, sample // 2)))
        data = pcm_to_wav(stereo, sample_rate_hz=rate, channel_count=2)
        (root / clip["path"]).write_bytes(data)
        clip["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    for track in request["plan"]["routing"]["tracks"]:
        track.update(gain_db=0, pan_law="balanced")
    return root, request


def rendered_pcm(root, request):
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return decode_pcm_wav(archive.read("master.wav"))[0]


@pytest.mark.parametrize(
    "law,position,expected",
    [
        ("linear", -1, (8000, 0)),
        ("linear", 0, (4000, 2000)),
        ("linear", 1, (0, 4000)),
        ("constant_power", -1, (8000, 0)),
        ("constant_power", 0, (5657, 2828)),
        ("constant_power", 1, (0, 4000)),
        ("balanced", -1, (8000, 0)),
        ("balanced", 0, (8000, 4000)),
        ("balanced", 1, (0, 4000)),
    ],
)
def test_stereo_pan_laws_have_explicit_channel_scales(stereo_routed_project, law, position, expected):
    root, request = stereo_routed_project
    request["plan"]["routing"]["tracks"][0].update(pan_law=law, pan_position=position)
    assert tuple(rendered_pcm(root, request)[:2]) == expected


@pytest.mark.parametrize(
    "muted,solo_a,solo_b,expected",
    [
        (False, False, False, (16000, -6000)),
        (True, False, False, (0, -6000)),
        (False, True, False, (16000, 0)),
        (False, False, True, (0, -6000)),
        (True, True, False, (0, 0)),
    ],
)
def test_mute_and_active_solo_precedence(routed_project, muted, solo_a, solo_b, expected):
    root, request = routed_project
    a, b = request["plan"]["routing"]["tracks"]
    a.update(muted=muted, soloed=solo_a)
    b["soloed"] = solo_b
    pcm = rendered_pcm(root, request)
    assert (pcm[0], pcm[7000]) == expected


def test_multiple_cues_can_share_one_track(routed_project):
    root, request = routed_project
    request["plan"]["routing"]["tracks"].pop()
    request["cue_tracks"][1]["track_id"] = "voice-a"
    pcm = rendered_pcm(root, request)
    assert (pcm[0], pcm[7000]) == (16000, -12000)


def add_bed(root, request, value=1000):
    data = pcm_to_wav(array("h", [value] * 13230), sample_rate_hz=22050)
    (root / "bed.wav").write_bytes(data)
    request["bed"] = {"path": "bed.wav", "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    request["plan"]["beds"] = ["bed.wav"]


def test_bus_gain_follows_saturated_clip_and_bed_sum(routed_project):
    root, request = routed_project
    for clip in request["clips"]:
        clip["stem_id"] = "ambience"
    for track in request["plan"]["routing"]["tracks"]:
        track.update(destination_bus_id="ambience", gain_db=0)
    request["plan"]["routing"]["buses"][1]["gain_db"] = -6.020599913279624
    add_bed(root, request, 30000)
    pcm = rendered_pcm(root, request)
    assert pcm[0] == 16384 and pcm[-1] == 15000


@pytest.mark.parametrize("optional_bed", [False, True])
def test_bed_cue_is_not_implicitly_rendered_twice(routed_project, optional_bed):
    root, request = routed_project
    request["plan"]["timeline"]["cues"][0]["kind"] = "bed"
    request["transitions"] = []  # Existing crossfades require two LINE cues.
    if optional_bed:
        add_bed(root, request)
    assert rendered_pcm(root, request)[0] == (17000 if optional_bed else 16000)


def test_optional_bed_needs_no_track_binding(routed_project):
    root, request = routed_project
    for cue in request["plan"]["timeline"]["cues"]:
        cue.update(kind="silence", source_ref="silence")
    request.update(clips=[], cue_tracks=[], transitions=[])
    request["plan"]["routing"]["tracks"] = []
    add_bed(root, request)
    assert set(rendered_pcm(root, request)) == {1000}
