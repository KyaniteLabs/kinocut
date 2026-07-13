"""In-memory versioned voice profile library.

The library stores :class:`VoiceProfile` instances keyed by ``profile_id``
and ``version``. Persistence promotion to disk or S3 is controller-owned;
this module provides the canonical in-memory contract, deterministic digest,
and version-history semantics used by higher-level controllers.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from kinocut_sound._canonical import Sha256, canonical_digest

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_LIBRARY_INVALID,
    CONSISTENCY_PROFILE_INVALID,
    VoiceConsistencyError,
    bounded_consistency_error,
)
from kinocut_sound.voice_consistency.profile import VoiceProfile


class ProfileLibrary:
    """Sealed, in-memory versioned profile library.

    Profiles are stored immutably by ``(profile_id, version)``. A later
    :meth:`save` for the same ``(profile_id, version)`` pair is rejected so
    an accidental overwrite cannot silently mutate an accepted profile.
    """

    __slots__ = ("_profiles",)

    def __init__(self, profiles: Mapping[str, Mapping[int, VoiceProfile]] | None = None) -> None:
        if profiles is None:
            self._profiles: dict[str, dict[int, VoiceProfile]] = {}
            return
        if not isinstance(profiles, Mapping):
            raise bounded_consistency_error(
                "library source must be a mapping",
                CONSISTENCY_LIBRARY_INVALID,
            )
        copied: dict[str, dict[int, VoiceProfile]] = {}
        for profile_id, versions in profiles.items():
            if not isinstance(versions, Mapping):
                raise bounded_consistency_error(
                    "library versions must be a mapping",
                    CONSISTENCY_LIBRARY_INVALID,
                )
            copied[profile_id] = dict(versions)
        self._profiles = copied

    def save(self, profile: VoiceProfile) -> None:
        """Store ``profile``; reject duplicate versions."""

        if not isinstance(profile, VoiceProfile):
            raise bounded_consistency_error(
                "library save requires a VoiceProfile",
                CONSISTENCY_PROFILE_INVALID,
            )
        versions = self._profiles.setdefault(profile.profile_id, {})
        if profile.version in versions:
            raise bounded_consistency_error(
                "profile version already exists in library",
                CONSISTENCY_LIBRARY_INVALID,
            )
        versions[profile.version] = profile

    def load(self, profile_id: str, *, version: int | None = None) -> VoiceProfile:
        """Return the latest profile for ``profile_id`` or a specific version."""

        versions = self._profiles.get(profile_id)
        if versions is None:
            raise bounded_consistency_error(
                "profile id not found in library",
                CONSISTENCY_LIBRARY_INVALID,
            )
        if version is None:
            version = max(versions)
        profile = versions.get(version)
        if profile is None:
            raise bounded_consistency_error(
                "profile version not found in library",
                CONSISTENCY_LIBRARY_INVALID,
            )
        return profile

    def list(self, profile_id: str) -> tuple[int, ...]:
        """Return sorted versions for ``profile_id``."""

        versions = self._profiles.get(profile_id)
        if versions is None:
            return ()
        return tuple(sorted(versions))

    def list_ids(self) -> tuple[str, ...]:
        """Return sorted profile ids in the library."""

        return tuple(sorted(self._profiles))

    def has(self, profile_id: str, *, version: int | None = None) -> bool:
        """Return whether ``profile_id`` (and optionally version) is stored."""

        versions = self._profiles.get(profile_id)
        if versions is None:
            return False
        if version is None:
            return len(versions) > 0
        return version in versions

    def digest(self) -> Sha256:
        """Return a canonical SHA-256 over the whole library contents."""

        payload: dict[str, object] = {
            "profile_ids": list(self.list_ids()),
            "profiles": [
                {
                    "profile_id": profile_id,
                    "versions": [
                        {
                            "version": profile.version,
                            "slot_id": profile.slot_id,
                            "reference_hash": profile.reference_hash,
                            "consent_grant_ref": profile.consent_grant_ref,
                            "fingerprint": profile.fingerprint.digest(),
                        }
                        for version in sorted(versions)
                        for profile in (versions[version],)
                    ],
                }
                for profile_id in sorted(self._profiles)
                for versions in (self._profiles[profile_id],)
            ],
        }
        return canonical_digest(payload)

    def to_mapping(self) -> Mapping[str, Mapping[int, VoiceProfile]]:
        """Return a read-only view of the stored profiles."""

        return MappingProxyType(
            {pid: MappingProxyType(dict(vers)) for pid, vers in self._profiles.items()}
        )
