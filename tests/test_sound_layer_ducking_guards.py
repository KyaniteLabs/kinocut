"""Duck contracts and worker summaries must fail closed on malformed claims."""

import copy
import json
import os
import zipfile

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.public.mix_layer_ducking import verify_ducking_evidence
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project, inspect_ducking  # noqa: F401


@pytest.mark.parametrize("kind", ["target", "source", "self", "empty", "recovery", "bool", "sidechain"])
def test_invalid_ducking_intent_fails(ducked_project, kind):  # noqa: F811
    _, request = ducked_project
    policy = request["layer_ducking"]
    if kind == "target":
        policy["target_bus_id"] = "sfx"
    elif kind == "source":
        policy["source_bus_id"] = "missing"
    elif kind == "self":
        policy["source_bus_id"] = "ambience"
    elif kind == "empty":
        request["layer_assets"] = []
        request["plan"]["layers"] = []
    elif kind == "recovery":
        policy["recovery_ms"] = 1
    elif kind == "bool":
        policy["attack_ms"] = True
    else:
        request["plan"]["routing"]["sidechains"] = [
            {
                **policy,
                "attenuation_db": 9,
                "attack_ms": 80,
            }
        ]
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("active_frames", True),
        ("active_frames", -1),
        ("activity_runs", 8000),
        ("minimum_gain", float("nan")),
        ("final_gain", 0.1),
        ("final_gain", True),
        ("completed_releases", 100000),
        ("max_release_frames", 1),
        ("recovery_status", "not_exercised"),
        ("truncated_recovery", True),
        ("truncated_release_frames", 100000),
    ],
)
def test_malformed_summary_is_rejected(ducked_project, field, value):  # noqa: F811
    root, request = ducked_project
    _, receipt = inspect_ducking(root, request)
    actual = copy.deepcopy(receipt["layers"]["ducking"])
    actual["summary"][field] = value
    with pytest.raises(MixError):
        verify_ducking_evidence(load_mix_request(request), actual)


def test_changed_ducking_stage_metadata_cannot_publish(ducked_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_job

    root, request = ducked_project
    original = mix_job._run_worker

    def tamper(parsed, root_fd, stage_fd):
        status = original(parsed, root_fd, stage_fd)
        with os.fdopen(os.dup(stage_fd), "r+b") as stream:
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            receipt = json.loads(members["receipt.json"])
            receipt["layers"]["ducking"]["attack_frames"] = True
            members["receipt.json"] = json.dumps(receipt).encode()
            stream.seek(0)
            stream.truncate()
            with zipfile.ZipFile(stream, "w") as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
        return status

    monkeypatch.setattr(mix_job, "_run_worker", tamper)
    with pytest.raises(MixError) as failure:
        mix_job.render_mix_request(request, str(root))
    assert failure.value.code == "mix_worker_failed"
    assert not (root / request["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))
