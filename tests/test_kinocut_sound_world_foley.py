"""Foley resolver tests for the S8 world leaf.

Covers required rows:
* Foley resolver maps S4 cue ids to asset refs.
* unknown Foley cue fails closed.

Plus hardening: bindings built from S4 ``ParsedBeat`` rows; resolving a cue
whose asset license was revoked fails closed at use time.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kinocut_sound import AssetLicenseRef
from kinocut_sound.world import (
    AssetProvenance,
    CatalogAsset,
    FoleyBinding,
    FoleyBindingSpec,
    FoleyResolver,
    LicenseVerifier,
    WorldAssetCatalog,
    WorldAssetKind,
    WorldError,
    bindings_from_parsed_script,
)

_SHA = "sha256:" + "a" * 64
_OTHER = "sha256:" + "b" * 64


def _catalog_with_foley() -> tuple[WorldAssetCatalog, LicenseVerifier]:
    ref = AssetLicenseRef(license_id="foley_pack_1", asset_hash=_SHA)
    verifier = LicenseVerifier()
    verifier.register(ref)
    catalog = WorldAssetCatalog(license_verifier=verifier)
    catalog.register(
        CatalogAsset(
            asset_id="foley_door_close",
            kind=WorldAssetKind.FOLEY,
            duration_seconds=0.8,
            license_ref=ref,
            provenance=AssetProvenance(content_hash=_SHA, source_ref="foley/door_close.wav"),
            tags=("door", "interior"),
        )
    )
    return catalog, verifier


def test_foley_resolver_maps_s4_cue_id_to_catalog_asset():
    catalog, _ = _catalog_with_foley()
    resolver = FoleyResolver(
        catalog=catalog,
        bindings=(FoleyBindingSpec(cue_id="beat_0001_0001", asset_id="foley_door_close"),),
    )
    binding = resolver.resolve("beat_0001_0001")
    assert isinstance(binding, FoleyBinding)
    assert binding.cue_id == "beat_0001_0001"
    assert binding.asset_id == "foley_door_close"
    assert binding.asset_ref == "foley/door_close.wav"
    assert binding.asset_hash == _SHA
    assert binding.duration_seconds == pytest.approx(0.8)


def test_unknown_foley_cue_fails_closed():
    catalog, _ = _catalog_with_foley()
    resolver = FoleyResolver(catalog=catalog, bindings=())
    with pytest.raises(WorldError) as exc:
        resolver.resolve("beat_9999_9999")
    assert exc.value.code == "unknown_foley_cue"
    # Unbounded cue id is also rejected.
    with pytest.raises(WorldError) as exc:
        resolver.resolve("not a bounded id")
    assert exc.value.code == "unknown_foley_cue"
    assert not resolver.knows("beat_9999_9999")


def test_foley_resolver_rejects_binding_to_unknown_asset():
    catalog, _ = _catalog_with_foley()
    with pytest.raises(WorldError) as exc:
        FoleyResolver(
            catalog=catalog,
            bindings=(FoleyBindingSpec(cue_id="beat_0001_0001", asset_id="not_in_catalog"),),
        )
    assert exc.value.code == "unknown_asset"


def test_foley_use_fails_closed_when_license_revoked_after_binding():
    catalog, verifier = _catalog_with_foley()
    resolver = FoleyResolver(
        catalog=catalog,
        bindings=(FoleyBindingSpec(cue_id="beat_0001_0001", asset_id="foley_door_close"),),
    )
    # Initial resolve succeeds.
    assert resolver.resolve("beat_0001_0001").asset_id == "foley_door_close"
    # Revoke the license; subsequent use fails closed.
    verifier.revoke("foley_pack_1")
    with pytest.raises(WorldError) as exc:
        resolver.resolve("beat_0001_0001")
    assert exc.value.code == "unlicensed_asset"


def test_bindings_from_parsed_script_map_beat_ids_to_asset_ids():
    beats = (
        SimpleNamespace(
            beat_id="beat_0001_0001",
            asset_ref="foley/door_close.wav",
            kind="foley",
        ),
        SimpleNamespace(
            beat_id="beat_0002_0001",
            asset_ref="foley/glass_clink.wav",
            kind="foley",
        ),
        # A beat whose asset_ref is not in the map is skipped (catalog is the
        # authority on which assets are usable).
        SimpleNamespace(
            beat_id="beat_0003_0001",
            asset_ref="foley/unknown.wav",
            kind="foley",
        ),
    )
    specs = bindings_from_parsed_script(
        foley_beats=beats,
        asset_id_for={
            "foley/door_close.wav": "foley_door_close",
            "foley/glass_clink.wav": "foley_glass_clink",
        },
    )
    assert [spec.cue_id for spec in specs] == ["beat_0001_0001", "beat_0002_0001"]
    assert specs[0].asset_id == "foley_door_close"


def test_bindings_from_parsed_script_rejects_path_traversal_and_duplicates():
    with pytest.raises(WorldError) as exc:
        bindings_from_parsed_script(
            foley_beats=(SimpleNamespace(beat_id="beat_x", asset_ref="../escape.wav", kind="foley"),),
            asset_id_for={"../escape.wav": "asset_x"},
        )
    assert exc.value.code == "unknown_foley_cue"
    with pytest.raises(WorldError) as exc:
        bindings_from_parsed_script(
            foley_beats=(
                SimpleNamespace(beat_id="beat_dup", asset_ref="foley/a.wav", kind="foley"),
                SimpleNamespace(beat_id="beat_dup", asset_ref="foley/a.wav", kind="foley"),
            ),
            asset_id_for={"foley/a.wav": "asset_a"},
        )
    assert exc.value.code == "unknown_foley_cue"
