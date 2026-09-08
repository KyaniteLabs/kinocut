"""Reject ambiguous intent, coerced controls and oversized routed evidence."""

import copy

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public import mix_request, mix_request_v2
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.public.mix_request_v2 import SoundMixRequestV2
from kinocut_sound.public.mix_routing_receipt import routed_receipt_bytes, bounded_json, verify_routing_receipt
from kinocut_sound.sound_plan import SoundPlan
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown", "unused", "silent", "bed_missing", "bus"])
def test_binding_contract_rejects_ambiguous_routes(routed_project, kind):  # noqa: F811
    _, request = routed_project
    if kind == "missing":
        request["cue_tracks"].pop()
    elif kind == "duplicate":
        request["cue_tracks"].append(request["cue_tracks"][0].copy())
    elif kind == "unknown":
        request["cue_tracks"][0]["track_id"] = "unknown"
    elif kind == "unused":
        track = request["plan"]["routing"]["tracks"][0].copy()
        track["track_id"] = "unused"
        request["plan"]["routing"]["tracks"].append(track)
    elif kind == "silent":
        request["cue_tracks"].append({"cue_id": "silence", "track_id": "voice-a"})
    elif kind == "bed_missing":
        request["plan"]["timeline"]["cues"][0]["kind"] = "bed"
        request["cue_tracks"].pop(0)
    else:
        request["plan"]["routing"]["tracks"][0]["destination_bus_id"] = "sfx"
    with pytest.raises(MixError):
        load_mix_request(request)


@pytest.mark.parametrize(
    "key,value",
    [
        ("muted", 1),
        ("soloed", "false"),
        ("muted", None),
        ("gain_db", True),
        ("gain_db", "1"),
        ("pan_position", False),
        ("gain_db", float("nan")),
        ("pan_position", float("inf")),
    ],
)
def test_v2_raw_controls_are_strict(routed_project, key, value):  # noqa: F811
    _, request = routed_project
    request["plan"]["routing"]["tracks"][0][key] = value
    with pytest.raises(MixError):
        load_mix_request(request)


def test_existing_typed_state_is_accepted_without_claiming_raw_history(routed_project):  # noqa: F811
    _, request = routed_project
    request["plan"]["routing"]["tracks"][0]["muted"] = "false"
    plan = SoundPlan.model_validate(request["plan"])
    model = SoundMixRequestV2.model_validate({**request, "plan": plan})
    assert load_mix_request(model).plan.routing.tracks[0].muted is False


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
def test_mutated_typed_state_is_revalidated(routed_project):  # noqa: F811
    _, request = routed_project
    model = load_mix_request(request)
    tracks = model.plan.routing.tracks
    changed = tracks[0].model_copy(update={"muted": "false"})
    routing = model.plan.routing.model_copy(update={"tracks": (changed, *tracks[1:])})
    model = model.model_copy(update={"plan": model.plan.model_copy(update={"routing": routing})})
    with pytest.raises(MixError):
        load_mix_request(model)


@pytest.mark.parametrize("kind", ["send_cycle", "envelope", "bus_pan", "mono_pan", "latency"])
def test_unimplemented_routing_intent_is_not_discarded(routed_project, kind):  # noqa: F811
    _, request = routed_project
    routing = request["plan"]["routing"]
    if kind == "send_cycle":
        routing["sends"] = [
            {"send_id": "send", "source_bus_id": "dialogue", "destination_bus_id": "ambience"},
            {"send_id": "return", "source_bus_id": "ambience", "destination_bus_id": "dialogue"},
        ]
    elif kind == "envelope":
        routing["envelopes"] = [
            {"target_track_id": "voice-a", "parameter": "cutoff_hz", "points": [{"time_seconds": 0, "value": 0}]}
        ]
    elif kind == "bus_pan":
        routing["buses"][0]["pan_law"] = "constant_power"
    elif kind == "mono_pan":
        routing["tracks"][0]["pan_position"] = 1
    else:
        routing["latency"] = {"policy": "sample_accurate", "residual_samples": 1}
    with pytest.raises(MixError) as failure:
        load_mix_request(request)
    assert failure.value.code == "mix_unsupported_intent"


@pytest.mark.parametrize("name", ["MAX_MIX_ROUTING_TRACKS", "MAX_MIX_ROUTING_BUSES", "MAX_MIX_ROUTING_BINDINGS"])
def test_route_cardinality_fails_at_admission(routed_project, monkeypatch, name):  # noqa: F811
    _, request = routed_project
    monkeypatch.setattr(mix_request_v2, name, 1)
    with pytest.raises(MixError) as failure:
        load_mix_request(request)
    assert failure.value.code == "mix_over_limit"


def test_v2_receipt_working_memory_is_admitted(routed_project, monkeypatch):  # noqa: F811
    _, request = routed_project
    monkeypatch.setattr(mix_request, "MAX_MIX_MEMORY_BYTES", 2000000)
    with pytest.raises(MixError) as failure:
        load_mix_request(request)
    assert failure.value.code == "mix_over_limit"
    old = copy.deepcopy(request)
    old["schema_version"] = 1
    del old["cue_tracks"]
    old["plan"]["routing"] = {}
    load_mix_request(old)


def test_whole_receipt_limit_applies_beyond_routing(routed_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_routing_receipt as module

    _, request = routed_project
    parsed = load_mix_request(request)
    monkeypatch.setattr(module, "MAX_MIX_ROUTING_RECEIPT_BYTES", 10000)
    monkeypatch.setattr(module, "MAX_MIX_RECEIPT_BYTES", 12000)
    receipt = {"sample_count": 13230, "sources": [{"path": "x" * 11500}]}
    with pytest.raises(MixError) as failure:
        routed_receipt_bytes(receipt, parsed)
    assert failure.value.code == "mix_over_limit"


def test_routing_limit_and_exact_json_boundary(routed_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_routing_receipt as module

    _, request = routed_project
    monkeypatch.setattr(module, "MAX_MIX_ROUTING_RECEIPT_BYTES", 10)
    with pytest.raises(MixError):
        routed_receipt_bytes({"sample_count": 13230}, load_mix_request(request))
    assert bounded_json({"x": 1}, 7) == b'{"x":1}'
    with pytest.raises(MixError):
        bounded_json({"x": 1}, 6)


@pytest.mark.parametrize("kind", ["count", "boolean", "routing", "missing", "null", "list"])
def test_parent_checks_routed_metadata_against_request(routed_project, kind):  # noqa: F811
    import json

    _, request = routed_project
    parsed = load_mix_request(request)
    receipt = {"sample_count": 13230, "sample_rate_hz": 22050}
    receipt = json.loads(routed_receipt_bytes(receipt, parsed))
    if kind == "count":
        receipt["frame_count"] = 13229
    elif kind == "boolean":
        receipt["request_schema_version"] = True
    elif kind == "routing":
        receipt["routing"]["tracks"][0]["channel_factors"] = [99.0]
    elif kind == "missing":
        del receipt["routing"]
    else:
        receipt["routing"] = None if kind == "null" else []
    with pytest.raises(MixError):
        verify_routing_receipt(receipt, parsed)


@pytest.mark.parametrize("invalid", [None, []])
def test_malformed_worker_routing_cannot_publish(routed_project, monkeypatch, invalid):  # noqa: F811
    import json
    import os
    import zipfile
    from kinocut_sound.public import mix_job

    root, payload = routed_project
    original = mix_job._run_worker

    def tamper(request, root_fd, stage_fd):
        status = original(request, root_fd, stage_fd)
        with os.fdopen(os.dup(stage_fd), "r+b") as stream:
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}
            receipt = json.loads(members["receipt.json"])
            receipt["routing"] = invalid
            members["receipt.json"] = json.dumps(receipt).encode()
            stream.seek(0)
            stream.truncate()
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
        return status

    monkeypatch.setattr(mix_job, "_run_worker", tamper)
    with pytest.raises(MixError) as failure:
        mix_job.render_mix_request(payload, str(root))
    assert failure.value.code == "mix_worker_failed"
    assert not (root / payload["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))
