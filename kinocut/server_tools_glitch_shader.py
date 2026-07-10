"""MCP tool registrations for CRUSH GPU shader effects.

Four effects requiring headless WebGL rendering via Node.js + CRUSH.js:
- Digital Feedback, Slit-Scan, Depth Splatting, Point Cloud
"""

from __future__ import annotations

from typing import Any

from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path
from .paths import _auto_output
from .server_app import _result, _safe_tool, mcp


# ---------------------------------------------------------------------------
# GPU Shader Effect Tools
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def glitch_digital_feedback(
    input_path: str,
    output_path: str | None = None,
    feedback_mix: float = 0.5,
    scale: float = 1.0,
    rotation: float = 0.0,
    decay: float = 0.9,
) -> dict[str, Any]:
    """Apply digital feedback glitch effect (requires Node.js + GPU).

    Iterative frame feedback with scale/rotation transform. Each frame blends
    with a scaled+rotated version of the previous output, creating ghostly
    trails and recursive visual patterns.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        feedback_mix: Blend between current and feedback (0-1). Default 0.5.
        scale: UV scale for previous frame. Default 1.0.
        rotation: Rotation in degrees. Default 0.0.
        decay: Ghost trail opacity (0-1). Default 0.9.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (0.0 <= feedback_mix <= 1.0):
        raise MCPVideoError(
            f"feedback_mix must be between 0.0 and 1.0, got {feedback_mix}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= decay <= 1.0):
        raise MCPVideoError(
            f"decay must be between 0.0 and 1.0, got {decay}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch_shader import glitch_digital_feedback as _fn

    output = output_path or _auto_output(input_path, "digital_feedback")
    return _result(_fn(input_path, output, feedback_mix, scale, rotation, decay))


@mcp.tool()
@_safe_tool
def glitch_slit_scan(
    input_path: str,
    output_path: str | None = None,
    depth: int = 30,
    direction: int = 0,
) -> dict[str, Any]:
    """Apply slit-scan temporal displacement effect (requires Node.js + GPU).

    Each row/column of the output is sampled from a different past frame,
    creating a time-smeared effect reminiscent of slit-scan photography.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        depth: Number of past frames to use (1-120). Default 30.
        direction: 0=top-bottom, 1=bottom-top, 2=left-right, 3=right-left. Default 0.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (1 <= depth <= 120):
        raise MCPVideoError(
            f"depth must be between 1 and 120, got {depth}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if direction not in (0, 1, 2, 3):
        raise MCPVideoError(
            f"direction must be 0-3, got {direction}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch_shader import glitch_slit_scan as _fn

    output = output_path or _auto_output(input_path, "slit_scan")
    return _result(_fn(input_path, output, depth, direction))


@mcp.tool()
@_safe_tool
def glitch_depth_splatting(
    input_path: str,
    output_path: str | None = None,
    depth_scale: float = 1.0,
    spread: float = 10.0,
    point_size: float = 3.0,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Apply depth-based point splatting effect (requires Node.js + GPU).

    Extracts pseudo-depth from luminance and renders the image as scattered
    points, creating a 3D particle-like appearance.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        depth_scale: Depth extraction intensity. Default 1.0.
        spread: Point spread distance in pixels. Default 10.0.
        point_size: Size of each splatted point. Default 3.0.
        threshold: Depth cutoff threshold (0-1). Default 0.5.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (0.0 <= threshold <= 1.0):
        raise MCPVideoError(
            f"threshold must be between 0.0 and 1.0, got {threshold}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch_shader import glitch_depth_splatting as _fn

    output = output_path or _auto_output(input_path, "depth_splatting")
    return _result(_fn(input_path, output, depth_scale, spread, point_size, threshold))


@mcp.tool()
@_safe_tool
def glitch_point_cloud(
    input_path: str,
    output_path: str | None = None,
    density: float = 0.5,
    point_size: float = 2.0,
    rotation: float = 0.0,
    depth: float = 1.0,
) -> dict[str, Any]:
    """Apply point cloud rendering effect (requires Node.js + GPU).

    Samples the image as scattered points arranged in a 3D-rotated grid,
    with depth-based displacement creating a volumetric look.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        density: Point sampling density (0-1). Default 0.5.
        point_size: Size of each point. Default 2.0.
        rotation: 3D rotation angle in degrees. Default 0.0.
        depth: Depth displacement intensity. Default 1.0.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (0.0 <= density <= 1.0):
        raise MCPVideoError(
            f"density must be between 0.0 and 1.0, got {density}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch_shader import glitch_point_cloud as _fn

    output = output_path or _auto_output(input_path, "point_cloud")
    return _result(_fn(input_path, output, density, point_size, rotation, depth))
