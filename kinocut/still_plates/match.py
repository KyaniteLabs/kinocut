"""still-match: shared WB/exposure match of a still package to a hero plate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..defaults import STILL_MATCH_MAX_GAIN, STILL_MATCH_MIN_GAIN
from ..errors import MCPVideoError
from .io import (
    ensure_output_dir,
    file_sha256,
    load_rgb_array,
    save_rgb_array,
    validate_still_path,
    write_receipt,
)
from .stats import apply_rgb_gains, mean_rgb, shared_gains_to_hero


def _validate_match_args(
    *,
    inputs: list[str | Path],
    overwrite_sources: bool,
    per_frame_auto_wb: bool,
) -> None:
    if overwrite_sources:
        raise MCPVideoError(
            "still-match refuses overwrite_sources=True; write to output_dir instead",
            error_type="validation_error",
            code="overwrite_refused",
        )
    if not inputs:
        raise MCPVideoError(
            "still-match requires at least one input still",
            error_type="validation_error",
            code="empty_inputs",
        )
    if per_frame_auto_wb:
        raise MCPVideoError(
            "per_frame_auto_wb is not supported in v1 (shared gains only); pass False",
            error_type="validation_error",
            code="per_frame_wb_disabled",
        )


def _compute_shared_gains(hero_arr, input_arrs) -> tuple[tuple[float, float, float], float]:
    """One shared gain triple mapping package mean RGB toward hero mean RGB.

    RGB-target gains already include exposure; do **not** multiply by a second
    luma scale (that over-corrected and clipped highlights).
    """
    hero_rgb = mean_rgb(hero_arr)
    package_rgb = tuple(float(sum(mean_rgb(a)[i] for a in input_arrs) / len(input_arrs)) for i in range(3))
    gains = shared_gains_to_hero(
        hero_rgb,
        package_rgb,  # type: ignore[arg-type]
        max_gain=STILL_MATCH_MAX_GAIN,
        min_gain=STILL_MATCH_MIN_GAIN,
    )
    # Implied exposure scale from geometric mean of channel gains (receipt only).
    product = max(gains[0] * gains[1] * gains[2], 1e-12)
    exposure_scale = float(product ** (1.0 / 3.0))
    return gains, exposure_scale


def _write_matched_outputs(
    input_paths: list[Path],
    input_arrs: list,
    final_gains: tuple[float, float, float],
    out_dir: Path,
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for src, arr in zip(input_paths, input_arrs, strict=True):
        matched = apply_rgb_gains(arr, final_gains)
        dest = out_dir / f"{src.stem}_matched.png"
        save_rgb_array(matched, dest)
        outputs.append(
            {
                "source": str(src),
                "output": str(dest),
                "source_sha256": file_sha256(src),
                "output_sha256": file_sha256(dest),
            }
        )
    return outputs


def still_match(
    *,
    hero: str | Path,
    inputs: list[str | Path],
    output_dir: str | Path,
    overwrite_sources: bool = False,
    per_frame_auto_wb: bool = False,
    receipt_name: str = "still_match_receipt.json",
) -> dict[str, Any]:
    """Match stills to a hero using one shared WB/exposure gain triple."""
    _validate_match_args(
        inputs=inputs,
        overwrite_sources=overwrite_sources,
        per_frame_auto_wb=per_frame_auto_wb,
    )
    hero_path = validate_still_path(hero)
    input_paths = [validate_still_path(p) for p in inputs]
    out_dir = ensure_output_dir(output_dir)

    hero_arr = load_rgb_array(hero_path)
    input_arrs = [load_rgb_array(p) for p in input_paths]
    final_gains, exposure_scale = _compute_shared_gains(hero_arr, input_arrs)
    outputs = _write_matched_outputs(input_paths, input_arrs, final_gains, out_dir)

    receipt = {
        "tool": "still_match",
        "hero": str(hero_path),
        "hero_sha256": file_sha256(hero_path),
        "hero_mean_rgb": list(mean_rgb(hero_arr)),
        "package_mean_rgb": [float(sum(mean_rgb(a)[i] for a in input_arrs) / len(input_arrs)) for i in range(3)],
        "shared_gains": list(final_gains),
        "exposure_scale": exposure_scale,
        "per_frame_auto_wb": False,
        "delta_ev": (__import__("math").log2(exposure_scale) if exposure_scale > 0 else 0.0),
        "outputs": outputs,
    }
    receipt_path = write_receipt(out_dir / receipt_name, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["output_dir"] = str(out_dir)
    receipt["status"] = "ok"
    return receipt
