"""MCP guardrail tool registrations for visual quality."""

from __future__ import annotations

from typing import Any

from .design_guardrails import (
    extract_verification_frame,
    validate_text_layout,
    TextOverlaySpec,
)
from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_validate_text_layout(
    overlays: list[dict[str, Any]],
    video_width: int = 1920,
    video_height: int = 1080,
    background_color: str = "#000000",
) -> dict[str, Any]:
    """Validate a set of text overlays for visual failure modes before rendering.

    Checks for: text overlap, low contrast, unsafe positioning, excessive
    sequential overlays, and missing shadows.

    Args:
        overlays: List of overlay specs with keys: text, position, size, color,
                  shadow (optional), start_time (optional), duration (optional).
        video_width: Video width in pixels.
        video_height: Video height in pixels.
        background_color: Background hex color for contrast checking.

    Returns:
        dict with warnings list and clean boolean.
    """
    specs = []
    for o in overlays:
        specs.append(
            TextOverlaySpec(
                text=o.get("text", ""),
                position=o.get("position", "center"),
                size=o.get("size", 48),
                color=o.get("color", "white"),
                shadow=o.get("shadow", True),
                start_time=o.get("start_time"),
                duration=o.get("duration"),
            )
        )

    warnings = validate_text_layout(
        overlays=specs,
        video_width=video_width,
        video_height=video_height,
        background_color=background_color,
    )

    return _result(
        {
            "clean": len(warnings) == 0,
            "warning_count": len(warnings),
            "warnings": [
                {
                    "code": w.code,
                    "message": w.message,
                    "severity": w.severity,
                    "overlay_indices": list(w.overlay_indices),
                }
                for w in warnings
            ],
        }
    )


@mcp.tool()
@_safe_tool
def video_extract_frame(
    input_path: str,
    timestamp: float = 0.0,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Extract a single frame from a video for visual verification.

    Args:
        input_path: Absolute path to the video.
        timestamp: Time in seconds to extract.
        output_path: Where to save the frame. Auto-generated if omitted.
    """
    path = extract_verification_frame(input_path, timestamp, output_path)
    return _result({"output_path": path})
