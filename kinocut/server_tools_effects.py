"""MCP tool registrations for visual effects, layouts, mograph, and transitions."""

from __future__ import annotations

import os
from typing import Any

from .paths import _auto_output
from .errors import MCPVideoError
from .server_app import _result, _safe_tool, _validation_error, mcp
from .validation import VALID_MOGRAPH_STYLES
from .ffmpeg_helpers import _validate_input_path
from .limits import MAX_MOGRAPH_FRAMES

VALID_TEXT_ANIMATIONS = {"fade", "glitch", "slide-up", "typewriter"}
VALID_GRID_LAYOUTS = {"2x2", "3x1", "1x3", "2x3"}
VALID_PIP_POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right"}
VALID_TEXT_POSITIONS = {"center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"}

# ---------------------------------------------------------------------------
# Visual Effects Tools (P1 Features)
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def effect_vignette(
    input_path: str,
    output_path: str | None = None,
    intensity: float = 0.5,
    radius: float = 0.8,
    smoothness: float = 0.5,
) -> dict[str, Any]:
    """Apply vignette effect - darkened edges.

    Creates a darkened border effect that draws attention to the center of the frame.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        intensity: Darkness amount 0-1. Default 0.5.
        radius: Vignette radius 0-1 (1 = edge of frame). Default 0.8.
        smoothness: Edge softness 0-1. Default 0.5.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (0.0 <= intensity <= 1.0):
        raise MCPVideoError(
            f"intensity must be between 0.0 and 1.0, got {intensity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= radius <= 1.0):
        raise MCPVideoError(
            f"radius must be between 0.0 and 1.0, got {radius}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= smoothness <= 1.0):
        raise MCPVideoError(
            f"smoothness must be between 0.0 and 1.0, got {smoothness}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import effect_vignette as _vignette

    output = output_path or _auto_output(input_path, "vignette")
    return _result(_vignette(input_path, output, intensity, radius, smoothness))


@mcp.tool()
@_safe_tool
def effect_chromatic_aberration(
    input_path: str,
    output_path: str,
    intensity: float = 2.0,
    angle: float = 0,
) -> dict[str, Any]:
    """Apply chromatic aberration - RGB channel separation.

    Creates a trendy RGB split effect popular in tech/glitch aesthetics.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        intensity: Pixel offset amount. Default 2.0.
        angle: Separation direction in degrees. Default 0 (horizontal).

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if intensity < 0:
        raise MCPVideoError(
            f"intensity must be non-negative, got {intensity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import effect_chromatic_aberration as _chroma

    return _result(_chroma(input_path, output_path, intensity, angle))


@mcp.tool()
@_safe_tool
def effect_scanlines(
    input_path: str,
    output_path: str,
    line_height: int = 2,
    opacity: float = 0.3,
    flicker: float = 0.1,
) -> dict[str, Any]:
    """Apply CRT-style scanlines overlay.

    Simulates old CRT monitor scanline effect with optional flicker.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        line_height: Pixels per scanline. Default 2.
        opacity: Line opacity 0-1. Default 0.3.
        flicker: Brightness variation 0-1. Default 0.1.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if line_height < 1:
        raise MCPVideoError(
            f"line_height must be at least 1, got {line_height}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= opacity <= 1.0):
        raise MCPVideoError(
            f"opacity must be between 0.0 and 1.0, got {opacity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= flicker <= 1.0):
        raise MCPVideoError(
            f"flicker must be between 0.0 and 1.0, got {flicker}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import effect_scanlines as _scanlines

    return _result(_scanlines(input_path, output_path, line_height, opacity, flicker))


@mcp.tool()
@_safe_tool
def effect_noise(
    input_path: str,
    output_path: str,
    intensity: float = 0.05,
    mode: str = "film",
    animated: bool = True,
) -> dict[str, Any]:
    """Apply film grain or digital noise.

    Adds texture noise to video for vintage or lo-fi aesthetics.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        intensity: Noise amount 0-1. Default 0.05.
        mode: Noise type (film, digital, color). Default film.
        animated: Whether noise changes per frame. Default true.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (0.0 <= intensity <= 1.0):
        raise MCPVideoError(
            f"intensity must be between 0.0 and 1.0, got {intensity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if mode not in ("film", "digital", "color"):
        raise MCPVideoError(
            f"mode must be film, digital, or color, got {mode}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import effect_noise as _noise

    return _result(_noise(input_path, output_path, intensity, mode, animated))


@mcp.tool()
@_safe_tool
def effect_glow(
    input_path: str,
    output_path: str,
    intensity: float = 0.5,
    radius: int = 10,
    threshold: float = 0.7,
) -> dict[str, Any]:
    """Apply bloom/glow effect for highlights.

    Creates a soft glow around bright areas of the video.

    Args:
        input_path: Absolute path to input video.
        output_path: Absolute path for output video.
        intensity: Glow strength 0-1. Default 0.5.
        radius: Blur radius in pixels. Default 10.
        threshold: Brightness threshold 0-1. Default 0.7.

    Returns:
        Dict with success status and output_path.
    """
    input_path = _validate_input_path(input_path)
    if not (0.0 <= intensity <= 1.0):
        raise MCPVideoError(
            f"intensity must be between 0.0 and 1.0, got {intensity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if radius < 0:
        raise MCPVideoError(
            f"radius must be non-negative, got {radius}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= threshold <= 1.0):
        raise MCPVideoError(
            f"threshold must be between 0.0 and 1.0, got {threshold}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import effect_glow as _glow

    return _result(_glow(input_path, output_path, intensity, radius, threshold))


@mcp.tool()
@_safe_tool
def video_layout_grid(
    clips: list[str],
    layout: str,
    output_path: str,
    gap: int = 10,
    padding: int = 20,
    background: str = "#141414",
) -> dict[str, Any]:
    """Create grid-based multi-video layout.

    Arranges multiple videos in a grid pattern (2x2, 3x1, etc.).

    Args:
        clips: List of absolute paths to video files.
        layout: Grid layout (2x2, 3x1, 1x3, 2x3).
        output_path: Absolute path for output video.
        gap: Pixels between clips. Default 10.
        padding: Padding around grid. Default 20.
        background: Background color hex. Default #141414.

    Returns:
        Dict with success status and output_path.
    """
    if layout not in VALID_GRID_LAYOUTS:
        raise MCPVideoError(
            f"layout must be one of {sorted(VALID_GRID_LAYOUTS)}, got {layout}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    for _p in clips:
        _validate_input_path(_p)
    if gap < 0:
        raise MCPVideoError(
            f"gap must be non-negative, got {gap}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if padding < 0:
        raise MCPVideoError(
            f"padding must be non-negative, got {padding}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import layout_grid as _grid

    return _result(_grid(clips, layout, output_path, gap, padding, background))


@mcp.tool()
@_safe_tool
def video_layout_pip(
    main_path: str,
    pip_path: str,
    output_path: str,
    position: str = "bottom-right",
    size: float = 0.25,
    margin: int = 20,
    border: bool = True,
    border_color: str = "#CCFF00",
    border_width: int = 2,
    rounded_corners: bool = True,
) -> dict[str, Any]:
    """Picture-in-picture overlay.

    Overlay a smaller video on top of a main video.

    Args:
        main_path: Absolute path to main video.
        pip_path: Absolute path to picture-in-picture video.
        output_path: Absolute path for output video.
        position: Position (top-left, top-right, bottom-left, bottom-right). Default bottom-right.
        size: PIP size as fraction of main. Default 0.25.
        margin: Margin from edges in pixels. Default 20.
        border: Add border around PIP. Default true.
        border_color: Border color hex. Default #CCFF00.
        border_width: Border width in pixels. Default 2.
        rounded_corners: Apply rounded corners to PIP. Default true.

    Returns:
        Dict with success status and output_path.
    """
    if position not in VALID_PIP_POSITIONS:
        raise MCPVideoError(
            f"position must be one of {sorted(VALID_PIP_POSITIONS)}, got {position}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    main_path = _validate_input_path(main_path)
    pip_path = _validate_input_path(pip_path)
    if not (0.0 < size <= 1.0):
        raise MCPVideoError(
            f"size must be between 0.0 and 1.0, got {size}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if border_width < 0:
        raise MCPVideoError(
            f"border_width must be non-negative, got {border_width}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import layout_pip as _pip

    return _result(
        _pip(
            main_path,
            pip_path,
            output_path,
            position=position,
            size=size,
            margin=margin,
            rounded_corners=rounded_corners,
            border=border,
            border_color=border_color,
            border_width=border_width,
        )
    )


@mcp.tool()
@_safe_tool
def video_text_animated(
    input_path: str,
    text: str,
    output_path: str | None = None,
    animation: str = "fade",
    font: str = "Arial",
    size: int = 48,
    color: str = "white",
    position: str = "center",
    start: float = 0,
    duration: float = 3.0,
    typewriter_speed: float = 0.08,
) -> dict[str, Any]:
    """Add animated text to video.

    Overlay text with animation effects (fade, slide, etc.).

    Args:
        input_path: Absolute path to input video.
        text: Text to display.
        output_path: Absolute path for output video.
        animation: Animation type (fade, slide-up, typewriter). Default fade.
        font: Font family. Default Arial.
        size: Font size. Default 48.
        color: Text color. Default white.
        position: Text position. Default center.
        start: Start time in seconds. Default 0.
        duration: Display duration. Default 3.0.

    Returns:
        Dict with success status and output_path.
    """
    if not text or not text.strip():
        raise MCPVideoError("Text cannot be empty", error_type="validation_error", code="invalid_parameter")
    if animation not in VALID_TEXT_ANIMATIONS:
        raise MCPVideoError(
            f"animation must be one of {sorted(VALID_TEXT_ANIMATIONS)}, got {animation}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if position not in VALID_TEXT_POSITIONS:
        raise MCPVideoError(
            f"position must be one of {sorted(VALID_TEXT_POSITIONS)}, got {position}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    input_path = _validate_input_path(input_path)
    if not (8 <= size <= 500):
        raise MCPVideoError(
            f"size must be between 8 and 500, got {size}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if duration <= 0:
        raise MCPVideoError(
            f"duration must be positive, got {duration}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if start < 0:
        raise MCPVideoError(
            f"start must be non-negative, got {start}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    from .effects_engine import text_animated as _text

    output = output_path or _auto_output(input_path, "animated")
    return _result(
        _text(input_path, text, output, animation, font, size, color, position, start, duration, typewriter_speed)
    )


@mcp.tool()
@_safe_tool
def video_subtitles_styled(
    input_path: str,
    subtitles_path: str,
    output_path: str,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Burn subtitles from SRT/VTT with custom styling.

    Embeds subtitle file into video with customizable appearance.

    Args:
        input_path: Absolute path to input video.
        subtitles_path: Absolute path to SRT or VTT file.
        output_path: Absolute path for output video.
        style: Optional style dict with font, size, color, outline, etc.

    Returns:
        Dict with success status and output_path.
    """
    if not os.path.isfile(subtitles_path):
        return _validation_error(f"Subtitles file not found: {subtitles_path}", code="file_not_found")
    input_path = _validate_input_path(input_path)
    subtitles_path = _validate_input_path(subtitles_path)
    from .effects_engine import text_subtitles as _subs

    return _result(_subs(input_path, subtitles_path, output_path, style))


@mcp.tool()
@_safe_tool
def video_mograph_count(
    start: int,
    end: int,
    duration: float,
    output_path: str,
    style: dict[str, Any] | None = None,
    fps: int = 30,
) -> dict[str, Any]:
    """Generate animated number counter video.

    Creates a standalone video of an animated counting number.

    Args:
        start: Starting number.
        end: Ending number.
        duration: Animation duration in seconds.
        output_path: Absolute path for output video.
        style: Optional style dict with font, size, color, glow.
        fps: Frame rate. Default 30.

    Returns:
        Dict with success status and output_path.
    """
    if not (1 <= fps <= 120):
        raise MCPVideoError(
            f"fps must be between 1 and 120, got {fps}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if duration <= 0:
        raise MCPVideoError(
            f"duration must be positive, got {duration}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    total_frames = int(duration * fps)
    if total_frames > MAX_MOGRAPH_FRAMES:
        raise MCPVideoError(
            f"mograph frame count {total_frames} exceeds maximum of {MAX_MOGRAPH_FRAMES}",
            error_type="resource_error",
            code="mograph_too_large",
        )
    from .effects_engine import mograph_count as _count

    return _result(_count(start, end, duration, output_path, style=style, fps=fps))


@mcp.tool()
@_safe_tool
def video_mograph_progress(
    duration: float,
    output_path: str,
    style: str = "bar",
    color: str = "#CCFF00",
    track_color: str = "#333333",
    fps: int = 30,
) -> dict[str, Any]:
    """Generate progress bar / loading animation.

    Creates a standalone progress animation video.

    Args:
        duration: Animation duration in seconds.
        output_path: Absolute path for output video.
        style: Progress style (bar, circle, dots). Default bar.
        color: Progress color hex. Default #CCFF00.
        track_color: Background track color hex. Default #333333.
        fps: Frame rate. Default 30.

    Returns:
        Dict with success status and output_path.
    """
    if style not in VALID_MOGRAPH_STYLES:
        return _validation_error(f"Invalid style: must be one of {sorted(VALID_MOGRAPH_STYLES)}, got '{style}'")
    if not (1 <= fps <= 120):
        raise MCPVideoError(
            f"fps must be between 1 and 120, got {fps}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if duration <= 0:
        raise MCPVideoError(
            f"duration must be positive, got {duration}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    total_frames = int(duration * fps)
    if total_frames > MAX_MOGRAPH_FRAMES:
        raise MCPVideoError(
            f"mograph frame count {total_frames} exceeds maximum of {MAX_MOGRAPH_FRAMES}",
            error_type="resource_error",
            code="mograph_too_large",
        )
    from .effects_engine import mograph_progress as _progress

    return _result(_progress(duration, output_path, style=style, color=color, track_color=track_color, fps=fps))


@mcp.tool()
@_safe_tool
def video_info_detailed(
    input_path: str,
) -> dict[str, Any]:
    """Get extended video metadata.

    Returns detailed video information including scene change detection
    and dominant colors.

    Args:
        input_path: Absolute path to input video.

    Returns:
        Dict with duration, fps, resolution, bitrate, has_audio, scene_changes.
    """
    input_path = _validate_input_path(input_path)
    from .effects_engine import video_info_detailed as _info

    return _result(_info(input_path))


@mcp.tool()
@_safe_tool
def video_auto_chapters(
    input_path: str,
    threshold: float = 0.3,
) -> dict[str, Any]:
    """Auto-detect scene changes and create chapters.

    Analyzes video for scene cuts and returns chapter timestamps.

    Args:
        input_path: Absolute path to input video.
        threshold: Scene detection threshold 0-1. Default 0.3.

    Returns:
        List of (timestamp, description) chapter tuples.
    """
    if not 0.0 <= threshold <= 1.0:
        return _validation_error(f"threshold must be between 0.0 and 1.0, got {threshold}")
    input_path = _validate_input_path(input_path)
    from .effects_engine import auto_chapters as _chapters

    return _result(_chapters(input_path, threshold))


# ---------------------------------------------------------------------------
# Transition Tools (Advanced Effects)
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def transition_glitch(
    clip1_path: str,
    clip2_path: str,
    output_path: str | None = None,
    duration: float = 0.5,
    intensity: float = 0.3,
) -> dict[str, Any]:
    """Apply glitch transition between two video clips.

    Args:
        clip1_path: Absolute path to first video clip.
        clip2_path: Absolute path to second video clip.
        output_path: Absolute path for output video.
        duration: Transition duration in seconds (default 0.5).
        intensity: Glitch intensity 0-1 (default 0.3).
    """
    if duration <= 0:
        return _validation_error(f"duration must be positive, got {duration}")
    if not 0.0 <= intensity <= 1.0:
        return _validation_error(f"intensity must be between 0.0 and 1.0, got {intensity}")
    clip1_path = _validate_input_path(clip1_path)
    clip2_path = _validate_input_path(clip2_path)
    from .transitions_engine import transition_glitch

    output = output_path or _auto_output(clip1_path, "transition")
    return _result(transition_glitch(clip1_path, clip2_path, output, duration, intensity))


@mcp.tool()
@_safe_tool
def transition_pixelate(
    clip1_path: str,
    clip2_path: str,
    output_path: str,
    duration: float = 0.4,
    pixel_size: int = 50,
) -> dict[str, Any]:
    """Apply pixelate transition between two video clips."""
    if duration <= 0:
        return _validation_error(f"duration must be positive, got {duration}")
    if pixel_size < 2:
        return _validation_error(f"pixel_size must be at least 2, got {pixel_size}")
    clip1_path = _validate_input_path(clip1_path)
    clip2_path = _validate_input_path(clip2_path)
    from .transitions_engine import transition_pixelate

    return _result(transition_pixelate(clip1_path, clip2_path, output_path, duration, pixel_size))


@mcp.tool()
@_safe_tool
def transition_morph(
    clip1_path: str,
    clip2_path: str,
    output_path: str,
    duration: float = 0.6,
    mesh_size: int = 10,
) -> dict[str, Any]:
    """Apply morph transition between two video clips."""
    if duration <= 0:
        return _validation_error(f"duration must be positive, got {duration}")
    if mesh_size < 2:
        return _validation_error(f"mesh_size must be at least 2, got {mesh_size}")
    clip1_path = _validate_input_path(clip1_path)
    clip2_path = _validate_input_path(clip2_path)
    from .transitions_engine import transition_morph

    return _result(transition_morph(clip1_path, clip2_path, output_path, duration, mesh_size))
