"""Public object-matte entry: never shells Hyperframes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..defaults import DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_input_path, _validate_output_path
from ..hyperframes_models import HyperframesJsonResult
from ..validation import REMOVE_BACKGROUND_OBJECT_BACKEND, REMOVE_BACKGROUND_OBJECT_MODEL
from .runtime import make_session, require_object_matte_deps
from .weights import ensure_weights

_DOCS = "docs/PRODUCT_MATTE.md"


def _cut_still(image, mask, output_path, background_output_path):
    from .media import apply_alpha, encode_still

    cut = encode_still(apply_alpha(image, mask), output_path)
    hole = None
    if background_output_path:
        hole = encode_still(
            apply_alpha(image, mask, invert=True),
            _validate_output_path(background_output_path),
        )
    return cut, hole


def _cut_video(frames, masks, output_path, background_output_path, fps):
    from .media import apply_alpha, encode_video

    cut_frames = [apply_alpha(frame, mask) for frame, mask in zip(frames, masks, strict=True)]
    cut = encode_video(cut_frames, output_path, fps)
    hole = None
    if background_output_path:
        holes = [apply_alpha(frame, mask, invert=True) for frame, mask in zip(frames, masks, strict=True)]
        hole = encode_video(holes, _validate_output_path(background_output_path), fps)
    return cut, hole


def _receipt(cut: str, hole: str | None, providers: list[str], cache_hit: bool) -> HyperframesJsonResult:
    if not Path(cut).is_file():
        raise MCPVideoError(
            "Object-matte output was not written.",
            error_type="processing_error",
            code="missing_output",
            docs_url=_DOCS,
        )
    payload: dict[str, Any] = {
        "output": cut,
        "model": REMOVE_BACKGROUND_OBJECT_MODEL,
        "backend": REMOVE_BACKGROUND_OBJECT_BACKEND,
        "providers": providers,
        "cache_hit": cache_hit,
        "docs": _DOCS,
    }
    if hole:
        payload["backgroundOutput"] = hole
    return HyperframesJsonResult(command="remove-background", data=payload, stdout=json.dumps(payload, sort_keys=True))


def run_object_matte(
    *,
    input_path: str,
    output_path: str | None = None,
    background_output_path: str | None = None,
    device: str = "auto",
    quality: str = "balanced",
    mask_interval: int = DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL,
    equipment_overlay: str | None = None,
    fail_if_equipment_on_subject: bool = False,
) -> HyperframesJsonResult:
    """Cut a product/object. quality is accepted and ignored (CLI always sends it)."""
    del quality
    require_object_matte_deps()
    from .equipment import apply_equipment_gate
    from .infer import infer_mask
    from .media import default_output_path, extract_frames, is_still, load_still
    from .temporal import expand_sampled_masks, median_window

    source = _validate_input_path(input_path)
    dest = default_output_path(source, output_path)
    weights, cache_hit = ensure_weights()
    session, providers = make_session(weights, device)
    if is_still(source):
        image = load_still(source)
        mask = infer_mask(session, image)
        apply_equipment_gate(
            subject=mask,
            frames=[image],
            overlay_path=equipment_overlay,
            fail_if_equipment_on_subject=fail_if_equipment_on_subject,
        )
        cut, hole = _cut_still(image, mask, dest, background_output_path)
    else:
        frames, fps = extract_frames(source)
        sampled = [infer_mask(session, frames[index]) for index in range(0, len(frames), mask_interval)]
        masks = median_window(expand_sampled_masks(sampled, len(frames), mask_interval))
        apply_equipment_gate(
            subject=masks[len(masks) // 2],
            frames=frames,
            overlay_path=equipment_overlay,
            fail_if_equipment_on_subject=fail_if_equipment_on_subject,
        )
        cut, hole = _cut_video(frames, masks, dest, background_output_path, fps)
    return _receipt(cut, hole, providers, cache_hit)
