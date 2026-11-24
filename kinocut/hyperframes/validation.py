"""Shared project and option validation for Hyperframes operations."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

from ..errors import HyperframesProjectError, MCPVideoError
from ..ffmpeg_helpers import _validate_input_path
from ..limits import MAX_CRF, MAX_RESOLUTION, MIN_CRF
from ..validation import VALID_HYPERFRAMES_FORMATS, VALID_HYPERFRAMES_QUALITIES, VALID_HYPERFRAMES_RESOLUTIONS
from ..validation_errors import rejected_value


def validate_render_options(
    *,
    quality: str | None,
    format: str | None,
    resolution: str | None,
    width: int | None,
    height: int | None,
    crf: int | None,
    max_concurrent_renders: int | None,
    browser_gpu: bool,
    no_browser_gpu: bool,
    hdr: bool,
    sdr: bool,
) -> str | None:
    if quality is not None and (not isinstance(quality, str) or quality not in VALID_HYPERFRAMES_QUALITIES):
        raise MCPVideoError(
            f"Invalid quality: must be one of {sorted(VALID_HYPERFRAMES_QUALITIES)}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if format is not None and (not isinstance(format, str) or format not in VALID_HYPERFRAMES_FORMATS):
        raise MCPVideoError(
            f"Invalid format: must be one of {sorted(VALID_HYPERFRAMES_FORMATS)}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if resolution is not None and (not isinstance(resolution, str) or resolution not in VALID_HYPERFRAMES_RESOLUTIONS):
        raise MCPVideoError(
            f"Invalid resolution: must be one of {sorted(VALID_HYPERFRAMES_RESOLUTIONS)}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if width is not None and (type(width) is not int or not 1 <= width <= MAX_RESOLUTION):
        raise MCPVideoError(
            f"Invalid width: must be an integer from 1 to {MAX_RESOLUTION}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if height is not None and (type(height) is not int or not 1 <= height <= MAX_RESOLUTION):
        raise MCPVideoError(
            f"Invalid height: must be an integer from 1 to {MAX_RESOLUTION}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if crf is not None and (type(crf) is not int or not MIN_CRF <= crf <= MAX_CRF):
        raise MCPVideoError(
            f"Invalid crf: must be an integer from {MIN_CRF} to {MAX_CRF}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if max_concurrent_renders is not None and (type(max_concurrent_renders) is not int or max_concurrent_renders < 1):
        raise MCPVideoError(
            "max_concurrent_renders must be a positive integer", error_type="validation_error", code="invalid_parameter"
        )
    if browser_gpu and no_browser_gpu:
        raise MCPVideoError(
            "browser_gpu and no_browser_gpu cannot be used together",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if hdr and sdr:
        raise MCPVideoError(
            "hdr and sdr cannot be used together", error_type="validation_error", code="invalid_parameter"
        )
    return _resolve_render_resolution(width, height, resolution)


def validate_inspect_options(samples: int, collapse_static: bool, no_collapse_static: bool) -> None:
    if type(samples) is not int or samples < 1:
        raise MCPVideoError(
            "samples must be an integer of at least 1", error_type="validation_error", code="invalid_parameter"
        )
    if collapse_static and no_collapse_static:
        raise MCPVideoError(
            "collapse_static and no_collapse_static cannot be used together",
            error_type="validation_error",
            code="invalid_parameter",
        )


def validate_tts_options(text_or_file: str | None, speed: float | None, list_voices: bool) -> None:
    if speed is not None and (type(speed) not in (int, float) or not math.isfinite(speed) or speed <= 0):
        raise MCPVideoError(
            "speed must be finite and positive", error_type="validation_error", code="invalid_parameter"
        )
    if not list_voices and not text_or_file:
        raise MCPVideoError(
            "text_or_file is required unless list_voices is true",
            error_type="validation_error",
            code="invalid_parameter",
        )


def _validate_project_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise MCPVideoError(
            "Invalid name: must match ^[a-zA-Z0-9_-]+$",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return name


def _find_entry_point(project: Path) -> Path:
    """Locate the Hyperframes entry point (index.html or any HTML with data-composition-id)."""
    for candidate in ["index.html", "composition.html", "demo.html"]:
        if (project / candidate).is_file():
            return project / candidate
    # Fallback: any HTML file
    for f in project.iterdir():
        if f.suffix == ".html" and f.is_file():
            return f
    raise HyperframesProjectError(str(project), "Could not find entry point (no .html file)")


def _validate_project(project_path: str) -> tuple[Path, Path]:
    """Check that the project directory has the expected structure.

    Returns (project_dir, entry_point) tuple.
    """
    p = Path(project_path).resolve()
    if not p.is_dir():
        raise HyperframesProjectError(str(p), "Directory does not exist")
    entry_point = _find_entry_point(p)
    return p, entry_point


def _validate_variables_file(path: str | os.PathLike[str] | None) -> str | None:
    """Validate optional runtime-data files before forwarding them to Hyperframes."""
    if path is None:
        return None
    return _validate_input_path(str(path))


def _resolution_from_dimensions(width: int | None, height: int | None) -> str | None:
    """Return the Hyperframes resolution preset matching legacy width/height args."""
    match (width, height):
        case (1920, 1080):
            return "landscape"
        case (1080, 1920):
            return "portrait"
        case (3840, 2160):
            return "landscape-4k"
        case (2160, 3840):
            return "portrait-4k"
        case _:
            return None


def _canonical_resolution(value: str | None) -> str | None:
    """Normalize Hyperframes resolution aliases to canonical presets."""
    match value:
        case None:
            return None
        case "1080p":
            return "landscape"
        case "4k" | "uhd":
            return "landscape-4k"
        case _:
            return value


def _resolve_render_resolution(width: int | None, height: int | None, resolution: str | None) -> str | None:
    """Return the effective Hyperframes resolution without silently ignoring dimensions."""
    if (width is None) ^ (height is None):
        raise MCPVideoError(
            "width and height must be provided together",
            error_type="validation_error",
            code="invalid_parameter",
        )

    if width is None and height is None:
        return resolution

    dimension_resolution = _resolution_from_dimensions(width, height)
    if dimension_resolution is None:
        raise MCPVideoError(
            "Hyperframes render only supports width/height pairs that map to --resolution presets: "
            "1920x1080, 1080x1920, 3840x2160, or 2160x3840. Use resolution=... instead of arbitrary dimensions.",
            error_type="validation_error",
            code="invalid_parameter",
        )

    if resolution is not None and _canonical_resolution(resolution) != dimension_resolution:
        raise MCPVideoError(
            f"width/height {width}x{height} conflicts with resolution '{rejected_value(resolution)}'",
            error_type="validation_error",
            code="invalid_parameter",
        )

    return resolution or dimension_resolution


def _invalid_post(message: str) -> None:
    raise MCPVideoError(message, error_type="validation_error", code="invalid_parameter")


def _validate_post_step_values(op_type: str, params: dict[str, Any]) -> None:
    """Reject invalid post-processing parameter values before starting a Hyperframes render."""
    from typing import get_args

    from ..models import ASPECT_RATIOS, QUALITY_PRESETS, ExportFormat
    from ..validation import DURATION_POLICIES

    def _check_positive_int(key: str) -> None:
        val = params.get(key)
        if val is not None and (isinstance(val, bool) or not isinstance(val, int) or val <= 0):
            _invalid_post(f"{key} must be a positive integer")

    def _check_nonneg_num(key: str) -> None:
        val = params.get(key)
        if val is not None and (
            isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val < 0
        ):
            _invalid_post(f"{key} must be a finite non-negative number")

    if op_type == "resize":
        ratio = params.get("aspect_ratio")
        if ratio is not None and (not isinstance(ratio, str) or ratio not in ASPECT_RATIOS):
            _invalid_post(f"Unknown aspect ratio: {rejected_value(ratio)}")
        _check_positive_int("width")
        _check_positive_int("height")
        quality = params.get("quality")
        if quality is not None and (not isinstance(quality, str) or quality not in QUALITY_PRESETS):
            _invalid_post("Unknown resize quality preset")
    elif op_type == "convert":
        fmt = params.get("format")
        if fmt is not None and (not isinstance(fmt, str) or fmt not in get_args(ExportFormat)):
            _invalid_post("Unknown convert format")
        quality = params.get("quality")
        if quality is not None and (not isinstance(quality, str) or quality not in QUALITY_PRESETS):
            _invalid_post("Unknown convert quality preset")
    elif op_type == "fade":
        _check_nonneg_num("fade_in")
        _check_nonneg_num("fade_out")
    elif op_type == "add_audio":
        audio_path = params.get("audio_path")
        if audio_path is not None:
            _validate_input_path(str(audio_path))
        policy = params.get("duration_policy")
        if policy is not None and (not isinstance(policy, str) or policy not in DURATION_POLICIES):
            _invalid_post("Invalid duration_policy")
        for key in ("volume", "fade_in", "fade_out", "start_time"):
            _check_nonneg_num(key)
    elif op_type == "watermark":
        wm = params.get("image_path")
        if not isinstance(wm, str) or not wm:
            _invalid_post("watermark image_path is required")
        _validate_input_path(wm)
        opacity = params.get("opacity")
        if opacity is not None and (
            isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not (0.0 <= float(opacity) <= 1.0)
        ):
            _invalid_post("opacity must be between 0 and 1")
