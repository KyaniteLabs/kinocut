"""Explicit ambient source bindings without altering earlier request identities."""

from typing import Literal

from pydantic import Field, model_validator

from kinocut_sound._canonical import FrozenModel
from kinocut_sound.defaults import DEFAULT_PUBLIC_MIX_STEMS
from kinocut_sound.limits import MAX_AMBIENT_LAYERS
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.public.mix_request import SourceAsset
from kinocut_sound.public.mix_request_v2 import SoundMixRequestV2
from kinocut_sound.world.layers import AmbientLayer, DuckingContract, LayerStack
from kinocut_sound.world._errors import WorldError


class LayerAsset(FrozenModel):
    layer: AmbientLayer
    source: SourceAsset
    fill_mode: Literal["pad", "loop"]
    crossfade_frames: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _strict_layer(cls, value):
        if isinstance(value, dict):
            layer = value.get("layer")
            if isinstance(layer, AmbientLayer):
                layer = layer.model_dump(mode="python")
            if isinstance(layer, dict):
                for key in ("muted", "soloed"):
                    if key in layer and type(layer[key]) is not bool:
                        raise mix_error("layer flags must be actual booleans", MIX_INPUT_INVALID)
                if "gain_db" in layer and type(layer["gain_db"]) not in (int, float):
                    raise mix_error("layer gain must be an actual number", MIX_INPUT_INVALID)
        return value

    @model_validator(mode="after")
    def _fill_contract(self):
        if (self.fill_mode == "pad") != (self.crossfade_frames is None):
            raise mix_error("only loop fill requires crossfade frames", MIX_INPUT_INVALID)
        return self


class SoundMixRequestV3(SoundMixRequestV2):
    schema_version: Literal[3] = 3
    layer_assets: tuple[LayerAsset, ...] = Field(max_length=MAX_AMBIENT_LAYERS)
    layer_ducking: DuckingContract | None = None

    @model_validator(mode="before")
    @classmethod
    def _bounded_layers(cls, value):
        if isinstance(value, dict):
            rows = value.get("layer_assets", ())
            if not isinstance(rows, (list, tuple)):
                raise mix_error("layer assets must be an array", MIX_INPUT_INVALID)
            if len(rows) > MAX_AMBIENT_LAYERS:
                raise mix_error("layer assets exceed limit", MIX_OVER_LIMIT)
        return value


def validate_layers(request):
    try:
        stack = LayerStack(tuple(item.layer for item in request.layer_assets))
    except WorldError as exc:
        raise mix_error("invalid ambient layer stack", MIX_INPUT_INVALID) from exc
    if stack.layer_ids != request.plan.layers:
        raise mix_error("ordered layer assets must match plan layer ids", MIX_INPUT_INVALID)
    if request.layer_ducking is not None:
        raise mix_error("layer ducking is not implemented", "mix_unsupported_intent")
    stems = request.plan.delivery.stems.stem_ids or DEFAULT_PUBLIC_MIX_STEMS
    if stack.layer_ids and "ambience" not in stems:
        raise mix_error("layers require an ambience stem", MIX_INPUT_INVALID)
    if round(request.plan.authoritative_duration_seconds * request.plan.format.sample_rate_hz) < 1:
        raise mix_error("layered mixes require a positive target frame count", MIX_INPUT_INVALID)
    refs = {}
    for item in request.layer_assets:
        identity = (item.source.path, item.source.sha256)
        if item.layer.asset_ref in refs and refs[item.layer.asset_ref] != identity:
            raise mix_error("layer asset reference has conflicting source bindings", MIX_INPUT_INVALID)
        refs[item.layer.asset_ref] = identity
