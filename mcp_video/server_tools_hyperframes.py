"""Hyperframes MCP tool registrations."""

from __future__ import annotations

from typing import Any
import re

from .limits import MAX_CRF, MAX_PORT, MAX_RESOLUTION, MIN_CRF, MIN_PORT
from .server_app import _result, _safe_tool, _validation_error, mcp
from .validation import (
    VALID_HYPERFRAMES_FORMATS,
    VALID_HYPERFRAMES_QUALITIES,
    VALID_HYPERFRAMES_RESOLUTIONS,
    VALID_HYPERFRAMES_TEMPLATES,
)
from .ffmpeg_helpers import _validate_project_path


@mcp.tool()
@_safe_tool
def hyperframes_render(
    project_path: str,
    output_path: str | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
    composition: str | None = None,
    quality: str | None = None,
    format: str | None = None,
    resolution: str | None = None,
    workers: str | int | None = None,
    crf: int | None = None,
    video_bitrate: str | None = None,
    variables: Any | None = None,
    variables_file: str | None = None,
    docker: bool = False,
    hdr: bool = False,
    sdr: bool = False,
    gpu: bool = False,
    browser_gpu: bool = False,
    no_browser_gpu: bool = False,
    quiet: bool = False,
    strict: bool = False,
    strict_all: bool = False,
    max_concurrent_renders: int | None = None,
    strict_variables: bool = False,
) -> dict[str, Any]:
    """Render a Hyperframes composition to video.

    Args:
        project_path: Absolute path to the Hyperframes project directory.
        output_path: Where to save the video. Auto-generated if omitted.
        fps: Frame rate (24, 30, 60).
        width: Output width in pixels.
        height: Output height in pixels.
        quality: Render quality (draft, standard, high). Default standard.
        format: Output format (mp4, webm, mov, png-sequence). Default mp4.
        resolution: Hyperframes resolution preset (landscape, portrait, landscape-4k, portrait-4k, 1080p, 4k, uhd).
        composition: Specific composition file to render instead of index.html.
        workers: Parallel render workers (number or 'auto'). Default auto.
        crf: Override encoder CRF (lower = better quality).
        variables: Inline JSON object/string with runtime data for the composition.
        variables_file: Path to a JSON file with runtime data for the composition.
    """
    if quality is not None and quality not in VALID_HYPERFRAMES_QUALITIES:
        return _validation_error(
            f"Invalid quality: must be one of {sorted(VALID_HYPERFRAMES_QUALITIES)}, got '{quality}'"
        )
    if format is not None and format not in VALID_HYPERFRAMES_FORMATS:
        return _validation_error(f"Invalid format: must be one of {sorted(VALID_HYPERFRAMES_FORMATS)}, got '{format}'")
    if resolution is not None and resolution not in VALID_HYPERFRAMES_RESOLUTIONS:
        return _validation_error(
            f"Invalid resolution: must be one of {sorted(VALID_HYPERFRAMES_RESOLUTIONS)}, got '{resolution}'"
        )
    if width is not None and (width < 1 or width > MAX_RESOLUTION):
        return _validation_error(f"Invalid width: must be 1-{MAX_RESOLUTION}, got {width}")
    if height is not None and (height < 1 or height > MAX_RESOLUTION):
        return _validation_error(f"Invalid height: must be 1-{MAX_RESOLUTION}, got {height}")
    if crf is not None and (crf < MIN_CRF or crf > MAX_CRF):
        return _validation_error(f"Invalid crf: must be {MIN_CRF}-{MAX_CRF}, got {crf}")
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import render

    return _result(
        render(
            project_path,
            output_path=output_path,
            fps=fps,
            width=width,
            height=height,
            composition=composition,
            quality=quality,
            format=format,
            resolution=resolution,
            workers=workers,
            crf=crf,
            video_bitrate=video_bitrate,
            variables=variables,
            variables_file=variables_file,
            docker=docker,
            hdr=hdr,
            sdr=sdr,
            gpu=gpu,
            browser_gpu=browser_gpu,
            no_browser_gpu=no_browser_gpu,
            quiet=quiet,
            strict=strict,
            strict_all=strict_all,
            max_concurrent_renders=max_concurrent_renders,
            strict_variables=strict_variables,
        )
    )


@mcp.tool()
@_safe_tool
def hyperframes_compositions(
    project_path: str,
) -> dict[str, Any]:
    """List compositions in a Hyperframes project.

    Args:
        project_path: Absolute path to the Hyperframes project directory.
    """
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import compositions

    return _result(compositions(project_path))


@mcp.tool()
@_safe_tool
def hyperframes_preview(
    project_path: str,
    port: int = 3002,
) -> dict[str, Any]:
    """Launch Hyperframes preview studio for live preview.

    Args:
        project_path: Absolute path to the Hyperframes project directory.
        port: Port for the preview server (default 3002).
    """
    if port < MIN_PORT or port > MAX_PORT:
        return _validation_error(f"Invalid port: must be {MIN_PORT}-{MAX_PORT}, got {port}")
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import preview

    return _result(preview(project_path, port=port))


@mcp.tool()
@_safe_tool
def hyperframes_still(
    project_path: str,
    output_path: str | None = None,
    frame: int = 0,
    variables: Any | None = None,
    variables_file: str | None = None,
) -> dict[str, Any]:
    """Render a single frame as image from a Hyperframes composition.

    Args:
        project_path: Absolute path to the Hyperframes project directory.
        output_path: Where to save the image. Auto-generated if omitted.
        frame: Frame number to render (default 0).
        variables: Inline JSON object/string with runtime data for the composition.
        variables_file: Path to a JSON file with runtime data for the composition.
    """
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import still

    return _result(
        still(project_path, output_path=output_path, frame=frame, variables=variables, variables_file=variables_file)
    )


@mcp.tool()
@_safe_tool
def hyperframes_snapshot(
    project_path: str,
    frames: int = 5,
    at: list[float] | None = None,
    timeout_ms: int | None = None,
    variables: Any | None = None,
    variables_file: str | None = None,
) -> dict[str, Any]:
    """Capture key frames as PNG screenshots for visual verification."""
    if frames < 1:
        return _validation_error(f"frames must be at least 1, got {frames}")
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import snapshot

    return _result(
        snapshot(
            project_path,
            frames=frames,
            at=at,
            timeout_ms=timeout_ms,
            variables=variables,
            variables_file=variables_file,
        )
    )


@mcp.tool()
@_safe_tool
def hyperframes_inspect(
    project_path: str,
    samples: int = 9,
    at: list[float] | None = None,
    tolerance: int = 2,
    timeout_ms: int | None = None,
    max_issues: int = 80,
    strict: bool = False,
) -> dict[str, Any]:
    """Inspect rendered composition layout for overflow and visual issues."""
    if samples < 1:
        return _validation_error(f"samples must be at least 1, got {samples}")
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import inspect

    return _result(
        inspect(
            project_path,
            samples=samples,
            at=at,
            tolerance=tolerance,
            timeout_ms=timeout_ms,
            max_issues=max_issues,
            strict=strict,
        )
    )


@mcp.tool()
@_safe_tool
def hyperframes_info(project_path: str) -> dict[str, Any]:
    """Print Hyperframes project metadata."""
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import info

    return _result(info(project_path))


@mcp.tool()
@_safe_tool
def hyperframes_catalog(item_type: str | None = None, tag: str | None = None) -> dict[str, Any]:
    """Browse Hyperframes catalog blocks/components."""
    if item_type is not None and item_type not in {"block", "component"}:
        return _validation_error("item_type must be 'block' or 'component'")
    from .hyperframes_engine import catalog

    return _result(catalog(item_type=item_type, tag=tag))


@mcp.tool()
@_safe_tool
def hyperframes_capture(
    url: str,
    output: str | None = None,
    skip_assets: bool = False,
    max_screenshots: int | None = None,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Capture a website as editable Hyperframes components."""
    if not url.startswith(("http://", "https://")):
        return _validation_error("url must start with http:// or https://")
    from .hyperframes_engine import capture

    return _result(
        capture(
            url,
            output=output,
            skip_assets=skip_assets,
            max_screenshots=max_screenshots,
            timeout_ms=timeout_ms,
        )
    )


@mcp.tool()
@_safe_tool
def hyperframes_tts(
    text_or_file: str | None = None,
    output_path: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
    language: str | None = None,
    list_voices: bool = False,
) -> dict[str, Any]:
    """Generate speech audio or list available Hyperframes local TTS voices."""
    if speed is not None and speed <= 0:
        return _validation_error(f"speed must be positive, got {speed}")
    if not list_voices and not text_or_file:
        return _validation_error("text_or_file is required unless list_voices is true")
    from .hyperframes_engine import tts

    return _result(
        tts(
            text_or_file,
            output_path=output_path,
            voice=voice,
            speed=speed,
            language=language,
            list_voices=list_voices,
        )
    )


@mcp.tool()
@_safe_tool
def hyperframes_transcribe(
    input_path: str,
    project_path: str | None = None,
    model: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Transcribe audio/video to word-level timestamps or import transcripts."""
    from .hyperframes_engine import transcribe

    return _result(transcribe(input_path, project_path=project_path, model=model, language=language))


@mcp.tool()
@_safe_tool
def hyperframes_remove_background(
    input_path: str,
    output_path: str | None = None,
    background_output_path: str | None = None,
    device: str = "auto",
    quality: str = "balanced",
    info: bool = False,
) -> dict[str, Any]:
    """Remove a video/image background using Hyperframes local AI."""
    if device not in {"auto", "cpu", "coreml", "cuda"}:
        return _validation_error("device must be one of auto, cpu, coreml, cuda")
    if quality not in {"fast", "balanced", "best"}:
        return _validation_error("quality must be one of fast, balanced, best")
    from .hyperframes_engine import remove_background

    return _result(
        remove_background(
            input_path,
            output_path=output_path,
            background_output_path=background_output_path,
            device=device,
            quality=quality,
            info=info,
        )
    )


@mcp.tool()
@_safe_tool
def hyperframes_doctor() -> dict[str, Any]:
    """Run Hyperframes environment diagnostics."""
    from .hyperframes_engine import doctor

    return _result(doctor())


@mcp.tool()
@_safe_tool
def hyperframes_benchmark(
    project_path: str,
    output_path: str | None = None,
    runs: int | None = None,
    json_output: bool = True,
) -> dict[str, Any]:
    """Benchmark Hyperframes render speed and file size."""
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import benchmark

    return _result(benchmark(project_path, output_path=output_path, runs=runs, json_output=json_output))


@mcp.tool()
@_safe_tool
def hyperframes_init(
    name: str,
    output_dir: str | None = None,
    template: str = "blank",
    video: str | None = None,
    audio: str | None = None,
    skip_transcribe: bool = False,
    model: str | None = None,
    language: str | None = None,
    tailwind: bool = False,
    resolution: str | None = None,
) -> dict[str, Any]:
    """Scaffold a new Hyperframes project.

    Args:
        name: Project name.
        output_dir: Directory to create the project in. Defaults to current directory.
        template: Project template (blank, warm-grain, swiss-grid). Default blank.
        video: Optional source video for project bootstrap.
        audio: Optional source audio for project bootstrap.
        skip_transcribe: Skip Whisper transcription during media bootstrap.
        model: Whisper model for transcription.
        language: Language code for transcription.
        tailwind: Add Tailwind CSS browser-runtime support.
        resolution: Hyperframes canvas resolution preset.
    """
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return _validation_error("Invalid name: must match ^[a-zA-Z0-9_-]+$")
    if template not in VALID_HYPERFRAMES_TEMPLATES:
        return _validation_error(
            f"Invalid template: must be one of {sorted(VALID_HYPERFRAMES_TEMPLATES)}, got '{template}'"
        )
    if resolution is not None and resolution not in VALID_HYPERFRAMES_RESOLUTIONS:
        return _validation_error(
            f"Invalid resolution: must be one of {sorted(VALID_HYPERFRAMES_RESOLUTIONS)}, got '{resolution}'"
        )
    from .hyperframes_engine import create_project

    return _result(
        create_project(
            name,
            output_dir=output_dir,
            template=template,
            video=video,
            audio=audio,
            skip_transcribe=skip_transcribe,
            model=model,
            language=language,
            tailwind=tailwind,
            resolution=resolution,
        )
    )


@mcp.tool()
@_safe_tool
def hyperframes_add_block(
    project_path: str,
    block_name: str,
    no_clipboard: bool = False,
) -> dict[str, Any]:
    """Install a block from the Hyperframes catalog.

    Args:
        project_path: Absolute path to the Hyperframes project directory.
        block_name: Registry item name (e.g. claude-code-window, shader-wipe).
    """
    if not re.match(r"^[a-zA-Z0-9_-]+$", block_name):
        return _validation_error("Invalid block_name: must match ^[a-zA-Z0-9_-]+$")
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import add_block

    return _result(add_block(project_path, block_name, no_clipboard=no_clipboard))


@mcp.tool()
@_safe_tool
def hyperframes_validate(
    project_path: str,
) -> dict[str, Any]:
    """Validate a Hyperframes project for rendering readiness.

    Args:
        project_path: Absolute path to the Hyperframes project directory.
    """
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import validate

    return _result(validate(project_path))


@mcp.tool()
@_safe_tool
def hyperframes_to_mcpvideo(
    project_path: str,
    post_process: list[dict[str, Any]],
    output_path: str | None = None,
) -> dict[str, Any]:
    """Render a Hyperframes composition and post-process with mcp-video in one step.

    Args:
        project_path: Absolute path to the Hyperframes project directory.
        post_process: List of post-processing operations, each with 'op' and 'params' keys.
            Example: [{"op": "resize", "params": {"aspect_ratio": "9:16"}}]
        output_path: Where to save the final output. Auto-generated if omitted.
    """
    if not isinstance(post_process, list) or len(post_process) < 1:
        return _validation_error("Invalid post_process: must be a non-empty list")
    project_path = _validate_project_path(project_path)
    from .hyperframes_engine import render_and_post

    return _result(render_and_post(project_path, post_process, output_path=output_path))
