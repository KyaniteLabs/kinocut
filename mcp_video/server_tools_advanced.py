"""Advanced MCP video tool registrations."""

from __future__ import annotations

import os
from typing import Any

from .engine import (
    _validate_chroma_color,
    apply_filter,
    apply_mask,
    audio_waveform,
    chroma_key,
    compare_quality,
    create_from_images,
    detect_scenes,
    export_frames,
    generate_subtitles,
    hls_segment,
    luma_key,
    normalize_audio,
    overlay_video,
    read_metadata,
    reverse,
    shape_mask,
    split_screen,
    stabilize,
    write_metadata,
)
from .engine import video_batch as _video_batch
from .engine_batch import VALID_BATCH_OPERATIONS
from .engine_composite_layers import composite_layers
from .errors import MCPVideoError
from .models import _validate_position
from .limits import MAX_BATCH_SIZE, MAX_EXPORT_FRAMES_FPS
from .server_app import _result, _safe_tool, _validation_error, mcp
from .validation import VALID_LAYOUTS, VALID_PRESETS

from .ffmpeg_helpers import _validate_input_path

VALID_HLS_QUALITIES = {"low", "medium", "high", "ultra"}
VALID_QUALITY_METRICS = {"psnr", "ssim"}

_CLEANUP_MANAGED_SUFFIXES = (
    "_trimmed",
    "_resized",
    "_converted",
    "_merged",
    "_filtered",
    "_watermark",
    "_watermarked",
    "_overlay",
    "_preview",
    "_thumbnail",
    "_storyboard",
    "_normalized",
    "_stabilized",
    "_reversed",
    "_cropped",
    "_rotated",
    "_speed",
    "_fade",
    "_export",
)


@mcp.tool()
@_safe_tool
def video_filter(
    input_path: str,
    filter_type: str,
    params: dict[str, Any] | None = None,
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
) -> dict[str, Any]:
    """Apply a visual filter to a video.

    Common presets:
        - blur: params={"radius": 5, "strength": 1}
        - color_preset: params={"preset": "warm"} (warm, cool, vintage, cinematic, noir)

    Args:
        input_path: Absolute path to the input video.
        filter_type: Filter type (blur, sharpen, brightness, contrast, saturation,"
                     " grayscale, sepia, invert, vignette, color_preset, denoise,"
                     " deinterlace, ken_burns, reverb, compressor, pitch_shift,"
                     " noise_reduction).
        params: Optional filter parameters (e.g. radius for blur, preset for color_preset).
        output_path: Where to save the output. Auto-generated if omitted.
        crf: Override CRF value (0-51, lower = better quality). Default 23.
        preset: Override FFmpeg encoding preset (ultrafast, fast, medium, slow, veryslow).
    """
    if crf is not None and not (0 <= crf <= 51):
        return _validation_error(f"crf must be 0-51, got {crf}")
    if preset is not None and preset not in VALID_PRESETS:
        return _validation_error(f"Invalid preset: {preset}")
    input_path = _validate_input_path(input_path)
    return _result(
        apply_filter(
            input_path,
            filter_type=filter_type,
            params=params,
            output_path=output_path,
            crf=crf,
            preset=preset,
        )
    )


@mcp.tool()
@_safe_tool
def video_luma_key(
    input_path: str,
    threshold: float = 0.5,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Mask out dark regions based on luminance (brightness).

    Args:
        input_path: Absolute path to the input video.
        threshold: Luminance threshold (0.0-1.0). Pixels darker than this
            become transparent.
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    return _result(luma_key(input_path, threshold=threshold, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_shape_mask(
    input_path: str,
    shape: str = "circle",
    output_path: str | None = None,
    feather: int = 0,
) -> dict[str, Any]:
    """Apply a geometric shape mask to a video.

    Args:
        input_path: Absolute path to the input video.
        shape: Shape to use — "circle", "rounded_rect", or "oval".
        output_path: Where to save the output. Auto-generated if omitted.
        feather: Feather radius in pixels (0 = sharp edges).
    """
    input_path = _validate_input_path(input_path)
    return _result(shape_mask(input_path, shape=shape, output_path=output_path, feather=feather))


@mcp.tool()
@_safe_tool
def video_hls_segment(
    input_path: str,
    output_dir: str | None = None,
    segment_duration: int = 4,
    playlist_name: str = "playlist.m3u8",
    qualities: list[str] | None = None,
) -> dict[str, Any]:
    """Segment a video into HLS (HTTP Live Streaming) format.

    Args:
        input_path: Absolute path to the input video.
        output_dir: Directory to save segments. Auto-generated if omitted.
        segment_duration: Target segment duration in seconds (default 4).
        playlist_name: Name of the master playlist file.
        qualities: List of quality levels (e.g. ["low", "medium", "high"]).
    """
    if segment_duration <= 0:
        return _validation_error(f"segment_duration must be positive, got {segment_duration}")
    invalid_qualities = [quality for quality in qualities or [] if quality not in VALID_HLS_QUALITIES]
    if invalid_qualities:
        return _validation_error(
            f"qualities must be one of {sorted(VALID_HLS_QUALITIES)}, got invalid values: {invalid_qualities}"
        )
    input_path = _validate_input_path(input_path)
    return _result(
        hls_segment(
            input_path,
            output_dir=output_dir,
            segment_duration=segment_duration,
            playlist_name=playlist_name,
            qualities=qualities,
        )
    )


@mcp.tool()
@_safe_tool
def video_reverse(
    input_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Reverse video and audio playback so it plays backwards.

    Args:
        input_path: Absolute path to the input video.
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    return _result(reverse(input_path, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_chroma_key(
    input_path: str,
    color: str = "0x00FF00",
    similarity: float = 0.01,
    blend: float = 0.0,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Remove a solid color background (green screen / chroma key).

    Args:
        input_path: Absolute path to the input video.
        color: Color to make transparent in hex format (default green: 0x00FF00).
        similarity: How similar colors need to be to be keyed out (0.0-1.0, default 0.01).
        blend: How much to blend the keyed color (default 0.0).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    _validate_chroma_color(color)
    if not 0 <= similarity <= 1:
        return _validation_error(f"similarity must be between 0 and 1, got {similarity}")
    if not 0 <= blend <= 1:
        return _validation_error(f"blend must be between 0 and 1, got {blend}")
    return _result(chroma_key(input_path, color=color, similarity=similarity, blend=blend, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_normalize_audio(
    input_path: str,
    target_lufs: float = -16.0,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Normalize audio loudness to a target LUFS level.

    Common presets: -16 (YouTube), -23 (EBU R128/broadcast), -14 (Apple/Spotify).

    Args:
        input_path: Absolute path to the input video.
        target_lufs: Target integrated loudness in LUFS (default -16 for YouTube).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    if not -70 <= target_lufs <= -5:
        return _validation_error(f"target_lufs must be between -70 and -5, got {target_lufs}")
    return _result(normalize_audio(input_path, target_lufs=target_lufs, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_overlay(
    background_path: str,
    overlay_path: str,
    position: str | dict = "top-right",
    width: int | None = None,
    height: int | None = None,
    opacity: float = 0.8,
    start_time: float | None = None,
    duration: float | None = None,
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
) -> dict[str, Any]:
    """Picture-in-picture: overlay a video on top of another.

    Args:
        background_path: Absolute path to the background video.
        overlay_path: Absolute path to the overlay video.
        position: Position on screen. Named (top-left, etc.), pixel"
                  " {\"x\": 100, \"y\": 50}, or percentage {\"x_pct\": 0.5, \"y_pct\": 0.5}.
        width: Width to scale the overlay to (pixels).
        height: Height to scale the overlay to (pixels).
        opacity: Overlay opacity (0.0 to 1.0).
        start_time: When the overlay appears (seconds).
        duration: How long the overlay is visible (seconds).
        output_path: Where to save the output. Auto-generated if omitted.
        crf: Override CRF value (0-51, lower = better quality). Default 23.
        preset: Override FFmpeg encoding preset (ultrafast, fast, medium, slow, veryslow).
    """
    try:
        _validate_position(position)
    except MCPVideoError as exc:
        return _validation_error(str(exc))
    if width is not None and width <= 0:
        return _validation_error(f"width must be positive, got {width}")
    if height is not None and height <= 0:
        return _validation_error(f"height must be positive, got {height}")
    if crf is not None and not (0 <= crf <= 51):
        return _validation_error(f"crf must be 0-51, got {crf}")
    if preset is not None and preset not in VALID_PRESETS:
        return _validation_error(f"Invalid preset: {preset}")
    background_path = _validate_input_path(background_path)
    overlay_path = _validate_input_path(overlay_path)
    if not 0 <= opacity <= 1:
        return _validation_error(f"opacity must be between 0 and 1, got {opacity}")
    return _result(
        overlay_video(
            background_path,
            overlay_path=overlay_path,
            position=position,
            width=width,
            height=height,
            opacity=opacity,
            start_time=start_time,
            duration=duration,
            output_path=output_path,
            crf=crf,
            preset=preset,
        )
    )


@mcp.tool()
@_safe_tool
def video_split_screen(
    left_path: str,
    right_path: str,
    layout: str = "side-by-side",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Place two videos side by side or top/bottom.

    Args:
        left_path: Absolute path to the first video.
        right_path: Absolute path to the second video.
        layout: Layout type (side-by-side or top-bottom).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    if layout not in VALID_LAYOUTS:
        return _validation_error(f"Invalid layout: must be one of {sorted(VALID_LAYOUTS)}, got '{layout}'")
    left_path = _validate_input_path(left_path)
    right_path = _validate_input_path(right_path)
    return _result(split_screen(left_path, right_path=right_path, layout=layout, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_detect_scenes(
    input_path: str,
    threshold: float = 0.3,
    min_scene_duration: float = 1.0,
) -> dict[str, Any]:
    """Detect scene changes in a video.

    Args:
        input_path: Absolute path to the input video.
        threshold: Scene detection sensitivity (0.0-1.0, lower = more sensitive, default 0.3).
        min_scene_duration: Minimum scene duration in seconds (default 1.0).
    """
    input_path = _validate_input_path(input_path)
    if not 0 <= threshold <= 1:
        return _validation_error(f"threshold must be between 0 and 1, got {threshold}")
    if min_scene_duration <= 0:
        return _validation_error(f"min_scene_duration must be positive, got {min_scene_duration}")
    return _result(detect_scenes(input_path, threshold=threshold, min_scene_duration=min_scene_duration))


@mcp.tool()
@_safe_tool
def video_create_from_images(
    images: list[str],
    output_path: str | None = None,
    fps: float = 30.0,
) -> dict[str, Any]:
    """Create a video from a sequence of images.

    Args:
        images: List of absolute paths to image files (in order).
        output_path: Where to save the output video. Auto-generated if omitted.
        fps: Frames per second for the output video (default 30.0).
    """
    for _p in images:
        _validate_input_path(_p)
    if fps <= 0 or fps > MAX_EXPORT_FRAMES_FPS:
        return _validation_error(f"fps must be between 1 and {MAX_EXPORT_FRAMES_FPS}, got {fps}")
    return _result(create_from_images(images, output_path=output_path, fps=fps))


@mcp.tool()
@_safe_tool
def video_export_frames(
    input_path: str,
    output_dir: str | None = None,
    fps: float = 1.0,
    format: str = "jpg",
) -> dict[str, Any]:
    """Export frames from a video as individual images.

    Args:
        input_path: Absolute path to the input video.
        output_dir: Directory for extracted frames. Auto-generated if omitted.
        fps: Frames per second to extract (1.0 = 1 frame per second, default 1.0).
        format: Output image format (jpg or png, default jpg).
    """
    if fps <= 0:
        return _validation_error(f"fps must be positive, got {fps}")
    if fps > MAX_EXPORT_FRAMES_FPS:
        return _validation_error(f"FPS {fps} exceeds maximum of {MAX_EXPORT_FRAMES_FPS}", code="fps_too_high")
    input_path = _validate_input_path(input_path)
    return _result(export_frames(input_path, output_dir=output_dir, fps=fps, format=format))


@mcp.tool()
@_safe_tool
def video_generate_subtitles(
    entries: list[dict],
    input_path: str,
    burn: bool = False,
) -> dict[str, Any]:
    """Generate SRT subtitles from text entries and optionally burn into video.

    Args:
        entries: List of subtitle entries with keys: start (float), end (float), text (str).
        input_path: Absolute path to the input video.
        burn: If True, burn subtitles into the video (default False).
    """
    try:
        from .engine_subtitle_generate import _validate_entries

        _validate_entries(entries)
    except MCPVideoError as exc:
        return _validation_error(str(exc))
    input_path = _validate_input_path(input_path)
    return _result(generate_subtitles(entries, input_path, burn=burn))


@mcp.tool()
@_safe_tool
def video_compare_quality(
    original_path: str,
    distorted_path: str,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Compare video quality between original and processed versions.

    Args:
        original_path: Absolute path to the original/reference video.
        distorted_path: Absolute path to the processed/distorted video.
        metrics: Metrics to compute (default: ['psnr', 'ssim']).
    """
    invalid_metrics = [metric for metric in metrics or [] if metric.lower() not in VALID_QUALITY_METRICS]
    if invalid_metrics:
        return _validation_error(
            f"metrics must be one of {sorted(VALID_QUALITY_METRICS)}, got invalid values: {invalid_metrics}"
        )
    original_path = _validate_input_path(original_path)
    distorted_path = _validate_input_path(distorted_path)
    return _result(compare_quality(original_path, distorted_path, metrics=metrics))


@mcp.tool()
@_safe_tool
def video_read_metadata(
    input_path: str,
) -> dict[str, Any]:
    """Read metadata tags from a video/audio file.

    Args:
        input_path: Absolute path to the video or audio file.
    """
    input_path = _validate_input_path(input_path)
    return _result(read_metadata(input_path))


@mcp.tool()
@_safe_tool
def video_write_metadata(
    input_path: str,
    metadata: dict[str, str],
    output_path: str | None = None,
) -> dict[str, Any]:
    """Write metadata tags to a video/audio file.

    Args:
        input_path: Absolute path to the input file.
        metadata: Dict of tag key-value pairs (e.g. {'title': 'My Video', 'artist': 'Me'}).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    return _result(write_metadata(input_path, metadata=metadata, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_stabilize(
    input_path: str,
    smoothing: float = 15,
    zooming: float = 0,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Stabilize a shaky video using motion vector analysis.

    Args:
        input_path: Absolute path to the input video.
        smoothing: Smoothing strength (default 15, higher = more stable).
        zooming: Zoom percentage to avoid black borders (default 0).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    if smoothing < 0:
        return _validation_error(f"smoothing must be non-negative, got {smoothing}")
    if zooming < 0:
        return _validation_error(f"zooming must be non-negative, got {zooming}")
    return _result(stabilize(input_path, smoothing=smoothing, zooming=zooming, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_apply_mask(
    input_path: str,
    mask_path: str,
    feather: int = 5,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Apply an image mask to a video with edge feathering.

    Args:
        input_path: Absolute path to the input video.
        mask_path: Absolute path to the mask image (white = visible, black = transparent).
        feather: Feather/blur amount at mask edges in pixels (default 5).
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    mask_path = _validate_input_path(mask_path)
    if feather < 0:
        return _validation_error(f"feather must be non-negative, got {feather}")
    return _result(apply_mask(input_path, mask_path=mask_path, feather=feather, output_path=output_path))


@mcp.tool()
@_safe_tool
def video_audio_waveform(
    input_path: str,
    bins: int = 50,
) -> dict[str, Any]:
    """Extract audio waveform data (peaks and silence regions).

    Args:
        input_path: Absolute path to the input video/audio file.
        bins: Number of time segments to analyze (default 50).
    """
    input_path = _validate_input_path(input_path)
    if bins < 1 or bins > 1000:
        return _validation_error(f"bins must be between 1 and 1000, got {bins}")
    return _result(audio_waveform(input_path, bins=bins))


@mcp.tool()
@_safe_tool
def video_batch(
    inputs: list[str],
    operation: str,
    params: dict[str, Any] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Apply the same operation to multiple video files.

    Args:
        inputs: List of absolute paths to input video files.
        operation: Operation (trim, resize, convert, filter, blur, color_grade,"
                  " watermark, speed, fade, normalize_audio).
        params: Parameters for the operation.
        output_dir: Directory for output files. Auto-generated if omitted.
    """
    if operation not in VALID_BATCH_OPERATIONS:
        return _validation_error(
            f"Unknown operation '{operation}'. Valid operations: {sorted(VALID_BATCH_OPERATIONS)}",
            code="invalid_operation",
        )
    if len(inputs) > MAX_BATCH_SIZE:
        return _validation_error(
            f"Batch size {len(inputs)} exceeds maximum of {MAX_BATCH_SIZE}", code="batch_too_large"
        )
    return _result(_video_batch(inputs, operation, params, output_dir))


@mcp.tool()
@_safe_tool
def video_cleanup(
    files: list[str],
    keep: list[str] | None = None,
) -> dict[str, Any]:
    """Delete intermediate video files after a workflow.

    Useful for multi-step pipelines that leave temporary outputs.
    Files in ``keep`` are preserved even if listed in ``files``.

    Args:
        files: List of absolute paths to delete.
        keep: List of absolute paths to preserve (optional).
    """
    keep_set = set(keep or [])
    results: list[dict[str, Any]] = []
    removed = 0
    failed = 0
    for path in files:
        if path in keep_set:
            results.append({"path": path, "status": "kept"})
            continue
        try:
            p = _validate_input_path(path)
            stem = os.path.splitext(os.path.basename(p))[0]
            if not stem.startswith("mcp_video_") and not stem.endswith(_CLEANUP_MANAGED_SUFFIXES):
                raise MCPVideoError(
                    "Refusing to delete unmanaged file; only mcp-video intermediate outputs may be cleaned up",
                    error_type="validation_error",
                    code="unsafe_cleanup_path",
                )
            os.remove(p)
            results.append({"path": p, "status": "removed"})
            removed += 1
        except MCPVideoError as e:
            results.append({"path": path, "status": "failed", "error": str(e)})
            failed += 1
        except OSError as e:
            results.append({"path": path, "status": "failed", "error": str(e)})
            failed += 1
    return {
        "success": failed == 0,
        "removed": removed,
        "failed": failed,
        "results": results,
    }

@mcp.tool()
@_safe_tool
def video_composite_layers(
    spec_path: str,
    output_path: str | None = None,
    save_layer_plan: str | None = None,
) -> dict[str, Any]:
    """Composite ordered image/video layers from a JSON spec.

    P1 supports normal alpha compositing, opacity, fixed x/y positioning,
    video/image/solid layers, and a deterministic layer-plan receipt.
    Masks, expanded blend modes, transforms, and per-layer effect routing are
    deliberately deferred to later compositor phases.

    Args:
        spec_path: Path to a composite-layers JSON spec.
        output_path: Optional destination media path.
        save_layer_plan: Optional JSON path for the resolved layer-plan receipt.
    """
    return _result(composite_layers(spec_path, output_path=output_path, save_layer_plan=save_layer_plan))
