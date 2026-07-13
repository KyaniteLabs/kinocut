"""Cross-episode drift detection and re-alignment surface.

Drift detection compares each episode's lines against a reference profile
via the fake D42 style port. The :func:`realign` helper produces a new
profile version pointed at an updated reference hash.
"""

from __future__ import annotations

from dataclasses import dataclass

from kinocut_sound._canonical import Sha256, canonical_digest
from kinocut_sound.lines import Line
from kinocut_sound.sound_plan import SoundPlan

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_DRIFT_DETECTED,
    CONSISTENCY_METRIC_INVALID,
    CONSISTENCY_PROFILE_INVALID,
    bounded_consistency_error,
)
from kinocut_sound.voice_consistency.d42_port import FakeD42Port
from kinocut_sound.voice_consistency.metrics import style_check
from kinocut_sound.voice_consistency.profile import VoiceProfile


@dataclass(frozen=True)
class DriftEvent:
    """One detected drift event for a profile/episode pair."""

    profile_id: str
    episode_id: str
    line_id: str
    audio_hash: Sha256
    reference_hash: Sha256
    similarity: float
    threshold: float


@dataclass(frozen=True)
class DriftReport:
    """Aggregate drift report across episodes for a profile."""

    profile_id: str
    threshold: float
    events: tuple[DriftEvent, ...]
    has_drift: bool


def _extract_lines_for_profile(
    episodes: tuple[SoundPlan, ...],
    profile_id: str,
) -> tuple[tuple[str, Line], ...]:
    """Return ``(episode_id, line)`` tuples referencing ``profile_id``."""

    found: list[tuple[str, Line]] = []
    for episode in episodes:
        if not isinstance(episode, SoundPlan):
            raise bounded_consistency_error(
                "episodes must be SoundPlan instances",
                CONSISTENCY_METRIC_INVALID,
            )
        for line in episode.lines:
            if line.profile.profile_id == profile_id:
                found.append((episode.episode_id, line))
    return tuple(found)


def _make_event(
    *,
    profile_id: str,
    episode_id: str,
    line: Line,
    port: FakeD42Port,
    reference_hash: Sha256,
    threshold: float,
) -> DriftEvent | None:
    """Return a DriftEvent when ``line`` drifts below ``threshold``."""

    metrics = style_check(
        port=port,
        profile_id=profile_id,
        audio_hash=line.text_hash,
        reference_hash=reference_hash,
        threshold=threshold,
    )
    if not metrics.drift:
        return None
    return DriftEvent(
        profile_id=profile_id,
        episode_id=episode_id,
        line_id=line.line_id,
        audio_hash=line.text_hash,
        reference_hash=reference_hash,
        similarity=metrics.similarity,
        threshold=threshold,
    )


def detect_cross_episode_drift(
    *,
    profile: VoiceProfile,
    episodes: tuple[SoundPlan, ...],
    port: FakeD42Port,
    threshold: float = 1.0,
) -> DriftReport:
    """Detect per-line style drift across episodes for ``profile``."""

    if not isinstance(profile, VoiceProfile):
        raise bounded_consistency_error(
            "profile must be a VoiceProfile",
            CONSISTENCY_PROFILE_INVALID,
        )
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise bounded_consistency_error(
            "threshold must be a number",
            CONSISTENCY_METRIC_INVALID,
        )
    if not 0.0 <= threshold <= 1.0:
        raise bounded_consistency_error(
            "threshold must be in [0.0, 1.0]",
            CONSISTENCY_METRIC_INVALID,
        )
    events: list[DriftEvent] = []
    for episode_id, line in _extract_lines_for_profile(episodes, profile.profile_id):
        event = _make_event(
            profile_id=profile.profile_id,
            episode_id=episode_id,
            line=line,
            port=port,
            reference_hash=profile.reference_hash,
            threshold=threshold,
        )
        if event is not None:
            events.append(event)
    return DriftReport(
        profile_id=profile.profile_id,
        threshold=float(threshold),
        events=tuple(events),
        has_drift=len(events) > 0,
    )


def realign(
    profile: VoiceProfile,
    *,
    reference_wav_hash: Sha256,
) -> VoiceProfile:
    """Return a new profile version aligned to ``reference_wav_hash``.

    The returned profile bumps the version, updates ``reference_hash``, and
    keeps all other fields (slot, consent, fingerprint) unchanged so the
    re-aligned identity is auditable.
    """

    if not isinstance(profile, VoiceProfile):
        raise bounded_consistency_error(
            "realign requires a VoiceProfile",
            CONSISTENCY_PROFILE_INVALID,
        )
    return VoiceProfile(
        profile_id=profile.profile_id,
        version=profile.version + 1,
        slot_id=profile.slot_id,
        reference_hash=reference_wav_hash,
        provenance=profile.provenance,
        defaults=profile.defaults,
        fingerprint=profile.fingerprint,
        consent_grant_ref=profile.consent_grant_ref,
    )
