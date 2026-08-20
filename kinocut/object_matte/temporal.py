"""Mask-interval sampling plus median window 3."""

from __future__ import annotations

from PIL import Image

from ..defaults import DEFAULT_OBJECT_MATTE_MEDIAN_WINDOW


def expand_sampled_masks(sampled: list[Image.Image], frame_count: int, interval: int) -> list[Image.Image]:
    """Hold each inferred mask across the following interval-1 frames."""
    if not sampled or frame_count < 1:
        return []
    out: list[Image.Image] = []
    for index in range(frame_count):
        sample_index = min(index // interval, len(sampled) - 1)
        out.append(sampled[sample_index])
    return out


def median_window(masks: list[Image.Image], window: int = DEFAULT_OBJECT_MATTE_MEDIAN_WINDOW) -> list[Image.Image]:
    """Per-pixel median over an odd window. No-op when there is one frame."""
    import numpy as np

    if len(masks) < 2 or window < 3:
        return masks
    radius = window // 2
    stack = np.stack([np.asarray(mask, dtype=np.uint8) for mask in masks], axis=0)
    smoothed: list[Image.Image] = []
    last = len(masks) - 1
    for index in range(len(masks)):
        lo = max(0, index - radius)
        hi = min(last, index + radius) + 1
        med = np.median(stack[lo:hi], axis=0).astype(np.uint8)
        smoothed.append(Image.fromarray(med, mode="L"))
    return smoothed
