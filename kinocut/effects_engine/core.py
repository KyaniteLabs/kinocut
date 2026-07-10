"""Video effects and filters engine.

Visual effects using FFmpeg filters and PIL for custom processing.
"""

from __future__ import annotations

import logging
import math

from ..errors import ProcessingError
from ..defaults import DEFAULT_GLOW_MAX_SAFE_INTENSITY
from ..ffmpeg_helpers import _sanitize_ffmpeg_number
from ..ffmpeg_helpers import _validate_input_path, _validate_output_path, _run_command

logger = logging.getLogger(__name__)


def effect_vignette(
    input_path: str,
    output: str,
    intensity: float = 0.5,
    radius: float = 0.8,
    smoothness: float = 0.5,
) -> str:
    """Apply vignette effect - darkened edges with adjustable curve.

    Args:
        input_path: Input video path
        output: Output video path
        intensity: Darkness amount (0-1)
        radius: Vignette radius (0-1, 1 = edge of frame)
        smoothness: Edge softness (0-1)

    Returns:
        Path to output video
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    intensity = _sanitize_ffmpeg_number(intensity, "intensity")
    radius = _sanitize_ffmpeg_number(radius, "radius")

    # FFmpeg vignette filter: angle (in radians) controls the radius
    # intensity maps to darkness

    # Convert radius to angle (FFmpeg uses angle in radians)
    # angle of PI/2 = corner to center, angle of PI/5 = closer to edges
    angle = 3.14159 * (1 - radius * 0.8)  # Scale to reasonable range

    # Build filter chain
    # vignette creates the darkening, we overlay it with the original
    filters = (
        f"split[original][vignetted];"
        f"[vignetted]vignette=angle={angle}:mode=backward[a];"
        f"[a]format=pix_fmts=yuva420p,colorchannelmixer=aa={intensity}[vignette];"
        f"[original][vignette]overlay=format=auto"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        filters,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    _run_command(cmd)

    return output


def effect_chromatic_aberration(
    input_path: str,
    output: str,
    intensity: float = 2.0,
    angle: float = 0,
) -> str:
    """Apply chromatic aberration - RGB channel separation.

    Args:
        input_path: Input video path
        output: Output video path
        intensity: Pixel offset amount
        angle: Separation direction in degrees (0 = horizontal)

    Returns:
        Path to output video
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    # Convert angle to radians
    angle_rad = angle * 3.14159 / 180

    # Calculate x and y offsets
    offset_x = intensity * math.cos(angle_rad)
    offset_y = intensity * math.sin(angle_rad)

    # Use chromashift filter directly
    shift_x = int(offset_x)
    shift_y = int(offset_y)

    filters = f"chromashift=cbh={shift_x}:cbv={shift_y}:crh=-{shift_x}:crv=-{shift_y}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        filters,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    try:
        _run_command(cmd)
    except ProcessingError as e:
        if "chromashift" not in e.full_stderr:
            raise
        filters = f"colorbalance=rs={intensity / 100}:bs=-{intensity / 100}"
        cmd[5] = filters
        _run_command(cmd)

    return output


def effect_scanlines(
    input_path: str,
    output: str,
    line_height: int = 2,
    opacity: float = 0.3,
    flicker: float = 0.1,
) -> str:
    """Apply CRT-style scanlines overlay.

    Args:
        input_path: Input video path
        output: Output video path
        line_height: Pixels per line
        opacity: Line opacity (0-1)
        flicker: Subtle brightness variation

    Returns:
        Path to output video
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    line_height = _sanitize_ffmpeg_number(line_height, "line_height")
    opacity = _sanitize_ffmpeg_number(opacity, "opacity")
    flicker = _sanitize_ffmpeg_number(flicker, "flicker")

    # Use drawgrid filter to create scanlines - simpler and more reliable
    # drawgrid creates horizontal lines with specified spacing
    grid_spacing = line_height * 2
    line_thickness = line_height

    filters = f"drawgrid=w=iw:h={grid_spacing}:t={line_thickness}:c=black@{opacity}"

    if flicker > 0:
        # Add subtle flicker using eq filter
        filters += f",eq=brightness={flicker}*sin(t*10)"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        filters,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    _run_command(cmd)

    return output


def effect_noise(
    input_path: str,
    output: str,
    intensity: float = 0.05,
    mode: str = "film",
    animated: bool = True,
) -> str:
    """Apply film grain / digital noise.

    Args:
        input_path: Input video path
        output: Output video path
        intensity: Noise amount (0-1)
        mode: "film", "digital", or "color"
        animated: Whether noise changes per frame

    Returns:
        Path to output video
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    intensity = _sanitize_ffmpeg_number(intensity, "intensity")
    safe_strength = _sanitize_ffmpeg_number(intensity * 100, "noise_strength")
    noise_flags = "t+u" if animated else "u"

    if mode == "color":
        filters = f"format=yuv420p,noise=alls={safe_strength}:allf={noise_flags}"
    elif mode in {"film", "digital"}:
        filters = f"format=yuv420p,noise=c0s={safe_strength}:c0f={noise_flags}"
    else:
        filters = f"format=yuv420p,noise=c0s={safe_strength}:c0f={noise_flags}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        filters,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    _run_command(cmd)

    return output


def effect_glow(
    input_path: str,
    output: str,
    intensity: float = 0.5,
    radius: int = 10,
    threshold: float = 0.7,
) -> str:
    """Apply bloom/glow effect for highlights.

    Args:
        input_path: Input video path
        output: Output video path
        intensity: Glow strength (0-1)
        radius: Blur radius in pixels
        threshold: Brightness threshold (0-1) for glow

    Returns:
        Path to output video
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    radius = int(_sanitize_ffmpeg_number(radius, "radius"))
    intensity = _sanitize_ffmpeg_number(intensity, "intensity")
    # Guardrail: additive bloom can flood a channel and color-wash whole
    # frames. Keep the public default safe for autonomous agents unless a
    # future explicit "destructive" option is added.
    safe_intensity = min(intensity, DEFAULT_GLOW_MAX_SAFE_INTENSITY)
    threshold = _sanitize_ffmpeg_number(threshold, "threshold")

    # Extract highlights, blur them, overlay back
    threshold_8bit = int(threshold * 255)

    filters = (
        f"split[original][highlights];"
        f"[highlights]geq=lum='if(lt(lum(X,Y),{threshold_8bit}),0,lum(X,Y))',"
        f"gblur=sigma={radius}[glow];"
        f"[original][glow]blend=all_mode='screen':all_opacity={safe_intensity}"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        filters,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    try:
        _run_command(cmd)
    except ProcessingError as e:
        if "gblur" not in e.full_stderr:
            raise
        filters = (
            f"split[original][highlights];"
            f"[highlights]geq=lum='if(lt(lum(X,Y),{threshold_8bit}),0,lum(X,Y))',"
            f"boxblur={radius}:{radius}[glow];"
            f"[original][glow]blend=all_mode='screen':all_opacity={safe_intensity}"
        )
        cmd[5] = filters
        _run_command(cmd)

    return output


# ---------------------------------------------------------------------------
# Layout & Composition
# ---------------------------------------------------------------------------
