"""A/B reel construction: reference vs new render.

An A/B reel is a neutral descriptor that pairs a reference render hash with
a new render hash. It does not contain audio bytes, host paths, or raw text;
only bounded hashes and a stable reel digest that a controller can turn into
an actual audition artifact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from kinocut_sound._canonical import BoundedCode, Sha256

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_METRIC_INVALID,
    bounded_consistency_error,
)


@dataclass(frozen=True)
class AbReel:
    """Neutral A/B reel descriptor."""

    reel_label: str
    reference_hash: Sha256
    render_hash: Sha256
    reel_hash: Sha256
    human_review_required: bool = True


def _reel_hash(*, reel_label: str, reference_hash: str, render_hash: str) -> Sha256:
    body = {
        "reel_label": reel_label,
        "reference_hash": reference_hash,
        "render_hash": render_hash,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_ab_reel(
    *,
    reference_hash: Sha256,
    render_hash: Sha256,
    label: str,
) -> AbReel:
    """Build an A/B reel descriptor pairing reference and render hashes."""

    try:
        BoundedCode(label)
    except (TypeError, ValueError) as exc:
        raise bounded_consistency_error(
            "reel label must be a bounded code",
            CONSISTENCY_METRIC_INVALID,
        ) from exc
    reel_hash = _reel_hash(
        reel_label=label,
        reference_hash=reference_hash,
        render_hash=render_hash,
    )
    return AbReel(
        reel_label=label,
        reference_hash=reference_hash,
        render_hash=render_hash,
        reel_hash=reel_hash,
        human_review_required=True,
    )
