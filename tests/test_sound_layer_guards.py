"""Fail-closed layer admission and independent pre-publication evidence."""

import copy
import json
import os
import zipfile

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401


@pytest.mark.parametrize(
    "field,value",
    [
        ("muted", 1),
        ("muted", "false"),
        ("soloed", 0),
        ("gain_db", True),
        ("gain_db", "1"),
        ("gain_db", float("nan")),
        ("gain_db", float("inf")),
    ],
)
def test_raw_layer_values_are_strict(layered_project, field, value):  # noqa: F811
    _, request = layered_project
    request["layer_assets"][0]["layer"][field] = value
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "order", "ref", "ducking", "count", "fraction", "bool"])
def test_bad_layer_contracts_fail(layered_project, mutation):  # noqa: F811
    _, request = layered_project
    item = request["layer_assets"][0]
    if mutation == "missing":
        request["layer_assets"] = []
    elif mutation == "duplicate":
        request["layer_assets"].append(copy.deepcopy(item))
    elif mutation == "order":
        request["plan"]["layers"] = ["other"]
    elif mutation == "ref":
        second = copy.deepcopy(item)
        second["layer"]["layer_id"] = "rain"
        second["source"]["path"] = "other.wav"
        request["layer_assets"].append(second)
        request["plan"]["layers"].append("rain")
    elif mutation == "ducking":
        request["layer_ducking"] = {"source_bus_id": "dialogue", "target_bus_id": "ambience"}
    elif mutation == "count":
        request["layer_assets"] = [item] * 65
    else:
        item.update(fill_mode="loop", crossfade_frames=1.5 if mutation == "fraction" else True)
    with pytest.raises(MixError):
        load_mix_request(request)


def test_mutated_typed_request_is_revalidated(layered_project):  # noqa: F811
    _, request = layered_project
    parsed = load_mix_request(request)
    invalid_layer = parsed.layer_assets[0].layer.model_copy(update={"gain_db": True})
    invalid_asset = parsed.layer_assets[0].model_copy(update={"layer": invalid_layer})
    mutated = parsed.model_copy(update={"layer_assets": (invalid_asset,)})
    with pytest.raises(MixError):
        load_mix_request(mutated)


@pytest.mark.parametrize("failure", ["hash", "missing", "symlink", "fifo", "format", "empty"])
def test_inactive_layers_still_require_valid_source(layered_project, failure):  # noqa: F811
    from array import array
    import hashlib
    from kinocut_sound.mix._wav import pcm_to_wav
    from kinocut_sound.public.mix_job import render_mix_request

    root, request = layered_project
    item = request["layer_assets"][0]
    item["layer"]["muted"] = True
    path = root / "layer.wav"
    if failure == "hash":
        item["source"]["sha256"] = "sha256:" + "0" * 64
    elif failure in ("missing", "symlink", "fifo"):
        path.unlink()
        if failure == "symlink":
            path.symlink_to(root / "a.wav")
        elif failure == "fifo":
            os.mkfifo(path)
    else:
        data = pcm_to_wav(
            array("h", [1, 2] if failure == "format" else []),
            sample_rate_hz=44100 if failure == "format" else 22050,
        )
        path.write_bytes(data)
        item["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    with pytest.raises(MixError):
        render_mix_request(request, str(root))
    assert not (root / request["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))


@pytest.mark.parametrize("change", ["frames", "flags", "null", "shape_boolean"])
def test_forged_layer_stage_cannot_publish(layered_project, monkeypatch, change):  # noqa: F811
    from kinocut_sound.public import mix_job
    from kinocut_sound.public.mix_layer_receipt import layer_evidence

    root, payload = layered_project
    original = mix_job._run_worker

    def tamper(request, root_fd, stage_fd):
        status = original(request, root_fd, stage_fd)
        with os.fdopen(os.dup(stage_fd), "r+b") as stream:
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            receipt = json.loads(members["receipt.json"])
            if change == "frames":
                receipt["layers"] = layer_evidence(request, (5,))  # Internally consistent lie.
            elif change == "flags":
                receipt["layers"]["entries"][0]["audible"] = False
            elif change == "shape_boolean":
                receipt["layers"]["entries"][0]["fill"]["copies"] = True
            else:
                receipt["layers"] = None
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


def test_changed_source_after_worker_is_rejected(layered_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_job

    root, payload = layered_project
    original = mix_job._run_worker

    def mutate(request, root_fd, stage_fd):
        status = original(request, root_fd, stage_fd)
        (root / "layer.wav").write_bytes(b"changed")
        return status

    monkeypatch.setattr(mix_job, "_run_worker", mutate)
    with pytest.raises(MixError):
        mix_job.render_mix_request(payload, str(root))
    assert not (root / payload["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_layer_memory_and_receipt_bounds(layered_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_request, mix_layer_receipt, mix_routing_receipt

    _, payload = layered_project
    request = load_mix_request(payload)
    monkeypatch.setattr(mix_request, "MAX_MIX_MEMORY_BYTES", 1)
    with pytest.raises(MixError):
        mix_request.check_mix_resources(request, 0)
    monkeypatch.setattr(mix_layer_receipt, "MAX_MIX_LAYER_RECEIPT_BYTES", 10)
    with pytest.raises(MixError):
        mix_layer_receipt.layer_evidence(request, (4,))
    monkeypatch.setattr(mix_layer_receipt, "MAX_MIX_LAYER_RECEIPT_BYTES", 10000)
    layers = mix_layer_receipt.layer_evidence(request, (4,))
    monkeypatch.setattr(mix_routing_receipt, "MAX_MIX_RECEIPT_BYTES", 1000)
    with pytest.raises(MixError):
        mix_routing_receipt.routed_receipt_bytes({"sample_count": 13230}, request, layers)


def test_layer_bytes_share_clip_input_budget(layered_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_worker
    from kinocut_sound.public.mix_files import open_root

    root, payload = layered_project
    total = sum((root / clip["path"]).stat().st_size for clip in payload["clips"])
    total += (root / "layer.wav").stat().st_size
    monkeypatch.setattr(mix_worker, "MAX_MIX_INPUT_BYTES", total - 1)
    with open_root(str(root)) as root_fd, pytest.raises(MixError) as failure:
        mix_worker._sources(load_mix_request(payload), root_fd)
    assert failure.value.code == "mix_over_limit"


def test_zero_rounded_target_fails_admission(layered_project):  # noqa: F811
    _, request = layered_project
    request.update(clips=[], cue_tracks=[], transitions=[])
    request["plan"]["routing"]["tracks"] = []
    timeline = request["plan"]["timeline"]
    cue = timeline["cues"][-1]
    cue.update(start_seconds=0, duration_seconds=0.00000001)
    timeline.update(cues=[cue], tail_seconds=0)
    with pytest.raises(MixError) as failure:
        load_mix_request(request)
    assert "positive target frame" in str(failure.value)


def test_v2_mutated_gain_is_not_laundered_by_json_serialization(routed_project):  # noqa: F811
    _, payload = routed_project
    parsed = load_mix_request(payload)
    track = parsed.plan.routing.tracks[0].model_copy(update={"gain_db": True})
    routing = parsed.plan.routing.model_copy(update={"tracks": (track, *parsed.plan.routing.tracks[1:])})
    plan = parsed.plan.model_copy(update={"routing": routing})
    with pytest.raises(MixError):
        load_mix_request(parsed.model_copy(update={"plan": plan}))


def test_invalid_layer_shape_fails_before_renderer(layered_project, monkeypatch):  # noqa: F811
    import hashlib
    from array import array
    from kinocut_sound.mix._wav import pcm_to_wav
    from kinocut_sound.public import mix_worker
    from kinocut_sound.public.mix_files import open_root, open_parent, staged_output

    root, request = layered_project
    data = pcm_to_wav(array("h", [1, 2]), sample_rate_hz=44100)
    (root / "layer.wav").write_bytes(data)
    request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()

    def forbidden_render(*args, **kwargs):
        pytest.fail("renderer must not run before layer source admission")

    monkeypatch.setattr(mix_worker.MixRenderer, "render", forbidden_render)
    with (
        open_root(str(root)) as root_fd,
        open_parent(root_fd, request["output_path"]) as (parent, _),
        staged_output(parent) as (stage, _),
        pytest.raises(MixError),
    ):
        mix_worker.render_to_stage(request, root_fd, stage)
