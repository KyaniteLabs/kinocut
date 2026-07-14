"""Media MCP video tool registrations."""

from __future__ import annotations

import contextlib
import os
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .engine import (
    crop,
    edit_timeline,
    export_video,
    extract_audio,
    fade,
    preview,
    rotate,
    storyboard,
    subtitles,
    thumbnail,
    watermark,
)
from .errors import MCPVideoError
from .models import _validate_position
from .server_app import _error_result, _result, _safe_tool, _validation_error, mcp
from .templates import TEMPLATES, preview_template
from .validation import VALID_AUDIO_FORMATS, VALID_FORMATS, VALID_PRESETS
from .ffmpeg_helpers import _get_video_duration, _validate_input_path

ExistingVideoPath = Annotated[
    str,
    Field(description="Absolute path to an existing local video file. The input file is read only."),
]
ExistingImagePath = Annotated[
    str,
    Field(description="Absolute path to an existing local image file used as an overlay or watermark."),
]
OptionalOutputVideoPath = Annotated[
    str | None,
    Field(
        description="Destination video path. Auto-generated when omitted; an existing supplied path may be overwritten."
    ),
]
OptionalCrf = Annotated[
    int | None,
    Field(description="Optional FFmpeg CRF override from 0 to 51, where lower means higher quality."),
]
OptionalPreset = Annotated[
    str | None,
    Field(description="Optional FFmpeg encoding preset: ultrafast, fast, medium, slow, or veryslow."),
]


@mcp.tool()
@_safe_tool
def video_thumbnail(
    input_path: str,
    timestamp: float | str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Extract a single frame (thumbnail / frame grab) from a video.

    Args:
        input_path: Absolute path to the input video.
        timestamp: Time in seconds to extract frame. Defaults to 10% of video duration.
        output_path: Where to save the frame image. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    return _result(thumbnail(input_path, timestamp=timestamp, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_preview(
    input_path: str,
    output_path: str | None = None,
    scale_factor: int = 4,
) -> dict[str, Any]:
    """Generate a fast low-resolution preview for quick review.

    Args:
        input_path: Absolute path to the input video.
        output_path: Where to save the preview. Auto-generated if omitted.
        scale_factor: Downscale factor (4 = 1/4 resolution).
    """
    input_path = _validate_input_path(input_path)
    MAX_SCALE_FACTOR = 16
    if scale_factor < 2:
        return _validation_error(f"scale_factor must be at least 2, got {scale_factor}")
    if scale_factor > MAX_SCALE_FACTOR:
        return _validation_error(f"scale_factor must be at most {MAX_SCALE_FACTOR}, got {scale_factor}")
    return _result(preview(input_path, output_path=output_path, scale_factor=scale_factor))


@mcp.tool()
@_safe_tool
def video_storyboard(
    input_path: str,
    output_dir: str | None = None,
    frame_count: int = 8,
) -> dict[str, Any]:
    """Extract key frames and create a storyboard grid for human review.

    Args:
        input_path: Absolute path to the input video.
        output_dir: Directory to save frames. Auto-generated if omitted.
        frame_count: Number of key frames to extract.
    """
    input_path = _validate_input_path(input_path)
    MAX_FRAME_COUNT = 100
    if frame_count is not None and (frame_count < 1 or frame_count > MAX_FRAME_COUNT):
        return _validation_error(f"frame_count must be between 1 and {MAX_FRAME_COUNT}, got {frame_count}")
    return _result(storyboard(input_path, output_dir=output_dir, frame_count=frame_count))


@mcp.tool()
@_safe_tool
def video_subtitles(
    input_path: str,
    subtitle_path: str,
    output_path: str | None = None,
    style: str | None = None,
) -> dict[str, Any]:
    """Burn subtitles (SRT/VTT/authored ASS) into a video.

    Args:
        input_path: Absolute path to the input video.
        subtitle_path: Absolute path to the subtitle file (.srt, .vtt, or .ass).
        output_path: Where to save the output. Auto-generated if omitted.
        style: Optional force_style override applied to any subtitle format including
            authored ASS (e.g. "FontSize=24,PrimaryColour=&H00FFFFFF"). Omit to preserve
            an authored ASS file's own styling/positioning.
    """
    input_path = _validate_input_path(input_path)
    subtitle_path = _validate_input_path(subtitle_path)
    return _result(subtitles(input_path, subtitle_path=subtitle_path, output_path=output_path, style=style))


@mcp.tool(
    title="Add video watermark",
    description=(
        "Overlay an image watermark onto an existing video and render a new output file. "
        "The video and watermark image are read only; output_path is created or overwritten. "
        "Supports named, pixel, and percentage positions plus opacity, margin, CRF, and preset controls."
    ),
    annotations=ToolAnnotations(
        title="Add video watermark",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_watermark(
    input_path: ExistingVideoPath,
    image_path: ExistingImagePath,
    position: Annotated[
        str | dict,
        Field(
            description=(
                "Watermark position: named position such as bottom-right, pixel dict "
                '{"x": 100, "y": 50}, or percentage dict {"x_pct": 0.5, "y_pct": 0.5}.'
            )
        ),
    ] = "bottom-right",
    opacity: Annotated[
        float,
        Field(description="Watermark opacity from 0.0 fully transparent to 1.0 fully opaque."),
    ] = 0.7,
    margin: Annotated[
        int,
        Field(description="Non-negative edge margin in pixels for named positions."),
    ] = 20,
    output_path: OptionalOutputVideoPath = None,
    crf: OptionalCrf = None,
    preset: OptionalPreset = None,
) -> dict[str, Any]:
    """Add an image watermark to a video and render a new output file.

    Args:
        input_path: Absolute path to the existing input video. The source is read only.
        image_path: Absolute path to the watermark image. PNG with transparency is recommended.
        position: Watermark position. Accepts named positions such as top-left and
            bottom-right, pixel dicts like {"x": 100, "y": 50}, or percentage dicts
            like {"x_pct": 0.5, "y_pct": 0.5}.
        opacity: Watermark opacity from 0.0 fully transparent to 1.0 fully opaque.
        margin: Non-negative edge margin in pixels for named positions.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
        crf: Optional CRF override from 0 to 51, where lower means higher quality.
        preset: Optional FFmpeg encoding preset: ultrafast, fast, medium, slow, or veryslow.
    """
    try:
        _validate_position(position)
    except MCPVideoError as exc:
        return _validation_error(str(exc))
    if not 0 <= opacity <= 1:
        return _validation_error(f"opacity must be between 0 and 1, got {opacity}")
    if margin < 0:
        return _validation_error(f"margin must be non-negative, got {margin}")
    if crf is not None and not (0 <= crf <= 51):
        return _validation_error(f"crf must be 0-51, got {crf}")
    if preset is not None and preset not in VALID_PRESETS:
        return _validation_error(f"Invalid preset: {preset}")
    input_path = _validate_input_path(input_path)
    image_path = _validate_input_path(image_path)
    return _result(
        watermark(
            input_path,
            image_path=image_path,
            position=position,
            opacity=opacity,
            margin=margin,
            output_path=output_path,
            crf=crf,
            preset=preset,
        )
    )


@mcp.tool(
    title="Export video for delivery",
    description=(
        "Re-encode an existing video for final delivery using a quality preset and output format. "
        "Use this for publishing-ready renders; use video_convert when the main goal is container/codec conversion. "
        "The source video is read only and a new output file is produced."
    ),
    annotations=ToolAnnotations(
        title="Export video for delivery",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_export(
    input_path: ExistingVideoPath,
    output_path: OptionalOutputVideoPath = None,
    quality: Annotated[
        str,
        Field(description="Delivery quality preset: low, medium, high, or ultra."),
    ] = "high",
    format: Annotated[
        str,
        Field(description="Output format for delivery. Supported values are mp4, webm, gif, and mov."),
    ] = "mp4",
    c2pa_manifest_path: Annotated[
        str | None,
        Field(description="Optional C2PA manifest definition JSON to sign the final mp4 export."),
    ] = None,
    c2pa_tool_path: Annotated[
        str | None,
        Field(
            description="Optional path to the c2patool executable. Defaults to KINOCUT_C2PATOOL/MCP_VIDEO_C2PATOOL/PATH."
        ),
    ] = None,
    c2pa_signer_path: Annotated[
        str | None,
        Field(description="Optional c2patool subprocess signer command for external signing credentials."),
    ] = None,
) -> dict[str, Any]:
    """Export a video for final delivery with quality tuning.

    Use ``video_export`` when you want to re-encode a video for publishing
    with a quality preset (e.g. high-quality mp4 for YouTube).  For
    format/converter changes (mp4 → webm, gif), prefer :func:`video_convert`.

    Args:
        input_path: Absolute path to the existing input video. The source is read only.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
        quality: Delivery quality preset: low, medium, high, or ultra.
        format: Output format. Supported values are mp4, webm, gif, and mov.
    """
    if format not in VALID_FORMATS:
        return _validation_error(f"Invalid format: {format}. Must be one of {sorted(VALID_FORMATS)}")
    input_path = _validate_input_path(input_path)
    return _result(
        export_video(
            input_path,
            output_path=output_path,
            quality=quality,
            format=format,
            c2pa_manifest_path=c2pa_manifest_path,
            c2pa_tool_path=c2pa_tool_path,
            c2pa_signer_path=c2pa_signer_path,
        )
    )


@mcp.tool(
    title="Crop video frame",
    description=(
        "Crop an existing video to a rectangular region or centered percentage crop and render a new output file. "
        "The source video is read only; x/y default to a centered crop when omitted."
    ),
    annotations=ToolAnnotations(
        title="Crop video frame",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_crop(
    input_path: ExistingVideoPath,
    width: Annotated[
        int | None,
        Field(description="Crop region width in pixels. Pair with height unless using crop_percent."),
    ] = None,
    height: Annotated[
        int | None,
        Field(description="Crop region height in pixels. Pair with width unless using crop_percent."),
    ] = None,
    x: Annotated[
        int | None,
        Field(description="Optional X offset in pixels. Defaults to a centered crop when omitted."),
    ] = None,
    y: Annotated[
        int | None,
        Field(description="Optional Y offset in pixels. Defaults to a centered crop when omitted."),
    ] = None,
    output_path: OptionalOutputVideoPath = None,
    crop_percent: Annotated[
        float | None,
        Field(description="Centered crop percentage of original dimensions, such as 50 for the center 50%."),
    ] = None,
) -> dict[str, Any]:
    """Crop a video to a rectangular region and render a new output file.

    Provide either ``width`` + ``height`` or ``crop_percent`` (e.g. 50 for a
    center 50% crop).  ``x`` and ``y`` default to center.

    Args:
        input_path: Absolute path to the existing input video. The source is read only.
        width: Width of the crop region in pixels. Pair with height unless using crop_percent.
        height: Height of the crop region in pixels. Pair with width unless using crop_percent.
        x: Optional X offset in pixels. Defaults to a centered crop when omitted.
        y: Optional Y offset in pixels. Defaults to a centered crop when omitted.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
        crop_percent: Alternative to width/height. Percentage of original dimensions to
            keep in a centered crop, such as 50 for the center 50%.
    """
    input_path = _validate_input_path(input_path)
    return _result(
        crop(
            input_path,
            width=width,
            height=height,
            x=x,
            y=y,
            output_path=output_path,
            crop_percent=crop_percent,
        )
    )


@mcp.tool(
    title="Rotate or flip video",
    description=(
        "Rotate and/or flip an existing video and render a new output file. "
        "Supports right-angle rotations plus horizontal and vertical flips; the input video is not modified."
    ),
    annotations=ToolAnnotations(
        title="Rotate or flip video",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_rotate(
    input_path: ExistingVideoPath,
    angle: Annotated[
        int,
        Field(description="Clockwise rotation angle in degrees. Supported values are 0, 90, 180, and 270."),
    ] = 0,
    flip_horizontal: Annotated[
        bool,
        Field(description="Mirror the video horizontally after rotation when true."),
    ] = False,
    flip_vertical: Annotated[
        bool,
        Field(description="Mirror the video vertically after rotation when true."),
    ] = False,
    output_path: OptionalOutputVideoPath = None,
) -> dict[str, Any]:
    """Rotate and/or flip a video and render a new output file.

    Args:
        input_path: Absolute path to the existing input video. The source is read only.
        angle: Rotation angle in degrees. Supported values are 0, 90, 180, and 270.
        flip_horizontal: Mirror the video horizontally after rotation when true.
        flip_vertical: Mirror the video vertically after rotation when true.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
    """
    input_path = _validate_input_path(input_path)
    return _result(
        rotate(
            input_path,
            angle=angle,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            output_path=output_path,
        )
    )


@mcp.tool(
    title="Add video fade",
    description=(
        "Render fade-in and/or fade-out effects onto an existing video without modifying the source file. "
        "Use fade_in for a fade from black at the start and fade_out for a fade to black at the end; "
        "output_path is created or overwritten."
    ),
    annotations=ToolAnnotations(
        title="Add video fade",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@_safe_tool
def video_fade(
    input_path: ExistingVideoPath,
    fade_in: Annotated[
        float,
        Field(description="Non-negative fade-in duration in seconds from black at the start."),
    ] = 0.0,
    fade_out: Annotated[
        float,
        Field(description="Non-negative fade-out duration in seconds to black at the end."),
    ] = 0.0,
    output_path: OptionalOutputVideoPath = None,
    crf: OptionalCrf = None,
    preset: OptionalPreset = None,
) -> dict[str, Any]:
    """Add fade-in and/or fade-out effects to a video and render a new output file.

    Args:
        input_path: Absolute path to the existing input video. The source is read only.
        fade_in: Non-negative fade-in duration in seconds from black at the start.
        fade_out: Non-negative fade-out duration in seconds to black at the end.
        output_path: Destination video path. Auto-generated if omitted; may be overwritten
            if an existing path is supplied.
        crf: Optional CRF override from 0 to 51, where lower means higher quality.
        preset: Optional FFmpeg encoding preset: ultrafast, fast, medium, slow, or veryslow.
    """
    if crf is not None and not (0 <= crf <= 51):
        return _validation_error(f"crf must be 0-51, got {crf}")
    if preset is not None and preset not in VALID_PRESETS:
        return _validation_error(f"Invalid preset: {preset}")
    input_path = _validate_input_path(input_path)
    if fade_in < 0:
        return _validation_error(f"fade_in must be non-negative, got {fade_in}")
    if fade_out < 0:
        return _validation_error(f"fade_out must be non-negative, got {fade_out}")
    return _result(
        fade(
            input_path,
            fade_in=fade_in,
            fade_out=fade_out,
            output_path=output_path,
            crf=crf,
            preset=preset,
        )
    )


@mcp.tool()
@_safe_tool
def video_edit(
    timeline: dict[str, Any] | str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Execute a full timeline-based edit from a JSON specification.

    The timeline JSON describes video clips, audio tracks, text overlays,
    image overlays, transitions, and export settings in a single operation.

    Image overlays are applied in a single filtergraph pass (no multiple re-encodes).

    Args:
        timeline: JSON object with keys: width, height, tracks (video/audio/text/image), export.
            Can also be a JSON string or a path to a .json file.
            Image overlays in tracks: {"type": "image", "images": [{"source":
            "logo.png", "position": "top-right", "width": 200, "opacity": 0.8}]}
        output_path: Where to save the final video. Auto-generated if omitted.
    """
    parsed_timeline = timeline
    if isinstance(timeline, str):
        import json as _json

        timeline_str = timeline.strip()
        # Try parsing as inline JSON first
        try:
            parsed_timeline = _json.loads(timeline_str)
        except _json.JSONDecodeError:
            # Try reading as a file path
            if os.path.isfile(timeline_str):
                try:
                    with open(timeline_str, encoding="utf-8") as f:
                        parsed_timeline = _json.load(f)
                except (_json.JSONDecodeError, OSError) as exc:
                    return _validation_error(f"Invalid timeline JSON file: {timeline_str} — {exc}", code="invalid_json")
            else:
                return _validation_error(
                    f"timeline must be a dict, valid JSON string, or path to a .json file. Got: {timeline_str[:100]}"
                )
    if not isinstance(parsed_timeline, dict):
        return _validation_error(f"timeline must be a dict or JSON object. Got: {type(parsed_timeline).__name__}")
    return _result(edit_timeline(parsed_timeline, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_template_preview(
    template: str,
    input_path: str | None = None,
    duration: float | None = None,
    caption: str | None = None,
    title: str | None = None,
    music_path: str | None = None,
    outro_path: str | None = None,
) -> dict[str, Any]:
    """Preview what a video template would do before rendering.

    Analyzes the template and returns a list of operations, estimated output
    duration, resolution, and file size — without actually processing any video.

    Args:
        template: Template name (tiktok, youtube-shorts, instagram-reel, youtube, instagram-post).
        input_path: Absolute path to the input video (optional; used for duration probing).
        duration: Override the estimated duration in seconds.
        caption: Caption text for TikTok / Instagram Reel / Instagram Post templates.
        title: Title text for YouTube Shorts / YouTube video templates.
        music_path: Absolute path to background music file.
        outro_path: Absolute path to outro video file (YouTube template only).
    """
    template = template.lower().strip()
    if template not in TEMPLATES:
        return _validation_error(f"Unknown template: '{template}'. Available: {sorted(TEMPLATES.keys())}")

    kwargs: dict[str, Any] = {}
    if caption is not None:
        kwargs["caption"] = caption
    if title is not None:
        kwargs["title"] = title
    if music_path is not None:
        kwargs["music_path"] = music_path
    if outro_path is not None:
        kwargs["outro_path"] = outro_path

    probed_duration: float | None = None
    if input_path is not None:
        input_path = _validate_input_path(input_path)
        with contextlib.suppress(Exception):
            probed_duration = _get_video_duration(input_path)

    effective_duration = duration if duration is not None else probed_duration

    result = preview_template(
        template_name=template,
        video_path=input_path or "",
        duration=effective_duration,
        **kwargs,
    )
    return result


@mcp.tool()
@_safe_tool
def video_extract_audio(
    input_path: str,
    output_path: str | None = None,
    format: str = "mp3",
) -> dict[str, Any]:
    """Extract the audio track from a video file.

    Args:
        input_path: Absolute path to the input video.
        output_path: Where to save the audio file. Auto-generated if omitted.
        format: Audio format (mp3, aac, wav, ogg, flac).
    """
    if format not in VALID_AUDIO_FORMATS:
        return _validation_error(f"Invalid audio format: {format}. Must be one of {sorted(VALID_AUDIO_FORMATS)}")
    input_path = _validate_input_path(input_path)
    result = extract_audio(input_path, output_path=output_path, format=format)
    if not os.path.isfile(result):
        return _error_result(
            MCPVideoError(
                f"Audio extraction completed but output file not found: {result}",
                error_type="processing_error",
                code="missing_output",
            )
        )
    size_mb = os.path.getsize(result) / (1024 * 1024)
    return {
        "success": True,
        "output_path": result,
        "size_mb": round(size_mb, 2),
        "format": format,
        "operation": "extract_audio",
    }
