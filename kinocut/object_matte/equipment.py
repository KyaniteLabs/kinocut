"""Studio-gear diagnostic: turntable / stand / tripod / sweep / lightbox / clamp."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..defaults import DEFAULT_EQUIPMENT_SUBJECT_INTERSECTION
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_output_path

_DOCS = "docs/PRODUCT_MATTE.md"
_STATIC_ROW_FRACTION = 0.18


def static_row_mask(size: tuple[int, int]) -> np.ndarray:
    """Bottom band where a stand, clamp, or turntable usually sits."""
    width, height = size
    band = np.zeros((height, width), dtype=np.uint8)
    start = max(0, int(height * (1.0 - _STATIC_ROW_FRACTION)))
    band[start:, :] = 255
    return band


def temporal_static_mask(frames: list[Image.Image], max_std: float = 8.0) -> np.ndarray:
    """Pixels with low temporal variance (fixture, not a spinning SKU)."""
    if len(frames) < 2:
        return static_row_mask(frames[0].size if frames else (1, 1))
    stack = np.stack([np.asarray(frame.convert("L"), dtype=np.float32) for frame in frames], axis=0)
    std = np.std(stack, axis=0)
    static = (std <= max_std).astype(np.uint8) * 255
    return np.maximum(static, static_row_mask(frames[0].size))


def intersection_ratio(subject: Image.Image, equipment: np.ndarray) -> float:
    """Share of subject pixels that also sit on the equipment overlay."""
    sub = np.asarray(subject.convert("L"), dtype=np.uint8) > 127
    eq = equipment > 127
    subject_count = int(sub.sum())
    if subject_count == 0:
        return 0.0
    return float((sub & eq).sum()) / float(subject_count)


def write_overlay(path: str, equipment: np.ndarray) -> str:
    dest = _validate_output_path(path)
    Image.fromarray(equipment, mode="L").save(dest)
    return dest


def apply_equipment_gate(
    *,
    subject: Image.Image,
    frames: list[Image.Image],
    overlay_path: str | None,
    fail_if_equipment_on_subject: bool,
    threshold: float = DEFAULT_EQUIPMENT_SUBJECT_INTERSECTION,
) -> float:
    """Write overlay PNG when requested. Abort when fail flag + intersection."""
    if fail_if_equipment_on_subject and not overlay_path:
        raise MCPVideoError(
            "--fail-if-equipment-on-subject requires --equipment-overlay "
            "(turntable, stand, tripod, sweep, lightbox, clamp). Guide: "
            f"{_DOCS}.",
            error_type="validation_error",
            code="invalid_parameter",
            docs_url=_DOCS,
        )
    equipment = temporal_static_mask(frames) if frames else static_row_mask(subject.size)
    ratio = intersection_ratio(subject, equipment)
    if overlay_path:
        written = write_overlay(overlay_path, equipment)
        if fail_if_equipment_on_subject and not Path(written).is_file():
            raise MCPVideoError(
                "equipment overlay was requested but was not written.",
                error_type="processing_error",
                code="equipment_overlay_missing",
                docs_url=_DOCS,
            )
    if fail_if_equipment_on_subject and ratio >= threshold:
        raise MCPVideoError(
            "Studio equipment intersects the product silhouette "
            f"(ratio={ratio:.3f} >= {threshold}). Overlay written. "
            "Turntable / stand / tripod / sweep / lightbox / clamp. "
            f"Guide: {_DOCS}.",
            error_type="validation_error",
            code="equipment_on_subject",
            docs_url=_DOCS,
        )
    return ratio
