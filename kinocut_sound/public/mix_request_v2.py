"""Explicit cue-to-track bindings without changing the V1 request shape."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, canonical_digest
from kinocut_sound.defaults import DEFAULT_PUBLIC_MIX_STEMS
from kinocut_sound.limits import MAX_MIX_ROUTING_TRACKS, MAX_MIX_ROUTING_BUSES, MAX_MIX_ROUTING_BINDINGS
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix.static_routing import StaticRouting
from kinocut_sound.public.mix_request import SoundMixRequest
from kinocut_sound.public.mix_automation_request import guard_automation_rows
from kinocut_sound.public.mix_send_request import guard_send_rows
from kinocut_sound.public.mix_sidechain_request import guard_sidechain_rows


class CueTrackBinding(FrozenModel):
    cue_id: str
    track_id: str

    _ids = field_validator("cue_id", "track_id")(BoundedCode)


def _strict_routing(value):
    bindings = value.get("cue_tracks", ())
    if not isinstance(bindings, (list, tuple)):
        raise mix_error("cue track bindings must be an array", MIX_INPUT_INVALID)
    if len(bindings) > MAX_MIX_ROUTING_BINDINGS:
        raise mix_error("cue track bindings exceed limits", MIX_OVER_LIMIT)
    plan = value.get("plan", {})
    if isinstance(plan, BaseModel):
        plan = plan.model_dump(mode="python")
    if not isinstance(plan, dict):
        raise mix_error("V2 plan must be a mapping or typed plan", MIX_INPUT_INVALID)
    routing = plan.get("routing", {})
    if not isinstance(routing, dict):
        raise mix_error("V2 routing must be a mapping", MIX_INPUT_INVALID)
    guard_automation_rows(routing)
    guard_send_rows(routing)
    guard_sidechain_rows(routing)
    for name, limit in (("tracks", MAX_MIX_ROUTING_TRACKS), ("buses", MAX_MIX_ROUTING_BUSES)):
        rows = routing.get(name, ())
        if not isinstance(rows, (list, tuple)):
            raise mix_error("routing entries must be arrays", MIX_INPUT_INVALID)
        if len(rows) > limit:
            raise mix_error("routing entries exceed limits", MIX_OVER_LIMIT)
        for row in rows:
            if not isinstance(row, dict):
                raise mix_error("routing entry must be a mapping", MIX_INPUT_INVALID)
            for key in ("muted", "soloed") if name == "tracks" else ():
                if key in row and type(row[key]) is not bool:
                    raise mix_error("routing flags must be actual booleans", MIX_INPUT_INVALID)
            for key in ("gain_db", "pan_position"):
                if key in row and type(row[key]) not in (int, float):
                    raise mix_error("routing values must be actual numbers", MIX_INPUT_INVALID)


class SoundMixRequestV2(SoundMixRequest):
    schema_version: Literal[2] = 2
    cue_tracks: tuple[CueTrackBinding, ...] = Field(max_length=MAX_MIX_ROUTING_BINDINGS)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _version(cls, value):
        if type(value) is not int:
            raise mix_error("mix request version must be integer 2", MIX_INPUT_INVALID)
        return value

    @model_validator(mode="before")
    @classmethod
    def _strict_raw(cls, value):
        if isinstance(value, dict):
            _strict_routing(value)
        return value

    def canonical_id(self):
        payload = self.model_dump(mode="json", exclude={"plan"})
        payload["cue_tracks"] = sorted(payload["cue_tracks"], key=lambda item: item["cue_id"])
        payload["plan_hash"] = self.plan.canonical_id()
        return canonical_digest(payload)


def compile_routing(request):
    declared = request.plan.routing
    track_routing = (
        declared.model_copy(update={"sends": (), "sidechains": ()})
        if declared.sends or declared.sidechains
        else declared
    )
    arguments = (
        track_routing,
        tuple((item.cue_id, item.track_id) for item in request.cue_tracks),
        request.plan.format.channel_count,
        request.plan.delivery.stems.stem_ids or DEFAULT_PUBLIC_MIX_STEMS,
        tuple(clip.cue_id for clip in request.clips),
    )
    if request.plan.routing.envelopes:
        from kinocut_sound.mix.automated_routing import AutomatedRouting

        rate = request.plan.format.sample_rate_hz
        clip_ids = {clip.cue_id for clip in request.clips}
        starts = {
            cue.cue_id: round(cue.start_seconds * rate) for cue in request.plan.timeline.cues if cue.cue_id in clip_ids
        }
        routing = AutomatedRouting(
            *arguments,
            sample_rate_hz=rate,
            output_frames=round(request.plan.authoritative_duration_seconds * rate),
            cue_starts=starts,
        )
    else:
        routing = StaticRouting(*arguments)
    if declared.sends:
        from kinocut_sound.mix.sent_routing import SentRouting

        routing = SentRouting(
            declared.model_copy(update={"sidechains": ()}) if declared.sidechains else declared,
            routing,
            round(request.plan.authoritative_duration_seconds * request.plan.format.sample_rate_hz),
            request.plan.format.channel_count,
        )
    if declared.sidechains:
        from kinocut_sound.mix.sidechain_routing import SidechainRouting

        rate = request.plan.format.sample_rate_hz
        routing = SidechainRouting(
            declared,
            routing,
            round(request.plan.authoritative_duration_seconds * rate),
            request.plan.format.channel_count,
            rate,
        )
    for clip in request.clips:
        track = routing.tracks[routing.bindings[clip.cue_id]][0]
        if clip.stem_id != track.destination_bus_id:
            raise mix_error("clip stem must equal its track destination bus", MIX_INPUT_INVALID)
    return routing
