"""``kinocut_sound.voice_consistency`` — voice consistency leaf (S10).

A sidecar package that implements the Sonic World voice-consistency leaf:

* Versioned :class:`VoiceProfile` model.
* In-memory :class:`ProfileLibrary` with deterministic digest.
* Backend-neutral D42 ports plus :class:`FakeD42Port` for tests.
* Style/identity metrics consumed from the D42 ports.
* A/B reel descriptors from batch outputs.
* Cross-episode drift detection and :func:`realign`.
* Cross-character spectral distinctiveness and collision detection.
* Batch re-generation of lines referencing an updated profile.

The package imports nothing from any ``kinocut.*`` runtime module.
"""

from __future__ import annotations

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_COLLISION_DETECTED,
    CONSISTENCY_D42_UNAVAILABLE,
    CONSISTENCY_DRIFT_DETECTED,
    CONSISTENCY_LIBRARY_INVALID,
    CONSISTENCY_METRIC_INVALID,
    CONSISTENCY_PROFILE_INVALID,
    CONSISTENCY_REGENERATION_FAILED,
    VoiceConsistencyError,
    bounded_consistency_error,
    consistency_error,
)
from kinocut_sound.voice_consistency.ab_reel import AbReel, build_ab_reel
from kinocut_sound.voice_consistency.d42_port import (
    FakeD42Port,
    IdentityCheckResult,
    IdentityCheckSpec,
    IdentityPort,
    LocalFakeIdentityAdapter,
    LocalFakeStyleAdapter,
    StyleCheckResult,
    StyleCheckSpec,
    StylePort,
    UnavailableIdentityAdapter,
    UnavailableStyleAdapter,
    default_fake_d42_port,
)
from kinocut_sound.voice_consistency.distinctiveness import (
    DistinctivenessReport,
    detect_collisions,
    spectral_distance,
)
from kinocut_sound.voice_consistency.drift import (
    DriftEvent,
    DriftReport,
    detect_cross_episode_drift,
    realign,
)
from kinocut_sound.voice_consistency.library import ProfileLibrary
from kinocut_sound.voice_consistency.metrics import StyleMetrics, identity_similarity, style_check
from kinocut_sound.voice_consistency.profile import VoiceProfile
from kinocut_sound.voice_consistency.regeneration import (
    RegenerationReport,
    regenerate_for_profile,
)

__version__ = "0.1.0"

__all__ = [
    "AbReel",
    "CONSISTENCY_COLLISION_DETECTED",
    "CONSISTENCY_D42_UNAVAILABLE",
    "CONSISTENCY_DRIFT_DETECTED",
    "CONSISTENCY_LIBRARY_INVALID",
    "CONSISTENCY_METRIC_INVALID",
    "CONSISTENCY_PROFILE_INVALID",
    "CONSISTENCY_REGENERATION_FAILED",
    "DistinctivenessReport",
    "DriftEvent",
    "DriftReport",
    "FakeD42Port",
    "IdentityCheckResult",
    "IdentityCheckSpec",
    "IdentityPort",
    "LocalFakeIdentityAdapter",
    "LocalFakeStyleAdapter",
    "ProfileLibrary",
    "RegenerationReport",
    "StyleCheckResult",
    "StyleCheckSpec",
    "StyleMetrics",
    "StylePort",
    "UnavailableIdentityAdapter",
    "UnavailableStyleAdapter",
    "VoiceConsistencyError",
    "VoiceProfile",
    "bounded_consistency_error",
    "build_ab_reel",
    "consistency_error",
    "default_fake_d42_port",
    "detect_collisions",
    "detect_cross_episode_drift",
    "identity_similarity",
    "realign",
    "regenerate_for_profile",
    "spectral_distance",
    "style_check",
]
