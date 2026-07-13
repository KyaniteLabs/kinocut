"""License verification helpers for world/ambience assets.

Ambient beds, layers, and Foley assets are usable only when their declared
license reference is current and covers the asset's content hash. This module
owns the contract-side verification; it does not embed raw license text,
credential handles, or host paths. Verification is fail-closed: an unknown,
expired, or mismatched license yields :class:`LicenseVerdict.authorized` =
``False``, and a caller that attempts to *use* such an asset sees a
:class:`kinocut_sound.world._errors.WorldError` with code ``unlicensed_asset``.

Design references (sonic-world design):
* Core contracts §"Receipt & Provenance" — license refs are typed hashes.
* W4.1 / G04 — licensed catalog required before bed generation/audition.
* G05 — immutable asset provenance with content hashes.
"""

from __future__ import annotations

from dataclasses import dataclass

from kinocut_sound._canonical import BoundedCode, Sha256
from kinocut_sound.sound_plan import AssetLicenseRef
from kinocut_sound.world._errors import world_error

# Bounded ceiling so a hostile license table cannot exhaust memory. World-
# specific (not added to the shared limits module, which the S8 leaf cannot
# touch).
_MAX_LICENSE_ENTRIES = 4096


@dataclass(frozen=True)
class LicenseVerdict:
    """Fail-closed verdict for one ``(license_id, asset_hash)`` pair."""

    authorized: bool
    license_id: str | None
    reason_code: str | None

    @classmethod
    def authorized_verdict(cls, license_id: str) -> LicenseVerdict:
        return cls(authorized=True, license_id=license_id, reason_code=None)

    @classmethod
    def denied_verdict(cls, *, reason_code: str, license_id: str | None) -> LicenseVerdict:
        return cls(authorized=False, license_id=license_id, reason_code=reason_code)


class LicenseVerifier:
    """Bounded in-memory registry of currently-authoritative license refs.

    The verifier records which ``(license_id, asset_hash)`` pairs are currently
    accepted. Absence is always fail-closed: a license id that is not registered
    is not authorized, regardless of what a catalog entry claims. This keeps a
    cached or stale catalog row from authorizing use after a license has been
    revoked or expired upstream.
    """

    __slots__ = ("_authorized",)

    def __init__(self) -> None:
        self._authorized: dict[str, set[str]] = {}

    def register(self, ref: AssetLicenseRef) -> None:
        """Mark ``ref`` as currently authoritative (idempotent)."""

        BoundedCode(ref.license_id)
        self._bounded_id(ref.license_id)
        bucket = self._authorized.setdefault(ref.license_id, set())
        bucket.add(ref.asset_hash)
        self._check_ceiling()

    def revoke(self, license_id: str) -> None:
        """Drop every hash covered by ``license_id`` (fail-closed if unknown)."""

        BoundedCode(license_id)
        self._authorized.pop(license_id, None)

    def verify(self, ref: AssetLicenseRef) -> LicenseVerdict:
        """Return the current verdict for ``ref`` — fail-closed when unknown."""

        BoundedCode(ref.license_id)
        bucket = self._authorized.get(ref.license_id)
        if bucket is None:
            return LicenseVerdict.denied_verdict(reason_code="license_unknown", license_id=ref.license_id)
        if ref.asset_hash not in bucket:
            return LicenseVerdict.denied_verdict(reason_code="asset_hash_mismatch", license_id=ref.license_id)
        return LicenseVerdict.authorized_verdict(ref.license_id)

    def require_authorized(self, ref: AssetLicenseRef) -> LicenseVerdict:
        """Verify and raise :class:`WorldError` (unlicensed_asset) when denied."""

        verdict = self.verify(ref)
        if not verdict.authorized:
            raise world_error(
                "asset license is not currently authorized",
                "unlicensed_asset",
            )
        return verdict

    @staticmethod
    def _bounded_id(license_id: str) -> None:
        # Reject import/class-path-shaped ids defensively; the AssetLicenseRef
        # already bounds the shape, but double-check at the registry boundary.
        if ":" in license_id or "." in license_id:
            raise world_error("license id must be a bounded code", "catalog_invalid")

    def _check_ceiling(self) -> None:
        total = sum(len(bucket) for bucket in self._authorized.values())
        if total > _MAX_LICENSE_ENTRIES:
            raise world_error(
                "license registry exceeds its ceiling",
                "catalog_invalid",
            )


def verify_provenance_license(
    *,
    license_ref: AssetLicenseRef,
    provenance_hash: Sha256,
    verifier: LicenseVerifier,
) -> LicenseVerdict:
    """Cross-check a catalog asset's provenance hash against its license ref.

    The license covers the *asset content* hash, but a provenance hash that
    derives from the same content must also be present. This helper enforces
    that the license-authorized asset hash is non-empty and that the verifier
    accepts the ref. It does not embed the provenance hash in the license
    decision; it only ensures the caller actually supplied one.
    """

    if not provenance_hash:
        return LicenseVerdict.denied_verdict(reason_code="provenance_missing", license_id=license_ref.license_id)
    return verifier.verify(license_ref)
