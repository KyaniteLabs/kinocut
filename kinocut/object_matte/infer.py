"""BiRefNet-general preprocess / infer / postprocess. No alpha-matting."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from ..defaults import OBJECT_MATTE_IMAGENET_MEAN, OBJECT_MATTE_IMAGENET_STD
from ..errors import MCPVideoError
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


def _invalid_output() -> MCPVideoError:
    return MCPVideoError(
        "Object matte model must return one finite numeric single-channel spatial mask.",
        error_type="processing_error",
        code="invalid_model_output",
    )


def _validated_logits(logits: np.ndarray) -> np.ndarray:
    """Accept HW, 1HW or 11HW without squeezing singleton spatial axes."""
    try:
        array = np.asarray(logits)
        if array.dtype.kind not in {"f", "i", "u"} or not np.isfinite(array).all():
            raise _invalid_output()
        if array.ndim == 4 and array.shape[:2] == (1, 1):
            array = array[0, 0]
        elif array.ndim == 3 and array.shape[0] == 1:
            array = array[0]
        if array.ndim != 2 or not all(array.shape):
            raise _invalid_output()
        # Clip before float32 conversion so finite float64 extremes cannot overflow.
        return np.asarray(np.clip(array, -30.0, 30.0), dtype=np.float32)
    except (ValueError, TypeError, OverflowError) as exc:
        raise _invalid_output() from exc


def _sigmoid_minmax(logits: np.ndarray) -> np.ndarray:
    logits = _validated_logits(logits)
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
    outputs = session.run(None, {input_name: blob})
    if not isinstance(outputs, (list, tuple)) or not outputs:
        raise _invalid_output()
    logits = outputs[0]
    return postprocess(logits, image.size)
