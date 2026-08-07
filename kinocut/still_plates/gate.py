"""still-gate: fail-closed package cohesion metrics + contact sheet."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..defaults import STILL_GATE_MAX_LUMA_SPREAD, STILL_GATE_MAX_SHADOW_GREEN_CYAN
from ..errors import MCPVideoError
from .io import (
    ensure_output_dir,
    file_sha256,
    load_rgb_array,
    require_still_deps,
    validate_still_path,
    write_receipt,
)
from .stats import package_metrics


def still_gate(
    *,
    inputs: list[str | Path],
    output_dir: str | Path,
    max_luma_spread: float = STILL_GATE_MAX_LUMA_SPREAD,
    max_shadow_green_cyan: float = STILL_GATE_MAX_SHADOW_GREEN_CYAN,
    contact_sheet_name: str = "contact_sheet.png",
    receipt_name: str = "still_gate_receipt.json",
) -> dict[str, Any]:
    """Evaluate package cohesion; fail closed when metrics exceed thresholds."""
    if not inputs:
        raise MCPVideoError(
            "still-gate requires at least one input still",
            error_type="validation_error",
            code="empty_inputs",
        )
    paths = [validate_still_path(p) for p in inputs]
    out_dir = ensure_output_dir(output_dir)
    frames = [load_rgb_array(p) for p in paths]
    metrics = package_metrics(frames)

    failures: list[dict[str, Any]] = []
    if metrics["luma_spread"] > max_luma_spread:
        # Name the darkest and brightest frames by mean luma.
        lumas = [fm["mean_luma"] for fm in metrics["per_frame"]]
        dark_i = min(range(len(lumas)), key=lambda i: lumas[i])
        bright_i = max(range(len(lumas)), key=lambda i: lumas[i])
        failures.append(
            {
                "metric": "luma_spread",
                "value": metrics["luma_spread"],
                "threshold": max_luma_spread,
                "frame": str(paths[bright_i]),
                "frame_index": bright_i,
                "darkest_frame": str(paths[dark_i]),
                "darkest_frame_index": dark_i,
                "brightest_frame": str(paths[bright_i]),
                "brightest_frame_index": bright_i,
            }
        )
    if metrics["shadow_green_cyan_max"] > max_shadow_green_cyan:
        # Name the worst frame.
        worst_i = 0
        worst_v = -1.0
        for i, fm in enumerate(metrics["per_frame"]):
            v = fm["shadow_green_cyan_fraction"]
            if v > worst_v:
                worst_v = v
                worst_i = i
        failures.append(
            {
                "metric": "shadow_green_cyan_fraction",
                "value": metrics["shadow_green_cyan_max"],
                "threshold": max_shadow_green_cyan,
                "frame": str(paths[worst_i]),
                "frame_index": worst_i,
            }
        )

    sheet_path = _write_contact_sheet(paths, out_dir / contact_sheet_name)
    passed = len(failures) == 0
    receipt = {
        "tool": "still_gate",
        "status": "pass" if passed else "fail",
        "passed": passed,
        "thresholds": {
            "max_luma_spread": max_luma_spread,
            "max_shadow_green_cyan": max_shadow_green_cyan,
        },
        "metrics": metrics,
        "failures": failures,
        "inputs": [{"path": str(p), "sha256": file_sha256(p)} for p in paths],
        "contact_sheet": str(sheet_path),
        "exit_code": 0 if passed else 1,
    }
    receipt_path = write_receipt(out_dir / receipt_name, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["output_dir"] = str(out_dir)
    return receipt


def _write_contact_sheet(paths: list[Path], dest: Path) -> Path:
    """Write a simple horizontal/grid contact sheet of the package stills."""
    require_still_deps()
    from PIL import Image

    images = []
    for p in paths:
        with Image.open(p) as im:
            images.append(im.convert("RGB").copy())
    if not images:
        raise MCPVideoError("no images for contact sheet", error_type="validation_error", code="empty_inputs")

    thumb_h = 256
    thumbs = []
    for im in images:
        w, h = im.size
        scale = thumb_h / max(h, 1)
        thumbs.append(im.resize((max(1, int(w * scale)), thumb_h)))

    gap = 8
    total_w = sum(t.size[0] for t in thumbs) + gap * (len(thumbs) + 1)
    sheet = Image.new("RGB", (total_w, thumb_h + 2 * gap), color=(24, 24, 24))
    x = gap
    for t in thumbs:
        sheet.paste(t, (x, gap))
        x += t.size[0] + gap
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest)
    return dest.resolve()
