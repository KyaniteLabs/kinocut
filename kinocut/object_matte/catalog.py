"""Cutout model catalog and backend selection, without loading inference dependencies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._install_hints import pip_install_hint
from ..defaults import (
    DEFAULT_OBJECT_MATTE_TIMEOUT,
    DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL,
    DEFAULT_REMOVE_BACKGROUND_MODEL,
)
from ..errors import MCPVideoError
from ..limits import MAX_OBJECT_MATTE_FRAMES
from ..validation import (
    REMOVE_BACKGROUND_ALLOWED_MODELS,
    REMOVE_BACKGROUND_HF_BACKEND,
    REMOVE_BACKGROUND_HUMAN_MODEL,
    REMOVE_BACKGROUND_OBJECT_BACKEND,
    REMOVE_BACKGROUND_OBJECT_MODEL,
    REMOVE_BACKGROUND_OBJECT_MODELS,
    object_matte_cache_path,
)
from ..validation_errors import rejected_value


def _object_matte_cache_path() -> Path:
    return object_matte_cache_path()


def background_catalog() -> dict[str, Any]:
    """Kinocut-owned remove-background --info. Never shells Hyperframes or downloads."""
    cache_path = _object_matte_cache_path()
    return {
        "defaultModel": DEFAULT_REMOVE_BACKGROUND_MODEL,
        "allowlistedModels": sorted(REMOVE_BACKGROUND_ALLOWED_MODELS),
        "backends": {
            REMOVE_BACKGROUND_HUMAN_MODEL: REMOVE_BACKGROUND_HF_BACKEND,
            REMOVE_BACKGROUND_OBJECT_MODEL: REMOVE_BACKGROUND_OBJECT_BACKEND,
        },
        "models": {
            REMOVE_BACKGROUND_HUMAN_MODEL: {
                "id": REMOVE_BACKGROUND_HUMAN_MODEL,
                "subject": "people",
                "backend": REMOVE_BACKGROUND_HF_BACKEND,
                "install": None,
                "summary": "Talking-head and person cutouts. Default. No extra.",
            },
            REMOVE_BACKGROUND_OBJECT_MODEL: {
                "id": REMOVE_BACKGROUND_OBJECT_MODEL,
                "subject": "products-and-objects",
                "backend": REMOVE_BACKGROUND_OBJECT_BACKEND,
                "install": pip_install_hint("object-matte"),
                "summary": ("Products, packaging, and other non-person objects on a table, sweep, or turntable."),
                "limits": {
                    "maxFrames": MAX_OBJECT_MATTE_FRAMES,
                    "timeoutSeconds": DEFAULT_OBJECT_MATTE_TIMEOUT,
                },
            },
        },
        "docs": "docs/PRODUCT_MATTE.md",
        "cache": {
            "weightsCached": cache_path.is_file(),
            "path": str(cache_path),
        },
        "providers": [],
    }


def _resolve_remove_background_model(model: str | None) -> str:
    if model is None or model == "":
        return DEFAULT_REMOVE_BACKGROUND_MODEL
    if model not in REMOVE_BACKGROUND_ALLOWED_MODELS:
        allowed = ", ".join(sorted(REMOVE_BACKGROUND_ALLOWED_MODELS))
        raise MCPVideoError(
            f"Unknown remove-background model {rejected_value(model)!r}. "
            f"Allowlisted: {allowed} "
            f"({REMOVE_BACKGROUND_HUMAN_MODEL}=people, "
            f"{REMOVE_BACKGROUND_OBJECT_MODEL}=products-and-objects). "
            "See docs/PRODUCT_MATTE.md.",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return model


def _normalize_mask_interval(mask_interval: int | None) -> int:
    if mask_interval is None:
        return DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL
    if isinstance(mask_interval, bool) or not isinstance(mask_interval, int):
        raise MCPVideoError(
            "mask_interval must be an integer",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if mask_interval < 1:
        raise MCPVideoError(
            "mask_interval must be >= 1",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return mask_interval


def _assert_hf_remove_background_flags(
    mask_interval: int,
    equipment_overlay: str | None,
    fail_if_equipment_on_subject: bool,
) -> None:
    if mask_interval > DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL:
        raise MCPVideoError(
            "mask_interval > 1 is for product/object cutouts "
            "(--model birefnet-general). People cutouts use the default interval.",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if equipment_overlay:
        raise MCPVideoError(
            "equipment_overlay is for product/object cutouts "
            "(turntable, stand, tripod, sweep). Use --model birefnet-general.",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if fail_if_equipment_on_subject:
        raise MCPVideoError(
            "fail_if_equipment_on_subject is for product/object cutouts. "
            "Use --model birefnet-general. See docs/PRODUCT_MATTE.md.",
            error_type="validation_error",
            code="invalid_parameter",
        )


def uses_object_backend(model: str) -> bool:
    return model in REMOVE_BACKGROUND_OBJECT_MODELS
