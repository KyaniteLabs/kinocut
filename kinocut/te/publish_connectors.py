"""Local-first publish connectors with per-platform spec validation (TE.1)."""

from __future__ import annotations

from typing import Any

from kinocut.errors import MCPVideoError

# Spec floors — not a claim of live upload APIs.
PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "youtube_shorts": {
        "max_duration_seconds": 60,
        "aspect_ratio": "9:16",
        "min_height": 1280,
        "container": "mp4",
    },
    "tiktok": {
        "max_duration_seconds": 180,
        "aspect_ratio": "9:16",
        "min_height": 960,
        "container": "mp4",
    },
    "instagram_reels": {
        "max_duration_seconds": 90,
        "aspect_ratio": "9:16",
        "min_height": 1280,
        "container": "mp4",
    },
    "x_video": {
        "max_duration_seconds": 140,
        "aspect_ratio": "any",
        "min_height": 720,
        "container": "mp4",
    },
}


def validate_publish_spec(
    platform: str,
    *,
    duration_seconds: float,
    height: int,
    width: int,
    container: str = "mp4",
) -> dict[str, Any]:
    key = (platform or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key not in PLATFORM_SPECS:
        known = ", ".join(sorted(PLATFORM_SPECS))
        raise MCPVideoError(
            f"unknown platform {platform!r}; known: {known}",
            error_type="validation_error",
            code="unknown_platform",
        )
    spec = PLATFORM_SPECS[key]
    findings: list[dict[str, Any]] = []
    if duration_seconds > float(spec["max_duration_seconds"]):
        findings.append(
            {
                "check_id": "duration.max",
                "severity": "fail",
                "message": f"duration {duration_seconds}s > max {spec['max_duration_seconds']}",
            }
        )
    if container.lower().lstrip(".") != str(spec["container"]).lower():
        findings.append(
            {
                "check_id": "container",
                "severity": "fail",
                "message": f"container {container} != {spec['container']}",
            }
        )
    if height < int(spec["min_height"]):
        findings.append(
            {
                "check_id": "height.min",
                "severity": "fail",
                "message": f"height {height} < min {spec['min_height']}",
            }
        )
    ar = spec.get("aspect_ratio")
    if ar == "9:16" and height > 0 and width > 0:
        ratio = width / height
        if ratio > 0.62:  # looser than exact 0.5625
            findings.append(
                {
                    "check_id": "aspect.9x16",
                    "severity": "warn",
                    "message": f"aspect {width}:{height} not vertical-first",
                }
            )
    blocked = any(f["severity"] == "fail" for f in findings)
    return {
        "artifact_kind": "publish_validation",
        "platform": key,
        "spec": spec,
        "findings": findings,
        "verdict": "fail" if blocked else "pass",
        "blocked": blocked,
        "upload": False,
        "notes": "Validation only — no network publish from this tool.",
    }
