"""Verified content-addressed presets and exact per-project configuration."""

from __future__ import annotations

from enum import StrEnum
from itertools import islice
import logging

from pydantic import Field, StrictBool, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound._errors import SoundContractError
from kinocut_sound.limits import MAX_S3_PRESETS
from kinocut_sound.registry import AdapterRegistry

logger = logging.getLogger(__name__)


class SoundConfigError(SoundContractError):
    """Stable project configuration or preset error."""


def _error(message: str, code: str) -> SoundConfigError:
    return SoundConfigError(message, code=code, suggested_action={"auto_fix": False})


class PresetKind(StrEnum):
    """Closed S3 preset families."""

    PROFILE = "profile"
    CHAIN = "chain"
    SPATIAL = "spatial"
    BED = "bed"


class VerifiedPayloadRef(FrozenModel):
    """Verified content-addressed preset payload reference."""

    asset_id: str = Field(min_length=1)
    content_digest: Sha256
    verified: StrictBool

    @field_validator("asset_id")
    @classmethod
    def _asset(cls, value: str) -> str:
        return BoundedCode(value)

    @model_validator(mode="after")
    def _must_be_verified(self) -> VerifiedPayloadRef:
        if not self.verified:
            raise ValueError("preset payload must be verified")
        return self


class Preset(FrozenModel):
    """Versioned preset whose payload is verified and content-addressed."""

    preset_id: str = Field(min_length=1)
    kind: PresetKind
    version: str = Field(min_length=1)
    payload: VerifiedPayloadRef

    @field_validator("preset_id", "version")
    @classmethod
    def _codes(cls, value: str) -> str:
        return BoundedCode(value)

    @property
    def content_digest(self) -> str:
        return self.payload.content_digest


class PresetAddress(FrozenModel):
    """Exact catalog selector bound to expected content digest."""

    preset_id: str = Field(min_length=1)
    kind: PresetKind
    version: str = Field(min_length=1)
    expected_digest: Sha256

    @field_validator("preset_id", "version")
    @classmethod
    def _codes(cls, value: str) -> str:
        return BoundedCode(value)


def _bounded(values: object, label: str, *, allow_empty: bool = False) -> tuple[object, ...]:
    try:
        items = tuple(islice(iter(values), MAX_S3_PRESETS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("sound configuration traversal failed")
        raise ValueError(f"{label} is invalid") from None
    if len(items) > MAX_S3_PRESETS or (not items and not allow_empty):
        raise ValueError(f"{label} must be bounded and nonempty")
    return items


def _code_tuple(values: object) -> tuple[str, ...]:
    checked = tuple(BoundedCode(value) for value in _bounded(values, "configuration selectors"))
    if len(set(checked)) != len(checked):
        raise ValueError("configuration selectors must be unique")
    return tuple(sorted(checked))


def _addresses(values: object) -> tuple[PresetAddress, ...]:
    checked = tuple(
        PresetAddress.model_validate(item, from_attributes=True) for item in _bounded(values, "preset addresses")
    )
    keys = tuple((item.kind, item.preset_id, item.version) for item in checked)
    if len(set(keys)) != len(keys):
        raise ValueError("preset addresses must be unique")
    return tuple(sorted(checked, key=lambda item: (item.kind.value, item.preset_id, item.version)))


def _bounded_presets(values: object) -> tuple[Preset, ...]:
    try:
        return tuple(
            Preset.model_validate(item, from_attributes=True)
            for item in _bounded(values, "preset collection", allow_empty=True)
        )
    except ValueError:
        raise
    except Exception:
        logger.warning("preset validation failed")
        raise _error("preset collection is invalid", "invalid_preset_collection") from None


class PresetCatalog:
    """Bounded catalog preserving kind, id, version, and verified digest."""

    def __init__(self, presets: object = ()) -> None:
        self._items: dict[tuple[PresetKind, str, str], Preset] = {}
        try:
            checked = _bounded_presets(presets)
        except ValueError:
            raise _error("preset collection exceeds its ceiling", "preset_capacity_exceeded") from None
        for preset in checked:
            self.save(preset)

    @property
    def count(self) -> int:
        return len(self._items)

    def save(self, preset: Preset) -> None:
        try:
            checked = Preset.model_validate(preset.model_dump(mode="python"))
        except Exception:
            logger.warning("preset validation failed")
            raise _error("preset is invalid", "invalid_preset") from None
        key = (checked.kind, checked.preset_id, checked.version)
        if key in self._items:
            raise _error("preset already exists", "preset_already_exists")
        if len(self._items) >= MAX_S3_PRESETS:
            raise _error("preset catalog exceeds its ceiling", "preset_capacity_exceeded")
        self._items[key] = checked

    def load(self, address: PresetAddress) -> Preset:
        """Load an exact address and verify the expected payload digest."""

        try:
            checked = PresetAddress.model_validate(address.model_dump(mode="python"))
        except Exception:
            raise _error("preset selector is invalid", "invalid_preset_selector") from None
        preset = self._items.get((checked.kind, checked.preset_id, checked.version))
        if preset is None:
            raise _error("preset is not registered", "preset_missing")
        if preset.content_digest != checked.expected_digest:
            raise _error("preset content digest changed", "preset_digest_mismatch")
        return preset


class ProjectSoundConfig(FrozenModel):
    """Per-project exact roster, ambience, loudness, spatial, and chain refs."""

    project_id: str = Field(min_length=1)
    roster_preset: PresetAddress
    ambience_preset: PresetAddress
    loudness_preset: str = Field(min_length=1)
    spatial_preset: PresetAddress
    chain_preset: PresetAddress
    adapter_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("project_id", "loudness_preset")
    @classmethod
    def _codes(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("adapter_ids", mode="before")
    @classmethod
    def _adapters(cls, value: object) -> tuple[str, ...]:
        return _code_tuple(value)

    @model_validator(mode="after")
    def _kind_slots(self) -> ProjectSoundConfig:
        expected = (
            (self.roster_preset, PresetKind.PROFILE),
            (self.ambience_preset, PresetKind.BED),
            (self.spatial_preset, PresetKind.SPATIAL),
            (self.chain_preset, PresetKind.CHAIN),
        )
        if any(address.kind is not kind for address, kind in expected):
            raise ValueError("preset address kind does not match configuration slot")
        return self


class ProjectConfigPolicy(FrozenModel):
    """Closed allowlist of exact preset addresses and compiled adapters."""

    project_ids: tuple[str, ...] = Field(min_length=1)
    allowed_presets: tuple[PresetAddress, ...] = Field(min_length=1)
    loudness_presets: tuple[str, ...] = Field(min_length=1)
    adapter_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("project_ids", "loudness_presets", "adapter_ids", mode="before")
    @classmethod
    def _allowlists(cls, value: object) -> tuple[str, ...]:
        return _code_tuple(value)

    @field_validator("allowed_presets", mode="before")
    @classmethod
    def _preset_allowlist(cls, value: object) -> tuple[PresetAddress, ...]:
        return _addresses(value)

    def authorize(
        self,
        config: ProjectSoundConfig,
        *,
        catalog: PresetCatalog,
        registry: AdapterRegistry,
    ) -> None:
        """Resolve every exact ref and require every adapter be compiled."""

        try:
            checked = ProjectSoundConfig.model_validate(config.model_dump(mode="python"))
            addresses = (
                checked.roster_preset,
                checked.ambience_preset,
                checked.spatial_preset,
                checked.chain_preset,
            )
            allowed = set(self.allowed_presets)
            valid = (
                checked.project_id in self.project_ids
                and checked.loudness_preset in self.loudness_presets
                and all(address in allowed for address in addresses)
                and set(checked.adapter_ids) <= set(self.adapter_ids)
                and all(registry.contains(adapter_id) for adapter_id in checked.adapter_ids)
            )
            if valid:
                for address in addresses:
                    catalog.load(address)
        except SoundConfigError:
            raise
        except Exception:
            logger.warning("project configuration validation failed")
            raise _error("project sound configuration is invalid", "invalid_project_config") from None
        if not valid:
            raise _error("project sound configuration is denied", "project_config_denied")
