"""Hash-only presets and allowlisted per-project sound configuration."""

from __future__ import annotations

from enum import StrEnum
from itertools import islice
import logging

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound._errors import SoundContractError
from kinocut_sound.limits import MAX_S3_PRESETS

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


class Preset(FrozenModel):
    """Privacy-safe preset identity; payload remains content-addressed elsewhere."""

    preset_id: str = Field(min_length=1)
    kind: PresetKind
    version: str = Field(min_length=1)
    content_digest: Sha256

    @field_validator("preset_id", "version")
    @classmethod
    def _codes(cls, value: str) -> str:
        return BoundedCode(value)


def _bounded_presets(values: object) -> tuple[Preset, ...]:
    try:
        items = tuple(islice(iter(values), MAX_S3_PRESETS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("preset traversal failed")
        raise _error("preset collection is invalid", "invalid_preset_collection") from None
    if len(items) > MAX_S3_PRESETS:
        raise _error("preset collection exceeds its ceiling", "preset_capacity_exceeded")
    try:
        return tuple(Preset.model_validate(item, from_attributes=True) for item in items)
    except Exception:
        logger.warning("preset validation failed")
        raise _error("preset collection is invalid", "invalid_preset_collection") from None


class PresetCatalog:
    """Bounded in-memory preset catalog keyed by closed kind and identifier."""

    def __init__(self, presets: object = ()) -> None:
        self._items: dict[tuple[PresetKind, str], Preset] = {}
        for preset in _bounded_presets(presets):
            self.save(preset)

    @property
    def count(self) -> int:
        """Return the number of registered preset identities."""

        return len(self._items)

    def save(self, preset: Preset) -> None:
        """Save one hash-only preset identity without importing implementation."""

        try:
            checked = Preset.model_validate(preset.model_dump(mode="python"))
        except Exception:
            logger.warning("preset validation failed")
            raise _error("preset is invalid", "invalid_preset") from None
        key = (checked.kind, checked.preset_id)
        if key in self._items:
            raise _error("preset already exists", "preset_already_exists")
        if len(self._items) >= MAX_S3_PRESETS:
            raise _error("preset catalog exceeds its ceiling", "preset_capacity_exceeded")
        self._items[key] = checked

    def load(self, preset_id: str, *, kind: PresetKind) -> Preset:
        """Load an exact kind/id pair or fail closed."""

        try:
            preset_id = BoundedCode(preset_id)
            kind = PresetKind(kind)
        except (TypeError, ValueError):
            raise _error("preset selector is invalid", "invalid_preset_selector") from None
        preset = self._items.get((kind, preset_id))
        if preset is None:
            raise _error("preset is not registered", "preset_missing")
        return preset


def _code_tuple(values: object) -> tuple[str, ...]:
    try:
        items = tuple(islice(iter(values), MAX_S3_PRESETS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("configuration selector traversal failed")
        raise ValueError("configuration selectors are invalid") from None
    if not items or len(items) > MAX_S3_PRESETS:
        raise ValueError("configuration selectors must be nonempty and bounded")
    checked = tuple(BoundedCode(value) for value in items)
    if len(set(checked)) != len(checked):
        raise ValueError("configuration selectors must be unique")
    return checked


class ProjectSoundConfig(FrozenModel):
    """Per-project selection of roster, ambience, loudness, spatial, and chain."""

    project_id: str = Field(min_length=1)
    roster_preset: str = Field(min_length=1)
    ambience_preset: str = Field(min_length=1)
    loudness_preset: str = Field(min_length=1)
    spatial_preset: str = Field(min_length=1)
    chain_preset: str = Field(min_length=1)
    adapter_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "project_id",
        "roster_preset",
        "ambience_preset",
        "loudness_preset",
        "spatial_preset",
        "chain_preset",
    )
    @classmethod
    def _codes(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("adapter_ids", mode="before")
    @classmethod
    def _adapters(cls, value: object) -> tuple[str, ...]:
        return _code_tuple(value)


class ProjectConfigPolicy(FrozenModel):
    """Closed selector allowlists for one or more projects."""

    project_ids: tuple[str, ...] = Field(min_length=1)
    roster_presets: tuple[str, ...] = Field(min_length=1)
    ambience_presets: tuple[str, ...] = Field(min_length=1)
    loudness_presets: tuple[str, ...] = Field(min_length=1)
    spatial_presets: tuple[str, ...] = Field(min_length=1)
    chain_presets: tuple[str, ...] = Field(min_length=1)
    adapter_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "project_ids",
        "roster_presets",
        "ambience_presets",
        "loudness_presets",
        "spatial_presets",
        "chain_presets",
        "adapter_ids",
        mode="before",
    )
    @classmethod
    def _allowlists(cls, value: object) -> tuple[str, ...]:
        return _code_tuple(value)

    def authorize(self, config: ProjectSoundConfig) -> None:
        """Fail closed if any project selection falls outside policy."""

        try:
            project_id = BoundedCode(config.project_id)
            roster = BoundedCode(config.roster_preset)
            ambience = BoundedCode(config.ambience_preset)
            loudness = BoundedCode(config.loudness_preset)
            spatial = BoundedCode(config.spatial_preset)
            chain = BoundedCode(config.chain_preset)
            adapters = _code_tuple(config.adapter_ids)
            allowed_adapters = _code_tuple(self.adapter_ids)
        except (TypeError, ValueError):
            raise _error("project sound configuration is invalid", "invalid_project_config") from None
        checks = (
            project_id in _code_tuple(self.project_ids),
            roster in _code_tuple(self.roster_presets),
            ambience in _code_tuple(self.ambience_presets),
            loudness in _code_tuple(self.loudness_presets),
            spatial in _code_tuple(self.spatial_presets),
            chain in _code_tuple(self.chain_presets),
            set(adapters) <= set(allowed_adapters),
        )
        if not all(checks):
            raise _error("project sound configuration is denied", "project_config_denied")
