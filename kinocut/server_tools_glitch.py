"""MCP tool registrations for CRUSH glitch effects."""

from __future__ import annotations

from typing import Any

from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path
from .paths import _auto_output
from .server_app import _result, _safe_tool, mcp


# ---------------------------------------------------------------------------
# Glitch Effect Tools
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def glitch_rgb_shift(
    input_path: str,
    output_path: str | None = None,
    amount: float = 10.0,
    angle: float = 0.0,
    noise: float = 0.0,
) -> dict[str, Any]:
    """Apply RGB channel shift glitch effect.

    Shifts red and blue channels in opposite directions for a chromatic
    split look. Optionally adds per-frame noise for a jittery feel.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        amount: Shift distance in pixels. Default 10.0.
        angle: Shift direction in degrees. Default 0 (horizontal).
        noise: Per-frame noise amplitude (0-1). Default 0.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if amount < 0:
        raise MCPVideoError(
            f"amount must be non-negative, got {amount}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= noise <= 1.0):
        raise MCPVideoError(
            f"noise must be between 0.0 and 1.0, got {noise}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_rgb_shift as _fn

    output = output_path or _auto_output(input_path, "rgb_shift")
    return _result(_fn(input_path, output, amount, angle, noise))


@mcp.tool()
@_safe_tool
def glitch_scanline_jitter(
    input_path: str,
    output_path: str | None = None,
    jitter_amount: float = 15.0,
    frequency: float = 0.3,
    speed: float = 5.0,
    row_height: int = 4,
) -> dict[str, Any]:
    """Apply scanline jitter glitch effect.

    Displaces random horizontal rows of pixels for a CRT malfunction look.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        jitter_amount: Max horizontal displacement in pixels. Default 15.
        frequency: Fraction of rows affected (0-1). Default 0.3.
        speed: Animation speed multiplier. Default 5.
        row_height: Height of each jitter band in pixels. Default 4.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if jitter_amount < 0:
        raise MCPVideoError(
            f"jitter_amount must be non-negative, got {jitter_amount}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= frequency <= 1.0):
        raise MCPVideoError(
            f"frequency must be between 0.0 and 1.0, got {frequency}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if row_height < 1:
        raise MCPVideoError(
            f"row_height must be at least 1, got {row_height}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_scanline_jitter as _fn

    output = output_path or _auto_output(input_path, "scanline_jitter")
    return _result(_fn(input_path, output, jitter_amount, frequency, speed, row_height))


@mcp.tool()
@_safe_tool
def glitch_screen_tearing(
    input_path: str,
    output_path: str | None = None,
    tear_count: int = 5,
    offset_range: float = 80.0,
    speed: float = 3.0,
) -> dict[str, Any]:
    """Apply screen tearing glitch effect.

    Creates horizontal tear bands at varying Y positions that shift
    left/right over time.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        tear_count: Number of tear bands. Default 5.
        offset_range: Max horizontal offset in pixels. Default 80.
        speed: Animation speed. Default 3.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if tear_count < 1:
        raise MCPVideoError(
            f"tear_count must be at least 1, got {tear_count}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if offset_range < 0:
        raise MCPVideoError(
            f"offset_range must be non-negative, got {offset_range}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_screen_tearing as _fn

    output = output_path or _auto_output(input_path, "screen_tearing")
    return _result(_fn(input_path, output, tear_count, offset_range, speed))


@mcp.tool()
@_safe_tool
def glitch_vhs_tracking(
    input_path: str,
    output_path: str | None = None,
    tracking: float = 0.5,
    noise_amount: float = 0.03,
    color_bleed: float = 3.0,
    roll_speed: float = 2.0,
) -> dict[str, Any]:
    """Apply VHS tracking error glitch effect.

    Simulates VHS tape tracking problems with color bleed, rolling bands,
    and analog noise.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        tracking: Tracking error intensity (0-1). Default 0.5.
        noise_amount: VHS noise intensity (0-1). Default 0.03.
        color_bleed: Red channel shift in pixels. Default 3.
        roll_speed: Vertical roll speed. Default 2.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (0.0 <= tracking <= 1.0):
        raise MCPVideoError(
            f"tracking must be between 0.0 and 1.0, got {tracking}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= noise_amount <= 1.0):
        raise MCPVideoError(
            f"noise_amount must be between 0.0 and 1.0, got {noise_amount}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_vhs_tracking as _fn

    output = output_path or _auto_output(input_path, "vhs_tracking")
    return _result(_fn(input_path, output, tracking, noise_amount, color_bleed, roll_speed))


@mcp.tool()
@_safe_tool
def glitch_macroblocking(
    input_path: str,
    output_path: str | None = None,
    block_size: int = 16,
    intensity: float = 0.7,
    color_reduction: float = 0.3,
) -> dict[str, Any]:
    """Apply macroblocking glitch effect.

    Simulates codec artifacting by downscaling/upscaling to create blocky
    pixelation combined with color posterization.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        block_size: Block size in pixels. Default 16.
        intensity: Blend with original (0-1). Default 0.7.
        color_reduction: Color level reduction (0-1). Default 0.3.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if block_size < 2:
        raise MCPVideoError(
            f"block_size must be at least 2, got {block_size}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= intensity <= 1.0):
        raise MCPVideoError(
            f"intensity must be between 0.0 and 1.0, got {intensity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= color_reduction <= 1.0):
        raise MCPVideoError(
            f"color_reduction must be between 0.0 and 1.0, got {color_reduction}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_macroblocking as _fn

    output = output_path or _auto_output(input_path, "macroblocking")
    return _result(_fn(input_path, output, block_size, intensity, color_reduction))


@mcp.tool()
@_safe_tool
def glitch_datamoshing(
    input_path: str,
    output_path: str | None = None,
    drift: float = 20.0,
    iframe_interval: int = 30,
) -> dict[str, Any]:
    """Apply datamoshing glitch effect.

    Simulates P-frame corruption where displacement drifts across frames
    then periodically resets, mimicking real datamosh artifacts.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        drift: Max displacement drift in pixels. Default 20.
        iframe_interval: Frame interval for displacement resets. Default 30.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if drift < 0:
        raise MCPVideoError(
            f"drift must be non-negative, got {drift}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if iframe_interval < 1:
        raise MCPVideoError(
            f"iframe_interval must be at least 1, got {iframe_interval}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_datamoshing as _fn

    output = output_path or _auto_output(input_path, "datamoshing")
    return _result(_fn(input_path, output, drift, iframe_interval))


@mcp.tool()
@_safe_tool
def glitch_cmyk_split(
    input_path: str,
    output_path: str | None = None,
    amount: float = 8.0,
    angle: float = 0.0,
    noise: float = 0.0,
) -> dict[str, Any]:
    """Apply CMYK split glitch effect.

    Shifts RGB channels at 90-degree intervals to simulate four-plate
    offset print registration errors.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        amount: Shift distance in pixels. Default 8.
        angle: Base angle in degrees. Default 0.
        noise: Per-frame noise amplitude (0-1). Default 0.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if amount < 0:
        raise MCPVideoError(
            f"amount must be non-negative, got {amount}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= noise <= 1.0):
        raise MCPVideoError(
            f"noise must be between 0.0 and 1.0, got {noise}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_cmyk_split as _fn

    output = output_path or _auto_output(input_path, "cmyk_split")
    return _result(_fn(input_path, output, amount, angle, noise))


@mcp.tool()
@_safe_tool
def glitch_turbulent_displacement(
    input_path: str,
    output_path: str | None = None,
    amount: float = 20.0,
    scale: float = 0.01,
    speed: float = 1.0,
    octaves: int = 3,
) -> dict[str, Any]:
    """Apply turbulent displacement glitch effect.

    Uses layered sin/cos expressions at different frequencies to approximate
    fractal Brownian motion noise for organic-looking displacement.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        amount: Displacement magnitude in pixels. Default 20.
        scale: Base noise frequency. Default 0.01.
        speed: Animation speed. Default 1.
        octaves: Number of noise octaves (1-5). Default 3.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if amount < 0:
        raise MCPVideoError(
            f"amount must be non-negative, got {amount}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (1 <= octaves <= 5):
        raise MCPVideoError(
            f"octaves must be between 1 and 5, got {octaves}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .engine_glitch import glitch_turbulent_displacement as _fn

    output = output_path or _auto_output(input_path, "turbulent")
    return _result(_fn(input_path, output, amount, scale, speed, octaves))
