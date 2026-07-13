"""Licensed ambient asset catalog and lookup for the S8 world leaf.

The catalog stores ambient bed, layer, Foley, and texture assets under stable
bounded ids. Every asset carries a typed :class:`AssetLicenseRef` and an
immutable :class:`AssetProvenance` record (content hash, optional generator
descriptor, optional prompt hash). Use of an asset is fail-closed: a caller
that resolves an asset whose license is not currently authorized sees a
:class:`WorldError` with code ``unlicensed_asset``.

The catalog never embeds raw prompt text, transcripts, host paths, or model
file locations — only bounded ids and SHA-256 hashes leave the module.

Design references (sonic-world design):
* W4.1 / G04 — licensed catalog required for bed generation and placement.
* G05 — immutable asset provenance with content hashes (no raw protected text).
* Errors, Privacy & Security — fail-closed authorization at use time.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from kinocut_sound._canonical import (
    BoundedCode,
    FrozenModel,
    Sha256,
    location_violation,
)
from kinocut_sound.limits import MIN_TIME_SECONDS
from kinocut_sound.sound_plan import AssetLicenseRef
from kinocut_sound.world._errors import world_error
from kinocut_sound.world.license import LicenseVerifier, verify_provenance_license

# World-specific ceilings (the S8 leaf cannot touch the shared limits module).
_MAX_CATALOG_ASSETS = 4096
_MAX_ASSET_TAGS = 32


class WorldAssetKind(StrEnum):
    """Closed set of world-catalog asset kinds."""

    BED = "bed"
    LAYER = "layer"
    FOLEY = "foley"
    TEXTURE = "texture"


class AssetProvenance(FrozenModel):
    """Immutable provenance for one catalog asset — hashes only, never raw text."""

    content_hash: Sha256
    source_ref: str = Field(min_length=1)
    generator_descriptor: str | None = None
    prompt_hash: Sha256 | None = None

    @field_validator("source_ref")
    @classmethod
    def _source_ref_is_project_relative(cls, value: str) -> str:
        reason = location_violation(value)
        if reason is not None:
            raise ValueError(f"source_ref {reason}")
        return value

    @field_validator("generator_descriptor")
    @classmethod
    def _generator_descriptor_bounded(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else value


class CatalogAsset(FrozenModel):
    """One licensed, provenance-bound world asset stored under a stable id."""

    asset_id: str = Field(min_length=1)
    kind: WorldAssetKind
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS)
    license_ref: AssetLicenseRef
    provenance: AssetProvenance
    tags: tuple[str, ...] = ()

    @field_validator("asset_id")
    @classmethod
    def _asset_id_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("tags")
    @classmethod
    def _tags_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAX_ASSET_TAGS:
            raise ValueError("asset tag count exceeds ceiling")
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("asset tags must be unique")
        return value

    @field_validator("duration_seconds")
    @classmethod
    def _duration_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("duration_seconds must not be a boolean")
        return value


def _snapshot(asset: CatalogAsset) -> CatalogAsset:
    payload = asset.model_dump(mode="python")
    return CatalogAsset.model_validate(payload)


class WorldAssetCatalog:
    """Sealed, fail-closed store of licensed world assets keyed by stable id."""

    __slots__ = ("_assets", "_license")

    def __init__(self, *, license_verifier: LicenseVerifier) -> None:
        self._assets: dict[str, CatalogAsset] = {}
        self._license = license_verifier

    @property
    def license_verifier(self) -> LicenseVerifier:
        return self._license

    def register(self, asset: CatalogAsset) -> CatalogAsset:
        """Store ``asset`` under its id after snapshot revalidation (idempotent)."""

        snapshot = _snapshot(asset)
        if snapshot.asset_id in self._assets:
            raise world_error(
                "asset id is already registered",
                "catalog_invalid",
            )
        if len(self._assets) >= _MAX_CATALOG_ASSETS:
            raise world_error(
                "catalog exceeds its asset ceiling",
                "catalog_invalid",
            )
        # The license ref must be currently authoritative at register time so a
        # stale catalog row cannot be seeded without a live license.
        self._license.require_authorized(snapshot.license_ref)
        self._assets[snapshot.asset_id] = snapshot
        return snapshot

    def contains(self, asset_id: str) -> bool:
        try:
            checked = BoundedCode(asset_id)
        except (TypeError, ValueError):
            return False
        return checked in self._assets

    def get(self, asset_id: str) -> CatalogAsset:
        snapshot = self._assets.get(self._checked_id(asset_id))
        if snapshot is None:
            raise world_error("asset is not in the catalog", "unknown_asset")
        return snapshot

    def require_licensed(self, asset_id: str) -> CatalogAsset:
        """Return the asset, re-verifying its license at use time (fail-closed)."""

        snapshot = self.get(asset_id)
        verdict = verify_provenance_license(
            license_ref=snapshot.license_ref,
            provenance_hash=snapshot.provenance.content_hash,
            verifier=self._license,
        )
        if not verdict.authorized:
            raise world_error(
                "asset license is not currently authorized",
                "unlicensed_asset",
            )
        return snapshot

    def find(
        self,
        *,
        kind: WorldAssetKind | None = None,
        tag: str | None = None,
    ) -> tuple[CatalogAsset, ...]:
        """Return a stable, asset-id-sorted snapshot matching the filters."""

        if tag is not None:
            BoundedCode(tag)
        matches: list[CatalogAsset] = []
        for asset in self._assets.values():
            if kind is not None and asset.kind is not kind:
                continue
            if tag is not None and tag not in asset.tags:
                continue
            matches.append(asset)
        matches.sort(key=lambda item: item.asset_id)
        return tuple(matches)

    def asset_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._assets))

    @staticmethod
    def _checked_id(asset_id: str) -> str:
        try:
            return BoundedCode(asset_id)
        except (TypeError, ValueError):
            raise world_error(
                "asset identifier must be a bounded code",
                "catalog_invalid",
            ) from None
