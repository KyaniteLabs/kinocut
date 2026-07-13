"""Ambient layer stack with per-layer gain, mute/solo, and a ducking contract.

W4.2: multiple independent ambient layers stack with independent gain. W3.8
(ambient bed layering with ducking) is *contract-side only* here — the S9
assembly/mix leaf applies the ducking envelope. This module owns the declared
shape: ordered layers, per-layer gain in dB, mute/solo semantics, and an
optional :class:`DuckingContract` that names the sidechain bus and the
attenuation/release parameters S9 will use.

Mute/solo semantics follow standard console behaviour: when any layer is
soloed, only soloed and unmuted layers contribute; otherwise every unmuted
layer contributes. Effective gain is reported per layer so S9 can place each
layer on the timeline without re-deriving the mix.

Design references (sonic-world design):
* W4.2 — ambient layer management with independent gain.
* W3.8 — ambient bed layering with ducking (contract side; S9 applies).
* G07 — ducking envelope declared against numeric policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel
from kinocut_sound.defaults import (
    DEFAULT_BUS_GAIN_DB,
    DEFAULT_SEND_GAIN_DB,
)
from kinocut_sound.limits import (
    MAX_DUCKING_ATTENUATION_DB,
    MAX_DUCKING_RECOVERY_MS,
    MAX_DUCKING_RELEASE_MS,
    MAX_GAIN_DB,
    MAX_DUCKING_ATTACK_MS,
    MIN_DUCKING_ATTENUATION_DB,
    MIN_DUCKING_TIME_MS,
    MIN_GAIN_DB,
)
from kinocut_sound.world._errors import world_error

# S8-leaf-specific ceiling: a hostile layer table cannot grow unbounded.
_MAX_LAYERS = 64

# Ducking defaults for the contract side. The full numeric policy (9 dB
# attenuation, 80 ms attack, 350 ms release, 500 ms recovery) is named in the
# sonic-world design; the S9 mix leaf owns the operational policy. The shared
# defaults.py module cannot be edited by this leaf, so the bed-author-facing
# defaults are declared here.
DEFAULT_LAYER_DUCKING_ATTENUATION_DB = 9.0
DEFAULT_LAYER_DUCKING_ATTACK_MS = 80.0
DEFAULT_LAYER_DUCKING_RELEASE_MS = 350.0
DEFAULT_LAYER_DUCKING_RECOVERY_MS = 500.0


class DuckingContract(FrozenModel):
    """Declared ducking envelope for a layer stack — S9 applies the envelope.

    The contract names the sidechain source bus, the target bed bus, and the
    attenuation/attack/release/recovery parameters. S9 reads this and applies
    the ducking envelope sample-accurately; S8 only carries the declaration so
    a bed author can describe intent without binding the S9 mixdown.
    """

    source_bus_id: str = Field(min_length=1)
    target_bus_id: str = Field(min_length=1)
    attenuation_db: float = Field(
        default=DEFAULT_LAYER_DUCKING_ATTENUATION_DB,
        gt=MIN_DUCKING_ATTENUATION_DB,
        le=MAX_DUCKING_ATTENUATION_DB,
    )
    attack_ms: float = Field(
        default=DEFAULT_LAYER_DUCKING_ATTACK_MS,
        gt=MIN_DUCKING_TIME_MS,
        le=MAX_DUCKING_ATTACK_MS,
    )
    release_ms: float = Field(
        default=DEFAULT_LAYER_DUCKING_RELEASE_MS,
        gt=MIN_DUCKING_TIME_MS,
        le=MAX_DUCKING_RELEASE_MS,
    )
    recovery_ms: float = Field(
        default=DEFAULT_LAYER_DUCKING_RECOVERY_MS,
        gt=MIN_DUCKING_TIME_MS,
        le=MAX_DUCKING_RECOVERY_MS,
    )

    @field_validator("source_bus_id", "target_bus_id")
    @classmethod
    def _bus_ids_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("attenuation_db", "attack_ms", "release_ms", "recovery_ms")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("ducking numeric must not be a boolean")
        return value

    @model_validator(mode="after")
    def _no_self_duck(self) -> DuckingContract:
        if self.source_bus_id == self.target_bus_id:
            raise ValueError("ducking source and target buses must differ")
        if self.recovery_ms < self.release_ms:
            raise ValueError("recovery_ms must be at least release_ms")
        return self


class AmbientLayer(FrozenModel):
    """One independent ambient layer: asset ref, gain, mute/solo."""

    layer_id: str = Field(min_length=1)
    asset_ref: str = Field(min_length=1)
    gain_db: float = Field(default=DEFAULT_BUS_GAIN_DB, ge=MIN_GAIN_DB, le=MAX_GAIN_DB)
    muted: bool = False
    soloed: bool = False

    @field_validator("layer_id", "asset_ref")
    @classmethod
    def _ids_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("gain_db")
    @classmethod
    def _gain_not_boolean(cls, value: float) -> bool | float:
        if isinstance(value, bool):
            raise ValueError("gain_db must not be a boolean")
        return value


@dataclass(frozen=True)
class LayerMixResult:
    """Effective per-layer contribution after mute/solo resolution."""

    layer_id: str
    audible: bool
    effective_gain_db: float


class LayerStack:
    """Ordered ambient layer stack with mute/solo and an optional ducking contract."""

    __slots__ = ("_ducking", "_layers", "_order")

    def __init__(
        self,
        layers: tuple[AmbientLayer, ...],
        *,
        ducking: DuckingContract | None = None,
    ) -> None:
        if not isinstance(layers, tuple):
            raise world_error("layers must be a tuple", "layer_stack_invalid")
        if len(layers) > _MAX_LAYERS:
            raise world_error("layer count exceeds ceiling", "layer_stack_invalid")
        ids: set[str] = set()
        normalized: list[AmbientLayer] = []
        for layer in layers:
            snapshot = AmbientLayer.model_validate(layer.model_dump(mode="python"))
            if snapshot.layer_id in ids:
                raise world_error(
                    "layer ids must be unique",
                    "layer_stack_invalid",
                )
            ids.add(snapshot.layer_id)
            normalized.append(snapshot)
        self._layers: dict[str, AmbientLayer] = {layer.layer_id: layer for layer in normalized}
        self._order: tuple[str, ...] = tuple(layer.layer_id for layer in normalized)
        self._ducking: DuckingContract | None = ducking

    @property
    def layer_ids(self) -> tuple[str, ...]:
        return self._order

    @property
    def ducking(self) -> DuckingContract | None:
        return self._ducking

    def layer(self, layer_id: str) -> AmbientLayer:
        checked = BoundedCode(layer_id)
        snapshot = self._layers.get(checked)
        if snapshot is None:
            raise world_error("layer is not in the stack", "layer_stack_invalid")
        return snapshot

    def has_solo(self) -> bool:
        return any(layer.soloed for layer in self._layers.values())

    def is_audible(self, layer_id: str) -> bool:
        layer = self.layer(layer_id)
        if self.has_solo():
            return bool(layer.soloed and not layer.muted)
        return not layer.muted

    def mixed_gain_db(self, layer_id: str) -> float:
        """Return the effective gain in dB considering mute/solo."""

        layer = self.layer(layer_id)
        if not self.is_audible(layer_id):
            # A muted/non-soloed layer contributes negative infinity in practice;
            # report the ceiling-silent gain so callers can compare numerically.
            return MIN_GAIN_DB
        return layer.gain_db

    def mix(self) -> tuple[LayerMixResult, ...]:
        """Return ordered per-layer effective contributions for S9 placement."""

        return tuple(
            LayerMixResult(
                layer_id=layer_id,
                audible=self.is_audible(layer_id),
                effective_gain_db=self.mixed_gain_db(layer_id),
            )
            for layer_id in self._order
        )

    def effective_layers(self) -> tuple[AmbientLayer, ...]:
        """Return ordered layers that are currently audible."""

        return tuple(self._layers[layer_id] for layer_id in self._order if self.is_audible(layer_id))

    def bus_gain_db(self) -> float:
        """Return the declared bus base gain (default; S9 may override)."""

        return DEFAULT_SEND_GAIN_DB
