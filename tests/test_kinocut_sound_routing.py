"""RED-first tests for the ``kinocut_sound`` routing contract.

Routing binds typed track/bus ids, gain, pan law and automation, mute/solo
semantics, send/return wiring, ducking sidechains, sample-accurate automation,
and the latency-compensation policy. All identifiers are bounded codes so a
host path or uncontrolled prose cannot ride in.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.routing import (
    AutomationEnvelope,
    AutomationPoint,
    Bus,
    DuckingSidechain,
    LatencyCompensation,
    PanLaw,
    Routing,
    SendReturn,
    Track,
)


def _track(track_id: str = "track_dialog_001", destination_bus_id: str = "bus_dialog") -> Track:
    return Track(
        track_id=track_id,
        destination_bus_id=destination_bus_id,
        gain_db=0.0,
        pan_law=PanLaw.LINEAR,
        muted=False,
        soloed=False,
    )


def _bus(bus_id: str = "bus_dialog") -> Bus:
    return Bus(bus_id=bus_id, kind="dialog", gain_db=0.0, pan_law=PanLaw.LINEAR)


def test_pan_laws_are_closed():
    assert {p.value for p in PanLaw} == {"linear", "constant_power", "balanced"}


def test_track_and_bus_reject_unbounded_ids_and_unsafe_gain():
    _track()
    _bus()
    for bad in ("with space", "../x", "1lead"):
        with pytest.raises(ValidationError):
            _track(track_id=bad)
        with pytest.raises(ValidationError):
            _bus(bus_id=bad)
    for bad_gain in (float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            Track(
                track_id="t",
                destination_bus_id="b",
                gain_db=bad_gain,
                pan_law=PanLaw.LINEAR,
                muted=False,
                soloed=False,
            )


def test_send_return_rejects_unbounded_codes_and_requires_destination():
    SendReturn(send_id="send_dialog_room", source_bus_id="bus_dialog", destination_bus_id="bus_room", gain_db=-6.0)
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            SendReturn(
                send_id=bad,
                source_bus_id="bus_dialog",
                destination_bus_id="bus_room",
                gain_db=0.0,
            )


def test_ducking_sidechain_honors_named_defaults():
    sidechain = DuckingSidechain(
        source_bus_id="bus_dialog",
        target_bus_id="bus_bed",
        attenuation_db=9.0,
        attack_ms=80.0,
        release_ms=350.0,
        recovery_ms=500.0,
    )
    assert sidechain.attenuation_db == 9.0
    assert sidechain.attack_ms == 80.0
    assert sidechain.release_ms == 350.0
    with pytest.raises(ValidationError):
        DuckingSidechain(
            source_bus_id="bus_dialog",
            target_bus_id="bus_bed",
            attenuation_db=9.0,
            attack_ms=80.0,
            release_ms=350.0,
            recovery_ms=200.0,  # recovery must be >= release
        )


def test_automation_envelope_requires_monotonic_times_and_bounded_points():
    env = AutomationEnvelope(
        target_track_id="track_dialog_001",
        parameter="gain_db",
        points=(
            AutomationPoint(time_seconds=0.0, value=0.0),
            AutomationPoint(time_seconds=1.0, value=-6.0),
        ),
    )
    assert env.points[1].time_seconds == 1.0
    with pytest.raises(ValidationError):
        AutomationEnvelope(
            target_track_id="track_dialog_001",
            parameter="gain_db",
            points=(
                AutomationPoint(time_seconds=1.0, value=0.0),
                AutomationPoint(time_seconds=0.5, value=-6.0),  # out of order
            ),
        )
    with pytest.raises(ValidationError):
        AutomationEnvelope(
            target_track_id="track_dialog_001",
            parameter="with space",
            points=(AutomationPoint(time_seconds=0.0, value=0.0),),
        )


def test_latency_compensation_requires_residual_within_one_sample():
    LatencyCompensation(policy="sample_accurate", residual_samples=0)
    LatencyCompensation(policy="sample_accurate", residual_samples=1)
    with pytest.raises(ValidationError):
        LatencyCompensation(policy="sample_accurate", residual_samples=2)
    with pytest.raises(ValidationError):
        LatencyCompensation(policy="off", residual_samples=0)  # invalid policy


def test_routing_rejects_dangling_bus_references():
    track = _track(track_id="t1", destination_bus_id="bus_missing")
    bus = _bus(bus_id="bus_dialog")
    with pytest.raises(ValidationError):
        Routing(tracks=(track,), buses=(bus,), sends=(), sidechains=(), envelopes=())
    ok = Routing(
        tracks=(_track(track_id="t1", destination_bus_id="bus_dialog"),),
        buses=(_bus(bus_id="bus_dialog"),),
        sends=(),
        sidechains=(),
        envelopes=(),
    )
    assert ok.buses[0].bus_id == "bus_dialog"


def test_routing_rejects_duplicate_track_and_bus_ids():
    with pytest.raises(ValidationError):
        Routing(
            tracks=(_track(track_id="dup"), _track(track_id="dup", destination_bus_id="bus_dialog")),
            buses=(_bus(bus_id="bus_dialog"),),
            sends=(),
            sidechains=(),
            envelopes=(),
        )
    with pytest.raises(ValidationError):
        Routing(
            tracks=(_track(track_id="t1"),),
            buses=(_bus(bus_id="dup"), _bus(bus_id="dup")),
            sends=(),
            sidechains=(),
            envelopes=(),
        )
