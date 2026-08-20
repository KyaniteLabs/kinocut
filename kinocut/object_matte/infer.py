"""BiRefNet-general preprocess / infer / postprocess. No alpha-matting."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from ..defaults import OBJECT_MATTE_IMAGENET_MEAN, OBJECT_MATTE_IMAGENET_STD
from ..validation import OBJECT_MATTE_INPUT_SIZE


def preprocess(image: Image.Image) -> np.ndarray:
    """RGB, 1024x1024, ImageNet mean/std, NCHW float32."""
    rgb = image.convert("RGB").resize(
        (OBJECT_MATTE_INPUT_SIZE, OBJECT_MATTE_INPUT_SIZE),
        Image.Resampling.LANCZOS,
    )
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    mean = np.asarray(OBJECT_MATTE_IMAGENET_MEAN, dtype=np.float32)
    std = np.asarray(OBJECT_MATTE_IMAGENET_STD, dtype=np.float32)
    arr = (arr - mean) / std
    return np.transpose(arr, (2, 0, 1))[None, ...]


def _sigmoid_minmax(logits: np.ndarray) -> np.ndarray:
    logits = np.asarray(logits, dtype=np.float32)
    logits = np.squeeze(logits)
    mask = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
    lo, hi = float(mask.min()), float(mask.max())
    if hi - lo < 1e-8:
        return np.zeros_like(mask, dtype=np.float32)
    return (mask - lo) / (hi - lo)


def postprocess(logits: np.ndarray, size: tuple[int, int]) -> Image.Image:
    """Sigmoid, min-max, LANCZOS back to the source size."""
    mask = _sigmoid_minmax(logits)
    pixels = np.clip(mask * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels, mode="L").resize(size, Image.Resampling.LANCZOS)


def infer_mask(session: Any, image: Image.Image) -> Image.Image:
    """Run one still through the ONNX session. Returns an L mask."""
    blob = preprocess(image)
    input_name = session.get_inputs()[0].name
    logits = session.run(None, {input_name: blob})[0]
    return postprocess(logits, image.size)
