"""Basic MCP video tool registrations."""

from __future__ import annotations

from typing import Any

from .engine import add_audio, add_text, add_texts, convert, merge, probe, resize, speed, trim
from .limits import MAX_RESOLUTION, MAX_SPEED_FACTOR, MIN_SPEED_FACTOR, MIN_CRF, MAX_CRF
from .server_app import _result, _safe_tool, _validation_error, mcp
from .validation import VALID_FORMATS, VALID_PRESETS
from .models import QUALITY_PRESETS
from .ffmpeg_helpers import _validate_input_path


@mcp.tool()
@_safe_tool
def video_info(input_path: str) -> dict[str, Any]:
    """Get metadata about a video file: duration, resolution, codec, fps, size.

    Args:
        input_path: Absolute path to the video file.
    """
    input_path = _validate_input_path(input_path)
    info = probe(input_path)
    data = info.model_dump()
    data["display_width"] = info.display_width
    data["display_height"] = info.display_height
    data["display_resolution"] = info.display_resolution
    data["aspect_ratio"] = info.aspect_ratio
    return {"success": True, "info": data}


@mcp.tool()
@_safe_tool
def video_trim(
    input_path: str,
    start: str = "0",
    duration: str | None = None,
    end: str | None = None,
    output_path: str | None = None,
    accurate: bool = False,
) -> dict[str, Any]:
    """Trim a video clip by start time and duration.

    Args:
        input_path: Absolute path to the input video.
        start: Start timestamp (e.g. '00:02:15' or seconds as string like '10.5').
        duration: Duration to keep (e.g. '00:00:30' or '30'). Exclusive with end.
        end: End timestamp. Exclusive with duration.
        output_path: Where to save the trimmed video. Auto-generated if omitted.
        accurate: Frame-accurate seeking (slower).  Default False uses fast
            input seeking which may land on the nearest keyframe.
    """
    input_path = _validate_input_path(input_path)
    return _result(
        trim(input_path, start=start, duration=duration, end=end, output_path=output_path, accurate=accurate)
    )


VALID_XFADE_TRANSITIONS = {
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "circlecrop",
    "radial",
    "smoothleft",
    "smoothright",
    "smoothup",
    "smoothdown",
}


@mcp.tool()
@_safe_tool
def video_merge(
    clips: list[str],
    output_path: str | None = None,
    transition: str | None = None,
    transitions: list[str] | None = None,
    transition_duration: float = 1.0,
) -> dict[str, Any]:
    """Merge multiple video clips into one.

    Args:
        clips: List of absolute paths to video clips to merge (in order).
        output_path: Where to save the merged video. Auto-generated if omitted.
        transition: Single transition type for all clip pairs (fade, dissolve, wipe-*).
        transitions: Per-pair transition types. Overrides transition if both provided.
        transition_duration: Duration of each transition in seconds.
    """
    if transition is not None and transition not in VALID_XFADE_TRANSITIONS:
        return _validation_error(
            f"Invalid transition '{transition}'. Must be one of: {', '.join(sorted(VALID_XFADE_TRANSITIONS))}"
        )
    if transitions is not None:
        invalid = [t for t in transitions if t not in VALID_XFADE_TRANSITIONS]
        if invalid:
            return _validation_error(
                f"Invalid transition(s): {', '.join(invalid)}. "
                f"Must be one of: {', '.join(sorted(VALID_XFADE_TRANSITIONS))}"
            )
    for _p in clips:
        _validate_input_path(_p)
    return _result(
        merge(
            clips,
            output_path=output_path,
            transition=transition,
            transitions=transitions,
            transition_duration=transition_duration,
        )
    )


@mcp.tool()
@_safe_tool
def video_add_text(
    input_path: str,
    text: str,
    position: str | dict = "top-center",
    font: str | None = None,
    size: int = 48,
    color: str = "white",
    shadow: bool = True,
    start_time: float | None = None,
    duration: float | None = None,
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
) -> dict[str, Any]:
    """Overlay text on a video (titles, captions, watermarks).

    Args:
        input_path: Absolute path to the input video.
        text: Text to overlay.
        position: Position on screen. Named (top-left, top-center, etc.), pixel"
                  " {\"x\": 100, \"y\": 50}, or percentage {\"x_pct\": 0.5, \"y_pct\": 0.5}.
        font: Path to font file. Uses system default if omitted.
        size: Font size in pixels.
        color: Text color (CSS color name or hex).
        shadow: Add text shadow for readability.
        start_time: When the text appears (seconds). Null = always visible.
        duration: How long text is visible (seconds). Requires start_time.
        output_path: Where to save the output. Auto-generated if omitted.
        crf: Override CRF value (0-51, lower = better quality). Default 23.
        preset: Override FFmpeg encoding preset (ultrafast, fast, medium, slow, veryslow).
    """
    if crf is not None and not (MIN_CRF <= crf <= MAX_CRF):
        return _validation_error(f"crf must be {MIN_CRF}-{MAX_CRF}, got {crf}")
    if preset is not None and preset not in VALID_PRESETS:
        return _validation_error(f"Invalid preset: {preset}")
    input_path = _validate_input_path(input_path)
    if size < 8 or size > 500:
        return _validation_error(f"Font size must be between 8 and 500, got {size}")
    return _result(
        add_text(
            input_path,
            text=text,
            position=position,
            font=font,
            size=size,
            color=color,
            shadow=shadow,
            start_time=start_time,
            duration=duration,
            output_path=output_path,
            crf=crf,
            preset=preset,
        )
    )


@mcp.tool()
@_safe_tool
def video_add_texts(
    input_path: str,
    texts: list[dict],
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
    auto_layout: bool = True,
) -> dict[str, Any]:
    """Overlay multiple text elements on a video in a single FFmpeg pass.

    Automatically detects overlapping text and distributes vertically stacked
    texts when they share the same named position.

    Args:
        input_path: Absolute path to the input video.
        texts: List of text overlay dicts. Each dict may contain:
            - text (str, required)
            - position (str|dict, default "center")
            - font (str, optional)
            - size (int, default 48)
            - color (str, default "white")
            - shadow (bool, default True)
            - start_time (float, optional)
            - duration (float, optional)
        output_path: Where to save the output. Auto-generated if omitted.
        crf: Override CRF value (0-51, lower = better quality). Default 23.
        preset: Override FFmpeg encoding preset (ultrafast, fast, medium, slow, veryslow).
        auto_layout: Automatically distribute vertically stacked texts at the
            same named position. Default True.
    """
    if crf is not None and not (MIN_CRF <= crf <= MAX_CRF):
        return _validation_error(f"crf must be {MIN_CRF}-{MAX_CRF}, got {crf}")
    if preset is not None and preset not in VALID_PRESETS:
        return _validation_error(f"Invalid preset: {preset}")
    input_path = _validate_input_path(input_path)
    if not texts:
        return _validation_error("texts list cannot be empty")
    for i, t in enumerate(texts):
        size = t.get("size", 48)
        if size < 8 or size > 500:
            return _validation_error(f"Font size must be between 8 and 500, got {size} at index {i}")
    return _result(
        add_texts(
            input_path,
            texts=texts,
            output_path=output_path,
            crf=crf,
            preset=preset,
            auto_layout=auto_layout,
        )
    )


@mcp.tool()
@_safe_tool
def video_add_audio(
    video_path: str,
    audio_path: str,
    volume: float = 1.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    mix: bool = False,
    start_time: float | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Add or replace the audio track of a video.

    Args:
        video_path: Absolute path to the video file.
        audio_path: Absolute path to the audio file (MP3, WAV, etc.).
        volume: Audio volume (0.0 to 2.0, where 1.0 = original).
        fade_in: Fade in duration in seconds.
        fade_out: Fade out duration in seconds.
        mix: If true, mix with existing audio. If false, replace it.
        start_time: When the audio starts playing (seconds).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    video_path = _validate_input_path(video_path)
    audio_path = _validate_input_path(audio_path)
    if not 0 <= volume <= 2.0:
        return _validation_error(f"volume must be between 0.0 and 2.0, got {volume}")
    if fade_in is not None and fade_in < 0:
        return _validation_error(f"fade_in must be non-negative, got {fade_in}")
    if fade_out is not None and fade_out < 0:
        return _validation_error(f"fade_out must be non-negative, got {fade_out}")
    return _result(
        add_audio(
            video_path,
            audio_path=audio_path,
            volume=volume,
            fade_in=fade_in,
            fade_out=fade_out,
            mix=mix,
            start_time=start_time,
            output_path=output_path,
        )
    )


@mcp.tool()
@_safe_tool
def video_resize(
    input_path: str,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str | None = None,
    quality: str = "high",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Resize a video or change its aspect ratio.

    Args:
        input_path: Absolute path to the input video.
        width: Target width in pixels. Use with height.
        height: Target height in pixels. Use with width.
        aspect_ratio: Preset aspect ratio (16:9, 9:16, 1:1, 4:3, 4:5, 21:9). Overrides width/height.
        quality: Quality preset (low, medium, high, ultra).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    if width is not None and width > MAX_RESOLUTION:
        return _validation_error(
            f"Width {width} exceeds maximum resolution of {MAX_RESOLUTION}", code="resolution_too_high"
        )
    if width is not None and width <= 0:
        return _validation_error(f"Width must be positive, got {width}")
    if height is not None and height > MAX_RESOLUTION:
        return _validation_error(
            f"Height {height} exceeds maximum resolution of {MAX_RESOLUTION}", code="resolution_too_high"
        )
    if height is not None and height <= 0:
        return _validation_error(f"Height must be positive, got {height}")
    input_path = _validate_input_path(input_path)
    return _result(
        resize(
            input_path,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            quality=quality,
            output_path=output_path,
        )
    )


@mcp.tool()
@_safe_tool
def video_convert(
    input_path: str,
    format: str = "mp4",
    quality: str = "high",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Convert a video to a different format or codec.

    Use ``video_convert`` when you need to change the container or codec
    (e.g. mp4 → webm, or re-encode with a different CRF). For simple final
    delivery with quality tuning, prefer :func:`video_export`.

    Args:
        input_path: Absolute path to the input video.
        format: Target format (mp4, webm, gif, mov).
        quality: Quality preset (low, medium, high, ultra).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    if format not in VALID_FORMATS:
        return _validation_error(f"Invalid format: {format}. Must be one of {sorted(VALID_FORMATS)}")
    if quality not in QUALITY_PRESETS:
        return _validation_error(f"Invalid quality: {quality}. Must be one of {sorted(QUALITY_PRESETS)}")
    input_path = _validate_input_path(input_path)
    return _result(
        convert(
            input_path,
            format=format,
            quality=quality,
            output_path=output_path,
        )
    )


@mcp.tool()
@_safe_tool
def video_speed(
    input_path: str,
    factor: float = 1.0,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Change video playback speed.

    Args:
        input_path: Absolute path to the input video.
        factor: Speed multiplier. 2.0 = 2x faster (time-lapse), 0.5 = half speed (slow-mo).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    if not (MIN_SPEED_FACTOR <= factor <= MAX_SPEED_FACTOR):
        return _validation_error(
            f"Speed factor {factor} out of range [{MIN_SPEED_FACTOR}, {MAX_SPEED_FACTOR}]", code="speed_out_of_range"
        )
    input_path = _validate_input_path(input_path)
    return _result(speed(input_path, factor=factor, output_path=output_path))


@mcp.tool()
@_safe_tool
def search_tools(query: str) -> dict[str, Any]:
    """Search registered MCP tools by keyword.

    Use this when you need to find the right tool for a task without reading
    all 91 tool descriptions. Returns matching tools with their names,
    descriptions, and required parameters.

    Args:
        query: Search term — e.g. "blur", "resize", "subtitle", "audio", "trim".
    """
    # Ensure all tool modules are loaded so the registry is complete.
    # We import sibling modules (not the facade) to populate the registry.
    from . import (  # noqa: F401
        server_tools_advanced,
        server_tools_ai,
        server_tools_audio,
        server_tools_creation,
        server_tools_effects,
        server_tools_hyperframes,
        server_tools_image,
        server_tools_media,
    )

    query_lower = query.lower()
    matches: list[dict[str, Any]] = []
    for name, tool in mcp._tool_manager._tools.items():
        if name == "search_tools":
            continue
        desc = (tool.description or "").lower()
        if query_lower in name.lower() or query_lower in desc:
            # Extract required params from JSON schema
            params = tool.parameters or {}
            required = params.get("required", [])
            matches.append(
                {
                    "name": name,
                    "description": (tool.description or "").split("\n")[0].strip(),
                    "required_params": required,
                }
            )
    return {"success": True, "query": query, "count": len(matches), "tools": matches}
