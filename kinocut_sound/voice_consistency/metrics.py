"""Voice consistency metrics consumed from a fake D42 port.

The metrics leaf is backend-neutral: it calls the typed :class:`StylePort`
and :class:`IdentityPort` defined in :mod:`d42_port.py` and returns bounded
results. A real D42 binding (S13) replaces the fake adapters without
changing this module's caller contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from kinocut_sound._canonical import BoundedCode, Sha256

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_D42_UNAVAILABLE,
    CONSISTENCY_METRIC_INVALID,
    bounded_consistency_error,
)
from kinocut_sound.voice_consistency.d42_port import (
    FakeD42Port,
    IdentityCheckSpec,
    StyleCheckSpec,
    IdentityCheckResult,
    StyleCheckResult,
)
from kinocut_sound.limits import MAX_VOICE_CONSISTENCY_FLAGS


@dataclass(frozen=True)
class StyleMetrics:
    """Style consistency metrics for one render against its reference."""

    profile_id: str
    audio_hash: Sha256
    reference_hash: Sha256
    similarity: float
    drift: bool
    flags: tuple[str, ...]
    threshold: float


def _validate_threshold(threshold: float) -> float:
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
    return float(threshold)


def _require_available(port: FakeD42Port) -> None:
    style_probe, identity_probe = port.probe()
    if not style_probe.available or not identity_probe.available:
        raise bounded_consistency_error(
            "D42 port is unavailable",
            CONSISTENCY_D42_UNAVAILABLE,
        )


def _validated_similarity(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
        or not math.isfinite(value)
    ):
        raise bounded_consistency_error("D42 similarity must be finite and within [0, 1]", CONSISTENCY_METRIC_INVALID)
    return float(value)


def _validated_style_result(result: StyleCheckResult, profile_id: str) -> float:
    if (
        not isinstance(result, StyleCheckResult)
        or result.profile_id != profile_id
        or not isinstance(result.drift, bool)
        or not isinstance(result.flags, tuple)
        or len(result.flags) > MAX_VOICE_CONSISTENCY_FLAGS
    ):
        raise bounded_consistency_error("D42 style result violates its bounded contract", CONSISTENCY_METRIC_INVALID)
    try:
        for flag in result.flags:
            BoundedCode(flag)
    except (TypeError, ValueError) as exc:
        raise bounded_consistency_error("D42 style flags must be bounded codes", CONSISTENCY_METRIC_INVALID) from exc
    return _validated_similarity(result.similarity)


def style_check(
    *,
    port: FakeD42Port,
    profile_id: str,
    audio_hash: Sha256,
    reference_hash: Sha256,
    threshold: float = 0.85,
) -> StyleMetrics:
    """Check a render's style consistency against its reference.

    ``threshold`` is the minimum acceptable similarity. The result's
    ``drift`` flag is ``True`` when similarity falls below it.
    """

    try:
        BoundedCode(profile_id)
    except (TypeError, ValueError) as exc:
        raise bounded_consistency_error(
            "profile_id must be a bounded code",
            CONSISTENCY_METRIC_INVALID,
        ) from exc
    threshold = _validate_threshold(threshold)
    _require_available(port)
    spec = StyleCheckSpec(
        profile_id=profile_id,
        audio_hash=audio_hash,
        reference_hash=reference_hash,
    )
    result = port.style.check_style(spec)
    similarity = _validated_style_result(result, profile_id)
    drift = result.drift or similarity < threshold
    flags = list(result.flags)
    if drift and "style_drift" not in flags:
        flags.append("style_drift")
    if len(flags) > MAX_VOICE_CONSISTENCY_FLAGS:
        raise bounded_consistency_error(
            "D42 result flags exceed the bounded output contract", CONSISTENCY_METRIC_INVALID
        )
    return StyleMetrics(
        profile_id=profile_id,
        audio_hash=audio_hash,
        reference_hash=reference_hash,
        similarity=similarity,
        drift=drift,
        flags=tuple(flags),
        threshold=threshold,
    )


def identity_similarity(
    *,
    port: FakeD42Port,
    audio_hash_a: Sha256,
    audio_hash_b: Sha256,
) -> float:
    """Return optional identity similarity between two audio hashes."""

    _require_available(port)
    spec = IdentityCheckSpec(
        audio_hash_a=audio_hash_a,
        audio_hash_b=audio_hash_b,
    )
    result = port.identity.compare_identity(spec)
    if not isinstance(result, IdentityCheckResult) or not isinstance(result.same_identity, bool):
        raise bounded_consistency_error("D42 identity result violates its bounded contract", CONSISTENCY_METRIC_INVALID)
    return _validated_similarity(result.similarity)
