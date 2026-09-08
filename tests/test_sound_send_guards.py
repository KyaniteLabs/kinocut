"""Send graph, snapshot memory and combined feature bounds are preflight gates."""

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
from tests.test_sound_sends_public import sent_project  # noqa: F401
from tests.test_sound_sends_public import add_send
from tests.test_sound_layers_public import layered_project
from tests.test_sound_layer_ducking_public import ducked_project
from tests.test_sound_automation_public import automated_project


@pytest.mark.parametrize(
    "field,value", [("post_fader", 1), ("post_fader", "false"), ("gain_db", True), ("gain_db", "0")]
)
def test_raw_send_flags_and_gain_are_strict(sent_project, field, value):  # noqa: F811
    _, request = sent_project
    request["plan"]["routing"]["sends"][0][field] = value
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_send_count_and_typed_mutation_fail(sent_project):  # noqa: F811
    _, request = sent_project
    parsed = load_mix_request(request)
    changed = parsed.plan.routing.sends[0].model_copy(update={"post_fader": "false"})
    routing = parsed.plan.routing.model_copy(update={"sends": (changed,)})
    with pytest.raises(MixError):
        load_mix_request(parsed.model_copy(update={"plan": parsed.plan.model_copy(update={"routing": routing})}))
    request["plan"]["routing"]["sends"] *= 65
    with pytest.raises(MixError) as failure:
        load_mix_request(request)
    assert failure.value.code == "mix_over_limit"


@pytest.mark.parametrize("pre,limit", [(False, 10072224), (True, 10098684)])
@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_exact_snapshot_memory_boundary(sent_project, monkeypatch, pre, limit, margin):  # noqa: F811
    from kinocut_sound.public import mix_request

    _, request = sent_project
    request["plan"]["routing"]["sends"][0]["post_fader"] = not pre
    parsed = load_mix_request(request)
    monkeypatch.setattr(mix_request, "MAX_MIX_MEMORY_BYTES", limit + margin)
    if margin < 0:
        with pytest.raises(MixError):
            mix_request.check_mix_resources(parsed, 0)
    else:
        mix_request.check_mix_resources(parsed, 0)


def test_combined_limit_precedes_renderer(sent_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_worker, mix_send_request
    from kinocut_sound.public.mix_files import open_root, open_parent, staged_output

    root, request = sent_project
    monkeypatch.setattr(mix_send_request, "MAX_MIX_ROUTED_FEATURE_WORK_UNITS", 1)

    def forbidden(*args, **kwargs):
        pytest.fail("combined work must be rejected before rendering")

    monkeypatch.setattr(mix_worker.MixRenderer, "render", forbidden)
    with (
        open_root(str(root)) as root_fd,
        open_parent(root_fd, request["output_path"]) as (parent, _),
        staged_output(parent) as (stage, _),
        pytest.raises(MixError) as failure,
    ):
        mix_worker.render_to_stage(request, root_fd, stage)
    assert failure.value.code == "mix_over_limit"


@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_exact_send_work_boundary(sent_project, monkeypatch, margin):  # noqa: F811
    from kinocut_sound.mix import bus_sends

    _, request = sent_project
    monkeypatch.setattr(bus_sends, "MAX_MIX_SEND_WORK_UNITS", 66154 + margin)
    if margin < 0:
        with pytest.raises(MixError):
            load_mix_request(request)
    else:
        assert compile_routing(load_mix_request(request)).graph.work_units == 66154


def test_zero_rounded_send_timeline_is_rejected(sent_project):  # noqa: F811
    _, request = sent_project
    request.update(clips=[], cue_tracks=[], transitions=[])
    request["plan"]["routing"]["tracks"] = []
    timeline = request["plan"]["timeline"]
    cue = copy.deepcopy(timeline["cues"][-1])
    cue.update(start_seconds=0, duration_seconds=0.00000001)
    timeline.update(cues=[cue], tail_seconds=0)
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.mark.parametrize("change", ["tap", "order", "frame", "missing"])
def test_forged_send_receipt_cannot_publish(sent_project, monkeypatch, change):  # noqa: F811
    from kinocut_sound.public import mix_job

    root, request = sent_project
    original = mix_job._run_worker

    def tamper(parsed, root_fd, stage_fd):
        status = original(parsed, root_fd, stage_fd)
        with os.fdopen(os.dup(stage_fd), "r+b") as stream:
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            receipt = json.loads(members["receipt.json"])
            graph = receipt["routing"]["sends"]
            if change == "tap":
                graph["sends"][0]["input_tap"] = "pre_fader"
            elif change == "order":
                graph["topological_order"].reverse()
            elif change == "frame":
                graph["frame_count"] = True
            else:
                del receipt["routing"]["sends"]
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


@pytest.mark.parametrize("kind,expected", [("automation", 79392), ("layer", 92622), ("ducking", 145534)])
@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_combined_feature_work_boundaries(routed_project, monkeypatch, kind, expected, margin):  # noqa: F811
    from kinocut_sound.public import mix_send_request
    from kinocut_sound.mix.source_windows import SourceWindow

    windows, frames = (), ()
    if kind == "automation":
        _, request = automated_project.__wrapped__(routed_project)
        windows = (SourceWindow("a", 0, 6615, 6615, 22050),)
    elif kind == "layer":
        _, request = layered_project.__wrapped__(routed_project)
        frames = (4,)
    else:
        _, request = ducked_project.__wrapped__(layered_project.__wrapped__(routed_project))
        frames = (13230,)
    add_send(request)
    parsed = load_mix_request(request)
    routing = compile_routing(parsed)
    monkeypatch.setattr(mix_send_request, "MAX_MIX_ROUTED_FEATURE_WORK_UNITS", expected + margin)
    if margin < 0:
        with pytest.raises(MixError):
            mix_send_request.check_routed_feature_work(parsed, routing, windows, frames)
    else:
        assert mix_send_request.check_routed_feature_work(parsed, routing, windows, frames) == expected
