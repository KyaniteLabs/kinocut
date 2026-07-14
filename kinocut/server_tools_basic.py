"""Basic MCP video tool registrations."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

import functools

import anyio
from mcp.server.fastmcp import Context

from .engine import add_audio, add_text, add_texts, convert, merge, probe, resize, speed, trim
from .contracts.receipt_ai_video import AiVideoReceiptSection
from .receipts_ai_video import attach_ai_video_section
from .limits import MAX_RESOLUTION, MAX_SPEED_FACTOR, MIN_SPEED_FACTOR, MIN_CRF, MAX_CRF
from .server_app import _mcp_progress_reporter, _result, _safe_tool, _validation_error, mcp
from .validation import DURATION_POLICIES, VALID_FORMATS, VALID_PRESETS, VALID_XFADE_TRANSITIONS
from .models import QUALITY_PRESETS
from .ffmpeg_helpers import _validate_input_path


def _attach_add_audio_receipt(result: dict[str, Any], duration_policy: str) -> dict[str, Any]:
    """Record the chosen duration_policy (and any preservation warning) in the receipt.

    Additive only: an ``ai_video`` section is attached without touching any legacy
    result field. ``shortest`` records the ``outro_may_be_trimmed`` warning code.
    """

    if not isinstance(result, dict) or not result.get("success"):
        return result
    warnings = ("outro_may_be_trimmed",) if duration_policy == "shortest" else ()
    section = AiVideoReceiptSection(project_id="add_audio", duration_policy=duration_policy, warnings=warnings)
    return attach_ai_video_section(result, section)


ExistingVideoPath = Annotated[
    str,
    Field(description="Absolute path to an existing local video file. The input file is read only."),
]
ExistingAudioPath = Annotated[
    str,
    Field(description="Absolute path to an existing local audio file such as MP3, WAV, M4A, or AAC."),
]
OptionalOutputVideoPath = Annotated[
    str | None,
    Field(
        description="Destination video path. Auto-generated when omitted; an existing supplied path may be overwritten."
    ),
]


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


@mcp.tool(
    title="Merge video clips",
    description=(
        "Concatenate two or more existing video clips into one rendered output file. "
        "The input clips are read only and kept unchanged; the tool creates an auto-named output "
        "or writes to output_path, using FFmpeg and reporting transition or media-mismatch validation errors."
    ),
    annotations=ToolAnnotations(
        title="Merge video clips",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_merge(
    clips: Annotated[
        list[str],
        Field(
            description=(
                "Ordered absolute paths to existing video clips. Provide at least two clips; "
                "inputs are validated and never modified."
            )
        ),
    ],
    output_path: OptionalOutputVideoPath = None,
    transition: Annotated[
        str | None,
        Field(
            description=(
                "Optional xfade transition applied to every clip boundary, such as fade, "
                "dissolve, wipeleft, wiperight, slideleft, or slideright."
            )
        ),
    ] = None,
    transitions: Annotated[
        list[str] | None,
        Field(description="Optional per-boundary xfade transitions. Overrides transition when provided."),
    ] = None,
    transition_duration: Annotated[
        float,
        Field(description="Duration in seconds for each transition; must fit inside neighboring clips."),
    ] = 1.0,
) -> dict[str, Any]:
    """Merge multiple video clips into one rendered output file.

    Args:
        clips: Ordered list of absolute paths to existing video clips. Requires at least
            two clips for a meaningful merge; each input path is validated and never modified.
        output_path: Destination for the merged render. Auto-generated if omitted; may be
            overwritten if an existing path is supplied.
        transition: Optional single xfade transition for every clip pair, such as fade,
            dissolve, wipeleft, wiperight, slideleft, or slideright.
        transitions: Optional per-pair transition list. Overrides transition when both
            are provided and should have one entry per gap between clips.
        transition_duration: Duration of each transition in seconds. Must fit inside the
            shortest neighboring clip.
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


@mcp.tool(
    title="Add or mix video audio",
    description=(
        "Add, replace, or mix an audio file into an existing video and render a new output file. "
        "The source video and audio are read only; output_path is created or overwritten. "
        "Controls volume, fade-in, fade-out, mix/replace mode, and optional start time."
    ),
    annotations=ToolAnnotations(
        title="Add or mix video audio",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_add_audio(
    video_path: ExistingVideoPath,
    audio_path: ExistingAudioPath,
    volume: Annotated[
        float,
        Field(description="Audio gain from 0.0 to 2.0, where 1.0 preserves original loudness."),
    ] = 1.0,
    fade_in: Annotated[
        float,
        Field(description="Non-negative fade-in duration in seconds applied to the inserted audio."),
    ] = 0.0,
    fade_out: Annotated[
        float,
        Field(description="Non-negative fade-out duration in seconds applied near the inserted audio end."),
    ] = 0.0,
    mix: Annotated[
        bool,
        Field(
            description="True mixes the new audio with existing video audio; false replaces the original audio track."
        ),
    ] = False,
    start_time: Annotated[
        float | None,
        Field(description="Optional start offset in seconds where the inserted audio begins."),
    ] = None,
    output_path: OptionalOutputVideoPath = None,
    duration_policy: Annotated[
        str,
        Field(
            description="How to reconcile audio and video length: keep_video (default, preserves the "
            "full video/outro), pad_audio, loop_audio, trim_audio, or shortest (may trim the outro)."
        ),
    ] = "keep_video",
) -> dict[str, Any]:
    """Add, replace, or mix an audio track into a video.

    Args:
        video_path: Absolute path to the existing video file. The input file is read only.
        audio_path: Absolute path to the existing audio file, such as MP3, WAV, M4A, or AAC.
        volume: Audio gain from 0.0 to 2.0, where 1.0 keeps original loudness.
        fade_in: Non-negative fade-in duration in seconds applied to the inserted audio.
        fade_out: Non-negative fade-out duration in seconds applied near the inserted audio end.
        mix: True mixes the new audio with existing video audio; False replaces the
            video's original audio track.
        start_time: Optional start offset in seconds for the inserted audio.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
    """
    video_path = _validate_input_path(video_path)
    audio_path = _validate_input_path(audio_path)
    if not 0 <= volume <= 2.0:
        return _validation_error(f"volume must be between 0.0 and 2.0, got {volume}")
    if fade_in is not None and fade_in < 0:
        return _validation_error(f"fade_in must be non-negative, got {fade_in}")
    if fade_out is not None and fade_out < 0:
        return _validation_error(f"fade_out must be non-negative, got {fade_out}")
    if duration_policy not in DURATION_POLICIES:
        # Never echo the raw (possibly hostile) value back into a public error.
        return _validation_error(f"duration_policy must be one of {DURATION_POLICIES}", code="invalid_duration_policy")
    result = _result(
        add_audio(
            video_path,
            audio_path=audio_path,
            volume=volume,
            fade_in=fade_in,
            fade_out=fade_out,
            mix=mix,
            start_time=start_time,
            output_path=output_path,
            duration_policy=duration_policy,
        )
    )
    return _attach_add_audio_receipt(result, duration_policy)


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


@mcp.tool(
    title="Convert video format",
    description=(
        "Transcode an existing video into a different container or codec format such as mp4, webm, gif, or mov. "
        "Use this for format conversion; use video_export for final delivery presets. "
        "The input video is read only and a new output file is rendered."
    ),
    annotations=ToolAnnotations(
        title="Convert video format",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
async def video_convert(
    input_path: ExistingVideoPath,
    format: Annotated[
        str,
        Field(description="Target output format: mp4, webm, gif, mov, hevc, av1, or prores."),
    ] = "mp4",
    quality: Annotated[
        str,
        Field(description="Encoding quality preset: low, medium, high, or ultra."),
    ] = "high",
    output_path: OptionalOutputVideoPath = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Convert a video to a different format or codec.

    Use ``video_convert`` when you need to change the container or codec
    (e.g. mp4 → webm, or re-encode with a different CRF). For simple final
    delivery with quality tuning, prefer :func:`video_export`. Long renders
    stream MCP progress notifications so clients can show a live percentage.

    Args:
        input_path: Absolute path to the existing input video. The source is read only.
        format: Target output format. Supported values are mp4, webm, gif, mov,
            hevc, av1, and prores.
        quality: Encoding quality preset. Supported values come from QUALITY_PRESETS:
            low, medium, high, and ultra.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
    """
    if format not in VALID_FORMATS:
        return _validation_error(f"Invalid format: {format}. Must be one of {sorted(VALID_FORMATS)}")
    if quality not in QUALITY_PRESETS:
        return _validation_error(f"Invalid quality: {quality}. Must be one of {sorted(QUALITY_PRESETS)}")
    input_path = _validate_input_path(input_path)
    run_convert = functools.partial(
        convert,
        input_path,
        format=format,
        quality=quality,
        output_path=output_path,
        on_progress=_mcp_progress_reporter(ctx),
    )
    return _result(await anyio.to_thread.run_sync(run_convert))


@mcp.tool(
    title="Change video speed",
    description=(
        "Render a new video with playback speed changed while keeping the source video unchanged. "
        "Values below 1.0 create slow motion and values above 1.0 create fast motion; "
        "the factor is validated against configured speed limits."
    ),
    annotations=ToolAnnotations(
        title="Change video speed",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_speed(
    input_path: ExistingVideoPath,
    factor: Annotated[
        float,
        Field(description="Playback speed multiplier. 2.0 is double speed, 0.5 is half speed, and 1.0 is unchanged."),
    ] = 1.0,
    output_path: OptionalOutputVideoPath = None,
) -> dict[str, Any]:
    """Change video playback speed and render a new output file.

    Args:
        input_path: Absolute path to the existing input video. The source is read only.
        factor: Speed multiplier within the configured allowed range. 2.0 is 2x
            faster, 0.5 is half-speed slow motion, and 1.0 means no speed change.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
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
    every registered tool description. Returns matching tools with their names,
    descriptions, and required parameters.

    Args:
        query: Search term — e.g. "blur", "resize", "subtitle", "audio", "trim".
    """
    # Ensure all tool modules are loaded so the registry is complete.
    # We import sibling modules (not the facade) to populate the registry.
    from . import (  # noqa: F401
        server_tools_advanced,
        server_tools_aivideo,
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
