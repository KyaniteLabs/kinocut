"""Foley cue resolver that maps S4 cue ids to licensed catalog asset refs.

W4.4: Foley triggering at script moments resolved against S4 cue ids. The S4
script parser produces Foley beats, each carrying a ``beat_id`` (the S4 cue
id) and an ``asset_ref``/``asset_hash`` pair. This module binds those cue ids
to licensed catalog assets so the S9 assembly leaf can place each Foley hit
on the timeline without re-resolving the catalog or the license.

Fail-closed behaviour: resolving an unknown cue id raises
:class:`WorldError` with code ``unknown_foley_cue``; resolving a cue whose
catalog asset is not currently licensed raises ``unlicensed_asset``.

Design references (sonic-world design):
* W4.4 — Foley triggering at script moments.
* G03 / W3.x — cues derived from script beats (S4).
* G05 — immutable asset provenance with content hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256, location_violation
from kinocut_sound.world._errors import world_error
from kinocut_sound.world.catalog import CatalogAsset, WorldAssetCatalog

_MAX_FOLEY_BINDINGS = 4096


class FoleyBindingSpec(FrozenModel):
    """Declared binding of one S4 Foley cue id to a catalog asset id."""

    cue_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)

    @field_validator("cue_id", "asset_id")
    @classmethod
    def _ids_bounded(cls, value: str) -> str:
        return BoundedCode(value)


@dataclass(frozen=True)
class FoleyBinding:
    """Resolved Foley cue → licensed catalog asset (hash + duration)."""

    cue_id: str
    asset_id: str
    asset_ref: str
    asset_hash: Sha256
    duration_seconds: float


class FoleyResolver:
    """Maps S4 Foley cue ids to licensed catalog assets (fail-closed)."""

    __slots__ = ("_bindings", "_catalog")

    def __init__(
        self,
        *,
        catalog: WorldAssetCatalog,
        bindings: tuple[FoleyBindingSpec, ...] = (),
    ) -> None:
        self._catalog = catalog
        self._bindings: dict[str, str] = {}
        for spec in bindings:
            self.register(spec)

    def register(self, spec: FoleyBindingSpec) -> None:
        if len(self._bindings) >= _MAX_FOLEY_BINDINGS:
            raise world_error(
                "Foley binding table exceeds its ceiling",
                "unknown_foley_cue",
            )
        checked_cue = BoundedCode(spec.cue_id)
        checked_asset = BoundedCode(spec.asset_id)
        if not self._catalog.contains(checked_asset):
            raise world_error(
                "Foley binding references an unknown catalog asset",
                "unknown_asset",
            )
        if checked_cue in self._bindings:
            raise world_error(
                "Foley cue id is already bound",
                "unknown_foley_cue",
            )
        self._bindings[checked_cue] = checked_asset

    def knows(self, cue_id: str) -> bool:
        try:
            checked = BoundedCode(cue_id)
        except (TypeError, ValueError):
            return False
        return checked in self._bindings

    def resolve(self, cue_id: str) -> FoleyBinding:
        """Resolve ``cue_id`` to a licensed catalog asset (fail-closed)."""

        checked_cue = self._checked_cue(cue_id)
        asset_id = self._bindings.get(checked_cue)
        if asset_id is None:
            raise world_error(
                "Foley cue id is not bound to a catalog asset",
                "unknown_foley_cue",
            )
        asset = self._catalog.require_licensed(asset_id)
        return self._to_binding(checked_cue, asset)

    def resolve_many(self, cue_ids: tuple[str, ...]) -> tuple[FoleyBinding, ...]:
        return tuple(self.resolve(cue_id) for cue_id in cue_ids)

    def cue_ids(self) -> tuple[str, ...]:
        try:
            items = tuple(islice(iter(self._bindings.keys()), _MAX_FOLEY_BINDINGS + 1))
        except Exception:  # pragma: no cover - defensive: bindings is owned here.
            return ()
        return tuple(sorted(items))

    @staticmethod
    def _to_binding(cue_id: str, asset: CatalogAsset) -> FoleyBinding:
        return FoleyBinding(
            cue_id=cue_id,
            asset_id=asset.asset_id,
            asset_ref=asset.provenance.source_ref,
            asset_hash=asset.provenance.content_hash,
            duration_seconds=asset.duration_seconds,
        )

    @staticmethod
    def _checked_cue(cue_id: str) -> str:
        try:
            return BoundedCode(cue_id)
        except (TypeError, ValueError):
            raise world_error(
                "Foley cue id must be a bounded code",
                "unknown_foley_cue",
            ) from None


def bindings_from_parsed_script(
    *,
    foley_beats: tuple[object, ...],
    asset_id_for: dict[str, str],
) -> tuple[FoleyBindingSpec, ...]:
    """Build binding specs from S4 ``ParsedBeat`` rows of kind ``foley``.

    Each beat must expose ``beat_id`` (the S4 cue id) and ``asset_ref`` (the
    project-relative asset location). ``asset_id_for`` maps the asset_ref to a
    catalog asset id. A beat whose asset_ref is not in the map is skipped —
    the catalog is the authority on which assets are usable.
    """

    specs: list[FoleyBindingSpec] = []
    seen: set[str] = set()
    for beat in foley_beats:
        beat_id = getattr(beat, "beat_id", None)
        asset_ref = getattr(beat, "asset_ref", None)
        if not isinstance(beat_id, str) or not isinstance(asset_ref, str):
            raise world_error(
                "Foley beat must carry a bounded beat_id and asset_ref",
                "unknown_foley_cue",
            )
        reason = location_violation(asset_ref)
        if reason is not None:
            raise world_error(
                f"Foley asset_ref {reason}",
                "unknown_foley_cue",
            )
        if asset_ref not in asset_id_for:
            continue
        BoundedCode(beat_id)
        if beat_id in seen:
            raise world_error(
                "Foley beat ids must be unique",
                "unknown_foley_cue",
            )
        seen.add(beat_id)
        specs.append(FoleyBindingSpec(cue_id=beat_id, asset_id=asset_id_for[asset_ref]))
    return tuple(specs)
