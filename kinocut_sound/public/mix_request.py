"""Persisted supplied-media mix requests without changing SoundPlan identities."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, StrictBool, ValidationError, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256, canonical_digest, location_violation
from kinocut_sound.defaults import DEFAULT_PUBLIC_MIX_STEMS
from kinocut_sound.format import ChannelLayout, ConversionPolicy, DitherPolicy, SampleFormat, TimeBase
from kinocut_sound.limits import (
    MAX_ASSEMBLY_CLIPS,
    MAX_ASSEMBLY_TIMELINE_CUES,
    MAX_MIX_DURATION_SECONDS,
    MAX_MIX_INPUT_BYTES,
    MAX_MIX_JSON_DEPTH,
    MAX_MIX_MEMORY_BYTES,
    MAX_MIX_REQUEST_BYTES,
    MAX_MIX_SAMPLE_RATE_HZ,
    MAX_MIX_STEMS,
    MIN_MIX_SAMPLE_RATE_HZ,
    MIX_SOURCE_MEMORY_MULTIPLIER,
    MIX_STEM_MEMORY_MULTIPLIER,
    MIX_WORK_MEMORY_MULTIPLIER,
    MIX_ROUTING_SOURCE_MEMORY_MULTIPLIER,
    MAX_MIX_RECEIPT_BYTES,
    MIX_LAYER_WORK_MEMORY_MULTIPLIER,
    MIX_AUTOMATION_METADATA_BYTES,
    MAX_MIX_ROUTING_RECEIPT_BYTES,
    MAX_MIX_SEND_RECEIPT_BYTES,
    MIX_SEND_METADATA_BYTES,
    MAX_MIX_SIDECHAIN_RECEIPT_BYTES,
    MIX_SIDECHAIN_METADATA_BYTES,
    MIX_CONVERSION_METADATA_BYTES,
    MIX_CONVERSION_IO_BYTES,
)
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, MIX_UNSAFE_PATH, mix_error
from kinocut_sound.routing import Routing
from kinocut_sound.sound_plan import SoundPlan
from kinocut_sound.timeline import CueKind


def relative_path(value: str) -> str:
    if location_violation(value) or "\\" in value or "." in value.split("/"):
        raise mix_error("mix asset path must be a plain project-relative path", MIX_UNSAFE_PATH)
    return value


class SourceAsset(FrozenModel):
    path: str
    sha256: Sha256

    _path = field_validator("path")(relative_path)


class ClipAsset(SourceAsset):
    cue_id: str
    stem_id: str

    _ids = field_validator("cue_id", "stem_id")(BoundedCode)


class CrossfadeSpec(FrozenModel):
    outgoing_cue_id: str
    incoming_cue_id: str
    duration_seconds: float = Field(gt=0, strict=True)

    _ids = field_validator("outgoing_cue_id", "incoming_cue_id")(BoundedCode)


class SoundMixRequest(FrozenModel):
    schema_version: Literal[1] = 1
    plan: SoundPlan
    clips: tuple[ClipAsset, ...] = Field(max_length=MAX_ASSEMBLY_CLIPS)
    transitions: tuple[CrossfadeSpec, ...] = Field(default=(), max_length=MAX_ASSEMBLY_CLIPS)
    bed: SourceAsset | None = None
    duck_bed: StrictBool = False
    output_path: str

    _output = field_validator("output_path")(relative_path)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise mix_error("mix request version must be integer 1", MIX_INPUT_INVALID)
        return value

    def canonical_id(self) -> str:
        payload = self.model_dump(mode="json", exclude={"plan"})
        payload["plan_hash"] = self.plan.canonical_id()
        return canonical_digest(payload)


def _check_tree(value: Any) -> None:
    """Bound Python/decoded JSON before constructing nested contract models."""
    pending = [(value, 0)]
    budget = MAX_MIX_REQUEST_BYTES
    while pending:
        node, depth = pending.pop()
        budget -= 1
        if depth > MAX_MIX_JSON_DEPTH or budget < 0:
            raise mix_error("mix request exceeds structural limits", MIX_OVER_LIMIT)
        if isinstance(node, dict):
            if len(node) > MAX_MIX_REQUEST_BYTES:
                raise mix_error("mix request exceeds structural limits", MIX_OVER_LIMIT)
            pending.extend((v, depth + 1) for pair in node.items() for v in pair)
        elif isinstance(node, (tuple, list)):
            if len(node) > MAX_ASSEMBLY_TIMELINE_CUES:
                raise mix_error("mix request contains too many entries", MIX_OVER_LIMIT)
            pending.extend((v, depth + 1) for v in node)
        elif isinstance(node, str):
            budget -= len(node)
        elif node is not None and type(node) not in (bool, int, float):
            raise mix_error("mix request must contain JSON values", MIX_INPUT_INVALID)


def _json_payload(value: Any) -> dict:
    if isinstance(value, SoundMixRequest):
        value = value.model_dump(mode="python")
    if isinstance(value, str):
        if len(value) > MAX_MIX_REQUEST_BYTES or len(value.encode()) > MAX_MIX_REQUEST_BYTES:
            raise mix_error("mix request is too large", MIX_OVER_LIMIT)
        value = json.loads(value)
    _check_tree(value)
    if not isinstance(value, dict):
        raise mix_error("mix request must be a JSON object", MIX_INPUT_INVALID)
    encoded = json.dumps(value, allow_nan=False).encode()
    if len(encoded) > MAX_MIX_REQUEST_BYTES:
        raise mix_error("mix request is too large", MIX_OVER_LIMIT)
    return json.loads(encoded)


def load_mix_request(value: Any) -> SoundMixRequest:
    try:
        payload = _json_payload(value)
        version = payload.get("schema_version", 1)
        if type(version) is not int or version not in (1, 2, 3, 4):
            raise mix_error("unsupported mix request version", MIX_INPUT_INVALID)
        if version == 4:
            from kinocut_sound.public.mix_request_v4 import SoundMixRequestV4

            request = SoundMixRequestV4.model_validate(payload)
        elif version == 3:
            from kinocut_sound.public.mix_request_v3 import SoundMixRequestV3

            request = SoundMixRequestV3.model_validate(payload)
        elif version == 2:
            from kinocut_sound.public.mix_request_v2 import SoundMixRequestV2

            request = SoundMixRequestV2.model_validate(payload)
        else:
            request = SoundMixRequest.model_validate(payload)
        validate_supported_intent(request)
        return request
    except (ValidationError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise mix_error("invalid sound mix request", MIX_INPUT_INVALID) from exc


def validate_supported_intent(request: SoundMixRequest) -> None:
    plan = request.plan
    fmt = plan.format
    unsupported = (
        fmt.channel_layout not in (ChannelLayout.MONO, ChannelLayout.STEREO)
        or fmt.sample_format != SampleFormat.PCM_S16LE
        or fmt.time_base != TimeBase.CONTINUOUS
        or fmt.dither != DitherPolicy.NONE
        or fmt.conversion != ConversionPolicy()
        or (request.schema_version == 1 and plan.routing != Routing())
        or (request.schema_version < 3 and bool(plan.layers))
    )
    if unsupported:
        raise mix_error("mix assembly supports mono/stereo PCM16 and default routing only", "mix_unsupported_intent")
    if not MIN_MIX_SAMPLE_RATE_HZ <= fmt.sample_rate_hz <= MAX_MIX_SAMPLE_RATE_HZ:
        raise mix_error("mix sample rate exceeds supported limits", MIX_OVER_LIMIT)
    cues = plan.timeline.cues
    if not cues or len(cues) > MAX_ASSEMBLY_CLIPS:
        raise mix_error("mix requires a bounded nonempty timeline", MIX_OVER_LIMIT)
    if any(c.transit_kind for c in cues):
        raise mix_error("transit_kind is not implemented by mix assembly", "mix_unsupported_intent")
    if any(
        c.kind in (CueKind.SILENCE, CueKind.CHAPTER_MARKER)
        and (c.in_point_seconds is not None or c.out_point_seconds is not None)
        for c in cues
    ):
        raise mix_error("silent cues cannot select source windows", MIX_INPUT_INVALID)
    audible = {c.cue_id: c for c in cues if c.kind not in (CueKind.SILENCE, CueKind.CHAPTER_MARKER)}
    bindings = {c.cue_id: c for c in request.clips}
    if len(bindings) != len(request.clips) or set(bindings) != set(audible):
        raise mix_error("mix clips must bind every audible cue exactly once", MIX_INPUT_INVALID)
    stems = plan.delivery.stems.stem_ids or DEFAULT_PUBLIC_MIX_STEMS
    if len(stems) > MAX_MIX_STEMS:
        raise mix_error("too many mix stems", MIX_OVER_LIMIT)
    for cue_id, binding in bindings.items():
        if binding.path != audible[cue_id].source_ref or binding.stem_id not in stems:
            raise mix_error("mix clip must match its cue source and declared stem", MIX_INPUT_INVALID)
    expected_beds = (request.bed.path,) if request.bed else ()
    if plan.beds != expected_beds or (request.duck_bed and request.bed is None):
        raise mix_error("mix bed must match the plan bed reference", MIX_INPUT_INVALID)
    if request.duck_bed and "dialogue" not in stems:
        raise mix_error("bed ducking requires a declared dialogue stem", "mix_unsupported_intent")
    if request.bed and "ambience" not in stems:
        raise mix_error("bed requires a declared ambience stem", "mix_unsupported_intent")
    if request.schema_version >= 2:
        from kinocut_sound.public.mix_request_v2 import compile_routing

        routing = compile_routing(request)
        if plan.routing.envelopes or plan.routing.sends or plan.routing.sidechains:
            from kinocut_sound.public.mix_routing_receipt import bounded_json

            bounded_json(routing.receipt(), MAX_MIX_ROUTING_RECEIPT_BYTES)
            if plan.routing.sends:
                bounded_json(routing.graph.receipt(), MAX_MIX_SEND_RECEIPT_BYTES)
            if plan.routing.sidechains:
                bounded_json(routing.sidechain_processor.receipt(), MAX_MIX_SIDECHAIN_RECEIPT_BYTES)
    if request.schema_version >= 3:
        from kinocut_sound.public.mix_request_v3 import validate_layers

        validate_layers(request)
    check_mix_resources(request, 0)


def check_mix_resources(request: SoundMixRequest, source_bytes: int) -> None:
    duration = request.plan.authoritative_duration_seconds
    stems = len(request.plan.delivery.stems.stem_ids or DEFAULT_PUBLIC_MIX_STEMS)
    samples = round(duration * request.plan.format.sample_rate_hz)
    multiplier = MIX_ROUTING_SOURCE_MEMORY_MULTIPLIER if request.schema_version >= 2 else MIX_SOURCE_MEMORY_MULTIPLIER
    work_multiplier = MIX_LAYER_WORK_MEMORY_MULTIPLIER if request.schema_version >= 3 else MIX_WORK_MEMORY_MULTIPLIER
    estimated = multiplier * source_bytes + 2 * samples * request.plan.format.channel_count * (
        MIX_STEM_MEMORY_MULTIPLIER * stems + work_multiplier
    )
    if request.schema_version >= 2:
        estimated += 4 * MAX_MIX_RECEIPT_BYTES
    if request.plan.routing.envelopes:
        estimated += MIX_AUTOMATION_METADATA_BYTES
    if request.plan.routing.sends:
        pre_sources = {send.source_bus_id for send in request.plan.routing.sends if not send.post_fader}
        estimated += 2 * samples * request.plan.format.channel_count * len(pre_sources) + MIX_SEND_METADATA_BYTES
    if request.plan.routing.sidechains:
        sources = {policy.source_bus_id for policy in request.plan.routing.sidechains}
        estimated += 2 * samples * request.plan.format.channel_count * len(sources) + MIX_SIDECHAIN_METADATA_BYTES
    if request.schema_version == 4:
        estimated += MIX_CONVERSION_METADATA_BYTES + MIX_CONVERSION_IO_BYTES
    if duration > MAX_MIX_DURATION_SECONDS or source_bytes > MAX_MIX_INPUT_BYTES or estimated > MAX_MIX_MEMORY_BYTES:
        raise mix_error("mix exceeds duration, input or memory limits", MIX_OVER_LIMIT)
