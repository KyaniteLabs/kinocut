"""Automation rejects excess work and independently checks selected-source evidence."""

import copy
import json
import os
import zipfile

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.public.mix_request_v2 import compile_routing
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_automation_public import automated_project  # noqa: F401


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "boolean", "collision", "outside", "count", "points"])
def test_invalid_automation_requests_fail(automated_project, kind):  # noqa: F811
    _, request = automated_project
    rows = request["plan"]["routing"]["envelopes"]
    if kind == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif kind == "unknown":
        rows[0]["target_track_id"] = "missing"
    elif kind == "boolean":
        rows[0]["points"][0]["value"] = True
    elif kind == "collision":
        rows[0]["points"][1]["time_seconds"] = 0.000001
    elif kind == "outside":
        rows[0]["points"][1]["time_seconds"] = 1
    elif kind == "count":
        request["plan"]["routing"]["envelopes"] = rows * 513
    else:
        rows[0]["points"] = [{"time_seconds": 0, "value": 0}] * 4097
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_metadata_allowance_has_exact_admission_boundary(automated_project, monkeypatch, margin):  # noqa: F811
    from kinocut_sound.public import mix_request

    _, payload = automated_project
    request = load_mix_request(payload)
    monkeypatch.setattr(mix_request, "MAX_MIX_MEMORY_BYTES", 42578080 + margin)
    if margin < 0:
        with pytest.raises(MixError):
            mix_request.check_mix_resources(request, 0)
    else:
        mix_request.check_mix_resources(request, 0)


def test_work_cap_precedes_any_source_transform(automated_project, monkeypatch):  # noqa: F811
    from kinocut_sound.mix import automated_routing

    root, request = automated_project
    routing = compile_routing(load_mix_request(request))
    monkeypatch.setattr(automated_routing, "MAX_MIX_AUTOMATION_WORK_UNITS", 1)

    def forbidden(*args):
        pytest.fail("over-budget automation must not transform PCM")

    monkeypatch.setattr(routing, "_process", forbidden)
    with pytest.raises(MixError) as failure:
        routing.process_sources(
            {item["cue_id"]: (root / item["path"]).read_bytes() for item in request["clips"]}, 22050
        )
    assert failure.value.code == "mix_over_limit"


@pytest.mark.parametrize("kind", ["window", "duplicate", "routing"])
def test_forged_automation_stage_cannot_publish(automated_project, monkeypatch, kind):  # noqa: F811
    from kinocut_sound.public import mix_job

    root, payload = automated_project
    original = mix_job._run_worker

    def tamper(request, root_fd, stage_fd):
        status = original(request, root_fd, stage_fd)
        with os.fdopen(os.dup(stage_fd), "r+b") as stream:
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            receipt = json.loads(members["receipt.json"])
            if kind == "window":
                receipt["source_windows"][0]["out_sample"] += 1
                receipt["source_windows"][0]["sample_count"] += 1
            elif kind == "duplicate":
                receipt["source_windows"][1] = receipt["source_windows"][0]
            else:
                receipt["routing"]["automation"]["envelopes"][0]["points"][1]["frame"] += 1
            members["receipt.json"] = json.dumps(receipt).encode()
            stream.seek(0)
            stream.truncate()
            with zipfile.ZipFile(stream, "w") as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
        return status

    monkeypatch.setattr(mix_job, "_run_worker", tamper)
    with pytest.raises(MixError) as failure:
        mix_job.render_mix_request(payload, str(root))
    assert failure.value.code == "mix_worker_failed"
    assert not (root / payload["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_automated_source_changed_after_worker_is_rejected(automated_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_job

    root, payload = automated_project
    original = mix_job._run_worker

    def mutate(request, root_fd, stage_fd):
        status = original(request, root_fd, stage_fd)
        (root / "a.wav").write_bytes(b"changed")
        return status

    monkeypatch.setattr(mix_job, "_run_worker", mutate)
    with pytest.raises(MixError):
        mix_job.render_mix_request(payload, str(root))
    assert not (root / payload["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_typed_point_mutation_is_revalidated(automated_project):  # noqa: F811
    _, payload = automated_project
    request = load_mix_request(payload)
    envelope = request.plan.routing.envelopes[0]
    point = envelope.points[0].model_copy(update={"value": True})
    changed = envelope.model_copy(update={"points": (point, *envelope.points[1:])})
    routing = request.plan.routing.model_copy(update={"envelopes": (changed,)})
    with pytest.raises(MixError):
        load_mix_request(request.model_copy(update={"plan": request.plan.model_copy(update={"routing": routing})}))


def test_total_point_limit_precedes_duplicate_parameter_validation(automated_project):  # noqa: F811
    _, request = automated_project
    item = request["plan"]["routing"]["envelopes"][0]
    item["points"] = [{"time_seconds": i / 22050, "value": 0} for i in range(4096)]
    third = copy.deepcopy(item)
    third["points"] = third["points"][:1]
    request["plan"]["routing"]["envelopes"] = [item, copy.deepcopy(item), third]
    with pytest.raises(MixError) as failure:
        load_mix_request(request)
    assert failure.value.code == "mix_over_limit"


def test_automation_receipt_is_bounded_before_io(automated_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_request

    _, request = automated_project
    monkeypatch.setattr(mix_request, "MAX_MIX_ROUTING_RECEIPT_BYTES", 1)
    with pytest.raises(MixError) as failure:
        load_mix_request(request)
    assert failure.value.code == "mix_over_limit"
