"""Final sidechain admission and measurement evidence must fail closed."""

import copy
import json
import os
import zipfile
import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_bus_sidechains_public import sidechain_project  # noqa: F401


@pytest.mark.parametrize("kind", ["self", "unknown", "duplicate", "count", "boolean", "string", "recovery"])
def test_invalid_sidechain_contracts_fail(sidechain_project, kind):  # noqa: F811
    _, request = sidechain_project
    rows = request["plan"]["routing"]["sidechains"]
    if kind == "self":
        rows[0]["target_bus_id"] = "dialogue"
    elif kind == "unknown":
        rows[0]["source_bus_id"] = "missing"
    elif kind == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif kind == "count":
        request["plan"]["routing"]["sidechains"] = rows * 65
    elif kind == "boolean":
        rows[0]["attack_ms"] = True
    elif kind == "string":
        rows[0]["attack_ms"] = "80"
    else:
        rows[0]["recovery_ms"] = 1
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_sidechain_memory_boundary(sidechain_project, monkeypatch, margin):  # noqa: F811
    from kinocut_sound.public import mix_request

    _, payload = sidechain_project
    request = load_mix_request(payload)
    monkeypatch.setattr(mix_request, "MAX_MIX_MEMORY_BYTES", 10098684 + margin)
    if margin < 0:
        with pytest.raises(MixError):
            mix_request.check_mix_resources(request, 0)
    else:
        mix_request.check_mix_resources(request, 0)


@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_sidechain_work_boundary(sidechain_project, monkeypatch, margin):  # noqa: F811
    from kinocut_sound.mix import bus_sidechains
    from kinocut_sound.public.mix_request_v2 import compile_routing

    _, request = sidechain_project
    monkeypatch.setattr(bus_sidechains, "MAX_MIX_SIDECHAIN_WORK_UNITS", 39692 + margin)
    if margin < 0:
        with pytest.raises(MixError):
            load_mix_request(request)
    else:
        assert compile_routing(load_mix_request(request)).sidechain_processor.work_units == 39692


def test_combined_sidechain_cap_precedes_renderer(sidechain_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_worker, mix_send_request
    from kinocut_sound.public.mix_files import open_root, open_parent, staged_output

    root, request = sidechain_project
    monkeypatch.setattr(mix_send_request, "MAX_MIX_ROUTED_FEATURE_WORK_UNITS", 1)

    def forbidden(*args, **kwargs):
        pytest.fail("combined sidechain budget must precede renderer")

    monkeypatch.setattr(mix_worker.MixRenderer, "render", forbidden)
    with (
        open_root(str(root)) as root_fd,
        open_parent(root_fd, request["output_path"]) as (parent, _),
        staged_output(parent) as (stage, _),
        pytest.raises(MixError) as failure,
    ):
        mix_worker.render_to_stage(request, root_fd, stage)
    assert failure.value.code == "mix_over_limit"


@pytest.mark.parametrize("kind", ["missing", "identity", "boolean", "scope"])
def test_forged_sidechain_measurements_cannot_publish(sidechain_project, monkeypatch, kind):  # noqa: F811
    from kinocut_sound.public import mix_job

    root, request = sidechain_project
    original = mix_job._run_worker

    def tamper(parsed, root_fd, stage_fd):
        status = original(parsed, root_fd, stage_fd)
        with os.fdopen(os.dup(stage_fd), "r+b") as stream:
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            receipt = json.loads(members["receipt.json"])
            if kind == "missing":
                del receipt["bus_sidechain_measurements"]
            elif kind == "identity":
                receipt["bus_sidechain_measurements"][0]["source_bus_id"] = "sfx"
            elif kind == "boolean":
                receipt["bus_sidechain_measurements"][0]["summary"]["active_frames"] = True
            else:
                receipt["routing"]["sidechains"]["controllers"][0]["source_position"] = "pre_fader"
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
