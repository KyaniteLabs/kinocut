"""General bus sidechains must alter retained bus PCM and report measured recovery."""

import json
import zipfile
import pytest

from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, add_bed  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project  # noqa: F401


@pytest.fixture
def sidechain_project(routed_project):  # noqa: F811
    root, request = routed_project
    add_bed(root, request, value=10000)
    request["plan"]["routing"]["sidechains"] = [
        {
            "source_bus_id": "dialogue",
            "target_bus_id": "ambience",
            "attenuation_db": 9,
            "attack_ms": 80,
            "release_ms": 100,
            "recovery_ms": 100,
        }
    ]
    return root, request


def test_bus_sidechain_ducks_complete_target_stem(sidechain_project):
    root, request = sidechain_project
    assert load_mix_request(request).plan.routing.sidechains
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, _, _ = decode_pcm_wav(archive.read("stems/ambience.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert pcm[0] == 9996 and pcm[1763] == 3548 and pcm[11024] == 10000
    assert result["sidechain_count"] == 1
    assert receipt["bus_sidechain_measurements"][0]["summary"]["recovery_status"] == "pass"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_result_metadata_failure_cannot_commit_output(sidechain_project, monkeypatch, asynchronous):
    import asyncio
    from kinocut_sound.public import mix_job
    from kinocut_sound.mix._errors import MixError

    root, request = sidechain_project

    def invalid_result(*args):
        raise TypeError("invalid result metadata")

    monkeypatch.setattr(mix_job, "_result", invalid_result)
    with pytest.raises(MixError):
        if asynchronous:
            asyncio.run(mix_job.render_mix_request_async(request, str(root)))
        else:
            mix_job.render_mix_request(request, str(root))
    assert not (root / request["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))


def inspect(root, request, stem="ambience"):
    result = _render(root, request)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return decode_pcm_wav(archive.read(f"stems/{stem}.wav"))[0], json.loads(archive.read("receipt.json"))


def test_detector_observes_source_bus_fader(sidechain_project):
    root, request = sidechain_project
    request["plan"]["routing"]["buses"][0]["gain_db"] = -60
    pcm, receipt = inspect(root, request)
    assert pcm[0] == 10000
    assert receipt["bus_sidechain_measurements"][0]["summary"]["active_frames"] == 0


def test_send_returns_feed_final_detector(sidechain_project):
    from tests.test_sound_sends_public import add_send

    root, request = sidechain_project
    add_send(request, source="dialogue", target="sfx")
    request["plan"]["routing"]["sidechains"][0]["source_bus_id"] = "sfx"
    pcm, _ = inspect(root, request)
    assert pcm[0] == 9996 and pcm[1763] == 3548


def test_sends_retain_pre_sidechain_values(sidechain_project):
    from tests.test_sound_sends_public import add_send

    root, request = sidechain_project
    add_send(request, source="ambience", target="sfx")
    pcm, _ = inspect(root, request)
    assert pcm[1763] == 3548
    with zipfile.ZipFile(root / request["output_path"]) as archive:
        assert decode_pcm_wav(archive.read("stems/sfx.wav"))[0][1763] == 5000


def test_layer_and_bus_ducking_are_separate_stages(ducked_project):  # noqa: F811
    root, request = ducked_project
    request["plan"]["routing"]["sidechains"] = [
        {
            "source_bus_id": "dialogue",
            "target_bus_id": "ambience",
            "attenuation_db": 6.020599913279624,
            "attack_ms": 1,
            "release_ms": 1,
            "recovery_ms": 1,
        }
    ]
    pcm, receipt = inspect(root, request)
    assert pcm[1763] == 1774
    assert "ducking" in receipt["layers"] and len(receipt["bus_sidechain_measurements"]) == 1


def test_sidechain_parent_cancellation_before_publish_cleans_and_resumes(sidechain_project, monkeypatch):
    import asyncio
    from kinocut_sound.public import mix_job
    from kinocut_sound.mix._errors import MixError

    root, request = sidechain_project
    original = mix_job._verify_stage

    def cancel_after_verification(*args):
        result = original(*args)
        asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
        return result

    async def scenario():
        monkeypatch.setattr(mix_job, "_verify_stage", cancel_after_verification)
        task = asyncio.create_task(mix_job.render_mix_request_async(request, str(root)))
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 15)
        assert not (root / request["output_path"]).exists()
        assert not list(root.glob(".kinocut-mix-*"))
        monkeypatch.setattr(mix_job, "_verify_stage", original)
        result = await mix_job.render_mix_request_async(request, str(root))
        before = (root / request["output_path"]).read_bytes()
        with pytest.raises(MixError) as failure:
            await mix_job.render_mix_request_async(request, str(root))
        assert failure.value.code == "mix_output_conflict"
        assert (root / request["output_path"]).read_bytes() == before
        return result

    assert asyncio.run(asyncio.wait_for(scenario(), 30))["ok"]


@pytest.mark.parametrize("with_send", [False, True])
def test_automation_composes_with_final_sidechains_and_optional_send(sidechain_project, with_send):
    from tests.test_sound_sends_public import add_send

    root, request = sidechain_project
    request["plan"]["routing"]["envelopes"] = [
        {
            "target_track_id": "voice-a",
            "parameter": "gain_db",
            "points": [{"time_seconds": 0, "value": -60}, {"time_seconds": 0.1, "value": 0}],
        }
    ]
    if with_send:
        add_send(request, source="dialogue", target="sfx")
        request["plan"]["routing"]["sidechains"][0]["source_bus_id"] = "sfx"
    pcm, receipt = inspect(root, request)
    assert pcm[0] == 10000 and pcm[3000] < 10000
    assert "automation" in receipt["routing"] and "sidechains" in receipt["routing"]
    assert ("sends" in receipt["routing"]) is with_send
    assert receipt["routing"]["inner_routing_algorithm"] == (
        "sent_pcm16_ties_even_v1" if with_send else "automated_pcm16_ties_even_v1"
    )
