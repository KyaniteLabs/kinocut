"""Still statistics for match and cohesion gating."""

from __future__ import annotations

from typing import Any

from ..defaults import STILL_SHADOW_LUMA_MAX
from .io import require_still_deps

# Green/cyan wash: G elevated vs R in shadows, or G+B clearly dominate R.
GREEN_CYAN_G_OVER_R = 1.08
GREEN_CYAN_GB_OVER_R = 1.15
# Re-export for callers/tests that imported the old module constant.
SHADOW_LUMA_MAX = STILL_SHADOW_LUMA_MAX


def _np():
    require_still_deps()
    import numpy as np

    return np


def luma_channel(arr) -> Any:
    """Rec.709 luma from float RGB array."""
    return 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]


def mean_rgb(arr) -> tuple[float, float, float]:
    """Mean RGB of the full frame."""
    means = arr.reshape(-1, 3).mean(axis=0)
    return float(means[0]), float(means[1]), float(means[2])


def mean_luma(arr) -> float:
    """Mean Rec.709 luma."""
    return float(luma_channel(arr).mean())


def apply_rgb_gains(arr, gains: tuple[float, float, float]):
    """Apply per-channel gains; clip to 0..1."""
    np = _np()
    out = arr * np.asarray(gains, dtype=np.float32).reshape(1, 1, 3)
    return np.clip(out, 0.0, 1.0)


def shared_gains_to_hero(
    hero_rgb: tuple[float, float, float],
    package_rgb: tuple[float, float, float],
    *,
    max_gain: float = 2.5,
    min_gain: float = 0.35,
) -> tuple[float, float, float]:
    """Compute one shared gain triple that maps package mean RGB toward hero."""
    gains = []
    for h, p in zip(hero_rgb, package_rgb, strict=True):
        g = (1.0 if h < 1e-6 else max_gain) if p < 1e-6 else h / p
        gains.append(float(max(min_gain, min(max_gain, g))))
    return gains[0], gains[1], gains[2]


def shadow_green_cyan_fraction(arr) -> float:
    """Fraction of shadow pixels showing green/cyan wash."""
    np = _np()
    luma = luma_channel(arr)
    shadow = luma < STILL_SHADOW_LUMA_MAX
    n_shadow = int(shadow.sum())
    if n_shadow == 0:
        return 0.0
    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]
    safe_r = np.maximum(r, 1e-4)
    greenish = (g / safe_r) >= GREEN_CYAN_G_OVER_R
    cyanish = ((g + b) / (2.0 * safe_r)) >= GREEN_CYAN_GB_OVER_R
    washed = shadow & (greenish | cyanish)
    return float(washed.sum() / n_shadow)


def frame_metrics(arr) -> dict[str, float]:
    """Per-frame cohesion metrics."""
    np = _np()
    luma = luma_channel(arr)
    r, g, b = mean_rgb(arr)
    return {
        "mean_r": r,
        "mean_g": g,
        "mean_b": b,
        "mean_luma": float(luma.mean()),
        "luma_p05": float(np.percentile(luma, 5)),
        "luma_p95": float(np.percentile(luma, 95)),
        "shadow_green_cyan_fraction": shadow_green_cyan_fraction(arr),
    }


def package_metrics(frames: list) -> dict[str, Any]:
    """Aggregate package-level cohesion metrics."""
    per_frame = [frame_metrics(f) for f in frames]
    lumas = [m["mean_luma"] for m in per_frame]
    fog = [m["shadow_green_cyan_fraction"] for m in per_frame]
    return {
        "frame_count": len(frames),
        "mean_luma_min": min(lumas) if lumas else 0.0,
        "mean_luma_max": max(lumas) if lumas else 0.0,
        "luma_spread": (max(lumas) - min(lumas)) if lumas else 0.0,
        "shadow_green_cyan_max": max(fog) if fog else 0.0,
        "shadow_green_cyan_mean": float(sum(fog) / len(fog)) if fog else 0.0,
        "per_frame": per_frame,
    }
