"""Catalog and license tests for the S8 world leaf.

Covers required rows:
* catalog stores/retrieves assets with license and provenance.
* unlicensed asset use fails closed at use time.
* license revocation flips a previously-licensed asset to fail-closed.
* hostile asset payloads (path traversal, oversized tags, duplicate ids) fail.
* receipts/serialized assets never leak host paths or raw prompt text.
"""

from __future__ import annotations

import pytest

from kinocut_sound import AssetLicenseRef
from kinocut_sound.world import (
    AssetProvenance,
    CatalogAsset,
    LicenseVerifier,
    WorldAssetCatalog,
    WorldAssetKind,
    WorldError,
)

_SHA = "sha256:" + "a" * 64
_OTHER_HASH = "sha256:" + "b" * 64


def _verifier(*refs: AssetLicenseRef) -> LicenseVerifier:
    verifier = LicenseVerifier()
    for ref in refs:
        verifier.register(ref)
    return verifier


def _bed_asset(
    asset_id: str = "bed_common_room",
    *,
    content_hash: str = _SHA,
    license_id: str = "cc_by_4",
    asset_hash: str = _SHA,
    source_ref: str = "beds/common_room.wav",
    duration_seconds: float = 120.0,
    prompt_hash: str | None = None,
) -> CatalogAsset:
    return CatalogAsset(
        asset_id=asset_id,
        kind=WorldAssetKind.BED,
        duration_seconds=duration_seconds,
        license_ref=AssetLicenseRef(license_id=license_id, asset_hash=asset_hash),
        provenance=AssetProvenance(
            content_hash=content_hash,
            source_ref=source_ref,
            prompt_hash=prompt_hash,
        ),
    )


def test_catalog_stores_and_retrieves_asset_with_license_and_provenance():
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    catalog = WorldAssetCatalog(license_verifier=_verifier(ref))
    asset = _bed_asset()
    snapshot = catalog.register(asset)
    # Round-trip identity (revalidated snapshot).
    assert snapshot.asset_id == "bed_common_room"
    assert snapshot.license_ref.license_id == "cc_by_4"
    assert snapshot.provenance.source_ref == "beds/common_room.wav"
    # Retrieve.
    assert catalog.contains("bed_common_room")
    fetched = catalog.get("bed_common_room")
    assert fetched.provenance.content_hash == _SHA
    assert fetched.duration_seconds == 120.0
    # Licensed use path returns the same asset after re-verification.
    assert catalog.require_licensed("bed_common_room").asset_id == "bed_common_room"


def test_catalog_find_filters_by_kind_and_tag_stably():
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    other_hash = "sha256:" + "c" * 64
    other_ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=other_hash)
    catalog = WorldAssetCatalog(license_verifier=_verifier(ref, other_ref))
    catalog.register(
        _bed_asset("bed_a", content_hash=_SHA, asset_hash=_SHA).model_copy(update={"tags": ("calm", "indoor")})
    )
    catalog.register(
        CatalogAsset(
            asset_id="layer_wind",
            kind=WorldAssetKind.LAYER,
            duration_seconds=60.0,
            license_ref=other_ref,
            provenance=AssetProvenance(content_hash=other_hash, source_ref="layers/wind.wav"),
            tags=("calm",),
        )
    )
    beds = catalog.find(kind=WorldAssetKind.BED)
    assert [a.asset_id for a in beds] == ["bed_a"]
    calm = catalog.find(tag="calm")
    assert {a.asset_id for a in calm} == {"bed_a", "layer_wind"}
    # Stable: repeat returns the same ordering.
    assert catalog.find(tag="calm") == calm


def test_unlicensed_asset_use_fails_closed():
    # The catalog is seeded with a license, then the license is revoked before use.
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    verifier = _verifier(ref)
    catalog = WorldAssetCatalog(license_verifier=verifier)
    catalog.register(_bed_asset())
    # Revoke after registration — the catalog row is now stale.
    verifier.revoke("cc_by_4")
    with pytest.raises(WorldError) as exc:
        catalog.require_licensed("bed_common_room")
    assert exc.value.code == "unlicensed_asset"
    # A plain get() still returns the (now-unusable) row; use is what fails.
    assert catalog.get("bed_common_room").asset_id == "bed_common_room"


def test_registering_an_asset_without_a_live_license_fails_closed():
    # No license registered at all.
    catalog = WorldAssetCatalog(license_verifier=LicenseVerifier())
    with pytest.raises(WorldError) as exc:
        catalog.register(_bed_asset())
    assert exc.value.code == "unlicensed_asset"


def test_duplicate_asset_id_is_rejected():
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    catalog = WorldAssetCatalog(license_verifier=_verifier(ref))
    catalog.register(_bed_asset())
    with pytest.raises(WorldError) as exc:
        catalog.register(_bed_asset())
    assert exc.value.code == "catalog_invalid"


def test_hostile_asset_payloads_fail_bounded():
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    catalog = WorldAssetCatalog(license_verifier=_verifier(ref))
    # Path-traversing source_ref is rejected by the location validator.
    with pytest.raises(Exception):
        CatalogAsset(
            asset_id="bed_x",
            kind=WorldAssetKind.BED,
            duration_seconds=10.0,
            license_ref=ref,
            provenance=AssetProvenance(content_hash=_SHA, source_ref="../escape.wav"),
        )
    # Unknown asset id lookup fails closed (not KeyError).
    with pytest.raises(WorldError) as exc:
        catalog.get("not_in_catalog")
    assert exc.value.code == "unknown_asset"
    # URL-shaped source_ref is rejected.
    with pytest.raises(Exception):
        AssetProvenance(content_hash=_SHA, source_ref="https://example/bed.wav")


def test_serialized_asset_never_leaks_host_paths_or_raw_prompt():
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    catalog = WorldAssetCatalog(license_verifier=_verifier(ref))
    asset = catalog.register(_bed_asset(prompt_hash=_OTHER_HASH))
    payload = asset.model_dump_json()
    for forbidden in ("/home/", "/etc/", "/Users/", "password", "raw_prompt"):
        assert forbidden not in payload
    # Only the prompt *hash* is present; never raw text.
    assert _OTHER_HASH in payload


def test_license_verifier_denies_unknown_and_mismatched_hashes():
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    verifier = _verifier(ref)
    # Unknown license id.
    verdict = verifier.verify(AssetLicenseRef(license_id="cc_by_nc", asset_hash=_SHA))
    assert not verdict.authorized
    assert verdict.reason_code == "license_unknown"
    # Mismatched asset hash under a known license id.
    mismatched = verifier.verify(AssetLicenseRef(license_id="cc_by_4", asset_hash=_OTHER_HASH))
    assert not mismatched.authorized
    assert mismatched.reason_code == "asset_hash_mismatch"


def test_license_id_with_path_shape_is_rejected():
    verifier = LicenseVerifier()
    with pytest.raises(WorldError) as exc:
        verifier.register(AssetLicenseRef(license_id="path.like", asset_hash=_SHA))
    assert exc.value.code == "catalog_invalid"


def test_catalog_ceiling_rejects_oversized_seed(monkeypatch):
    import kinocut_sound.world.catalog as catalog_mod

    monkeypatch.setattr(catalog_mod, "_MAX_CATALOG_ASSETS", 1)
    ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_SHA)
    other_ref = AssetLicenseRef(license_id="cc_by_4", asset_hash=_OTHER_HASH)
    catalog = WorldAssetCatalog(license_verifier=_verifier(ref, other_ref))
    catalog.register(_bed_asset("bed_a"))
    with pytest.raises(WorldError) as exc:
        catalog.register(_bed_asset("bed_b", content_hash=_OTHER_HASH, asset_hash=_OTHER_HASH))
    assert exc.value.code == "catalog_invalid"
