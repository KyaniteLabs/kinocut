"""Inverse of publish validation: platform constraints → cutfile (N5)."""

from __future__ import annotations

from typing import Any

from kinocut.te.cutfile import validate_cutfile
from kinocut.te.publish_connectors import PLATFORM_SPECS, validate_publish_spec


def solve_publish_cutfile(
    platform: str,
    *,
    source: str = "media/hero.mp4",
    source_duration: float = 60.0,
    captions: bool = False,
) -> dict[str, Any]:
    """Build a cutfile that should pass ``validate_publish_spec`` after render."""
    key = (platform or "").strip().lower().replace("-", "_").replace(" ", "_")
    spec = PLATFORM_SPECS.get(key)
    if spec is None:
        return validate_publish_spec(platform, duration_seconds=0, height=0, width=0)
    max_dur = float(spec["max_duration_seconds"])
    duration = min(float(source_duration), max_dur)
    ar = str(spec.get("aspect_ratio") or "9:16")
    min_h = int(spec["min_height"])
    if ar == "9:16":
        width, height = max(1080, int(min_h * 9 / 16)), max(min_h, 1920)
    elif ar == "1:1":
        width = height = max(min_h, 1080)
    else:
        height = max(min_h, 1080)
        width = int(height * 16 / 9)
    ops: list[dict[str, Any]] = [{"op": "trim", "start": 0, "duration": duration}]
    if ar != "any":
        ops.append({"op": "resize", "width": width, "height": height})
    if captions:
        ops.append({"op": "add_text", "text": "CAPTIONS", "position": "bottom-center"})
    cf = validate_cutfile(
        {
            "name": f"{key}-solve",
            "version": 1,
            "sources": [{"id": "hero", "path": source}],
            "ops": ops,
        }
    )
    proof = validate_publish_spec(
        key,
        duration_seconds=duration,
        height=height,
        width=width,
        container=str(spec["container"]),
    )
    return {
        **cf.to_dict(),
        "platform": key,
        "publish_proof": proof,
        "next_action": "review_then_cutfile_render",
    }
