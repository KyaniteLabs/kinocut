"""Typed track/bus routing, automation, ducking, and latency policy.

Routing binds typed track and bus ids, gain, pan law, mute/solo semantics,
send/return wiring, ducking sidechains, sample-accurate automation envelopes,
and the latency-compensation policy. Every identifier is a bounded code; every
numeric field rejects booleans and non-finite floats; every referenced bus id
must be declared on the same Routing instance, so a dangling reference is a
contract error rather than a silent mix-down defect.

Design references (sonic-world design):
* Core contracts §"SoundPlan" — buses/routing shape.
* Numeric defaults — latency residual <=1 sample; ducking defaults 9 dB / 80 ms
  attack / 350 ms release / 500 ms recovery.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel
from kinocut_sound.defaults import (
    DEFAULT_BUS_GAIN_DB,
    DEFAULT_LATENCY_RESIDUAL_SAMPLES,
    DEFAULT_PAN_POSITION,
    DEFAULT_SEND_GAIN_DB,
)
from kinocut_sound.limits import (
    MAX_DUCKING_ATTACK_MS,
    MAX_DUCKING_ATTENUATION_DB,
    MAX_DUCKING_RECOVERY_MS,
    MAX_DUCKING_RELEASE_MS,
    MAX_GAIN_DB,
    MAX_LATENCY_RESIDUAL_SAMPLES,
    MAX_PAN_POSITION,
    MIN_DUCKING_ATTENUATION_DB,
    MIN_DUCKING_TIME_MS,
    MIN_GAIN_DB,
    MIN_LATENCY_RESIDUAL_SAMPLES,
    MIN_PAN_POSITION,
    MIN_TIME_SECONDS,
)


class PanLaw(StrEnum):
    """The closed set of pan laws a plan may declare."""

    LINEAR = "linear"
    CONSTANT_POWER = "constant_power"
    BALANCED = "balanced"


class Track(FrozenModel):
    """One track routed to a bus, with static gain/pan and mute/solo flags."""

    track_id: str = Field(min_length=1)
    destination_bus_id: str = Field(min_length=1)
    gain_db: float = Field(ge=MIN_GAIN_DB, le=MAX_GAIN_DB)
    pan_law: PanLaw
    pan_position: float = Field(default=DEFAULT_PAN_POSITION, ge=MIN_PAN_POSITION, le=MAX_PAN_POSITION)
    muted: bool
    soloed: bool

    @field_validator("track_id", "destination_bus_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("gain_db", "pan_position")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value


class Bus(FrozenModel):
    """One bus identified by a bounded id and a bounded kind code."""

    bus_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    gain_db: float = Field(default=DEFAULT_BUS_GAIN_DB, ge=MIN_GAIN_DB, le=MAX_GAIN_DB)
    pan_law: PanLaw = PanLaw.LINEAR

    @field_validator("bus_id", "kind")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("gain_db")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value


class SendReturn(FrozenModel):
    """One send/return wire between two declared buses."""

    send_id: str = Field(min_length=1)
    source_bus_id: str = Field(min_length=1)
    destination_bus_id: str = Field(min_length=1)
    gain_db: float = Field(default=DEFAULT_SEND_GAIN_DB, ge=MIN_GAIN_DB, le=MAX_GAIN_DB)
    post_fader: bool = True

    @field_validator("send_id", "source_bus_id", "destination_bus_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("gain_db")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value

    @model_validator(mode="after")
    def _no_self_send(self) -> SendReturn:
        if self.source_bus_id == self.destination_bus_id:
            raise ValueError("source_bus_id and destination_bus_id must differ")
        return self


class DuckingSidechain(FrozenModel):
    """One ducking sidechain: source ducks target by ``attenuation_db``."""

    source_bus_id: str = Field(min_length=1)
    target_bus_id: str = Field(min_length=1)
    attenuation_db: float = Field(gt=MIN_DUCKING_ATTENUATION_DB, le=MAX_DUCKING_ATTENUATION_DB)
    attack_ms: float = Field(gt=MIN_DUCKING_TIME_MS, le=MAX_DUCKING_ATTACK_MS)
    release_ms: float = Field(gt=MIN_DUCKING_TIME_MS, le=MAX_DUCKING_RELEASE_MS)
    recovery_ms: float = Field(gt=MIN_DUCKING_TIME_MS, le=MAX_DUCKING_RECOVERY_MS)

    @field_validator("source_bus_id", "target_bus_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("attenuation_db", "attack_ms", "release_ms", "recovery_ms")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value

    @model_validator(mode="after")
    def _recovery_at_least_release(self) -> DuckingSidechain:
        if self.recovery_ms < self.release_ms:
            raise ValueError("recovery_ms must be at least release_ms")
        if self.source_bus_id == self.target_bus_id:
            raise ValueError("source_bus_id and target_bus_id must differ")
        return self


class AutomationPoint(FrozenModel):
    """One sample-accurate automation point: time + parameter value."""

    time_seconds: float = Field(ge=MIN_TIME_SECONDS)
    value: float

    @field_validator("time_seconds", "value")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value


class AutomationEnvelope(FrozenModel):
    """A monotonic-time automation envelope over one bounded parameter."""

    target_track_id: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    points: tuple[AutomationPoint, ...] = Field(min_length=1)

    @field_validator("target_track_id", "parameter")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @model_validator(mode="after")
    def _points_are_monotonic(self) -> AutomationEnvelope:
        last = self.points[0].time_seconds
        for point in self.points[1:]:
            if point.time_seconds <= last:
                raise ValueError("automation points must be strictly monotonic in time")
            last = point.time_seconds
        return self


class LatencyCompensation(FrozenModel):
    """The latency compensation policy and measured residual."""

    policy: str
    residual_samples: int = Field(default=DEFAULT_LATENCY_RESIDUAL_SAMPLES, ge=MIN_LATENCY_RESIDUAL_SAMPLES, le=MAX_LATENCY_RESIDUAL_SAMPLES)

    @field_validator("policy")
    @classmethod
    def _policy_is_bounded_and_known(cls, value: str) -> str:
        BoundedCode(value)
        if value not in {"sample_accurate"}:
            raise ValueError("policy must be 'sample_accurate'")
        return value


class Routing(FrozenModel):
    """Tracks, buses, sends, sidechains, and envelopes — internally consistent."""

    tracks: tuple[Track, ...] = ()
    buses: tuple[Bus, ...] = ()
    sends: tuple[SendReturn, ...] = ()
    sidechains: tuple[DuckingSidechain, ...] = ()
    envelopes: tuple[AutomationEnvelope, ...] = ()
    latency: LatencyCompensation = Field(default_factory=lambda: LatencyCompensation(policy="sample_accurate"))

    @model_validator(mode="after")
    def _references_resolve_and_ids_unique(self) -> Routing:
        track_ids = {t.track_id for t in self.tracks}
        if len(track_ids) != len(self.tracks):
            raise ValueError("track ids must be unique")
        bus_ids = {b.bus_id for b in self.buses}
        if len(bus_ids) != len(self.buses):
            raise ValueError("bus ids must be unique")

        for track in self.tracks:
            if track.destination_bus_id not in bus_ids:
                raise ValueError(f"track {track.track_id} references unknown bus {track.destination_bus_id}")
        for send in self.sends:
            if send.source_bus_id not in bus_ids:
                raise ValueError(f"send {send.send_id} references unknown source bus {send.source_bus_id}")
            if send.destination_bus_id not in bus_ids:
                raise ValueError(f"send {send.send_id} references unknown destination bus {send.destination_bus_id}")
        for sidechain in self.sidechains:
            if sidechain.source_bus_id not in bus_ids:
                raise ValueError(f"sidechain references unknown source bus {sidechain.source_bus_id}")
            if sidechain.target_bus_id not in bus_ids:
                raise ValueError(f"sidechain references unknown target bus {sidechain.target_bus_id}")
        for envelope in self.envelopes:
            if envelope.target_track_id not in track_ids:
                raise ValueError(
                    f"envelope references unknown track {envelope.target_track_id}"
                )
        return self
