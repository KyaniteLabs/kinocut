"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _run_command, _validate_input_path, _validate_output_path
from ..limits import DEFAULT_FFMPEG_TIMEOUT

logger = logging.getLogger(__name__)

# Style presets define color adjustments. Every style accepted by
# validation.VALID_COLOR_GRADE_STYLES must have an entry here.
STYLE_PRESETS: dict[str, dict[str, float]] = {
    "cinematic": {"contrast": 1.1, "saturation": 0.9, "gamma": 1.0, "red": 1.05, "green": 1.0, "blue": 0.95},
    "vintage": {"contrast": 0.9, "saturation": 0.7, "gamma": 1.1, "red": 1.1, "green": 0.95, "blue": 0.8},
    "warm": {"contrast": 1.0, "saturation": 1.05, "gamma": 1.0, "red": 1.1, "green": 1.0, "blue": 0.9},
    "cool": {"contrast": 1.0, "saturation": 0.95, "gamma": 1.0, "red": 0.9, "green": 1.0, "blue": 1.1},
    "dramatic": {"contrast": 1.3, "saturation": 1.1, "gamma": 0.9, "red": 1.0, "green": 1.0, "blue": 1.0},
    "noir": {"contrast": 1.3, "saturation": 0.2, "gamma": 0.95, "red": 1.0, "green": 1.0, "blue": 1.0},
    "auto": {"contrast": 1.05, "saturation": 1.0, "gamma": 1.0, "red": 1.0, "green": 1.0, "blue": 1.0},
}


def ai_color_grade(
    video: str,
    output: str,
    reference: str | None = None,
    style: str = "auto",
    lut_path: str | None = None,
) -> str:
    """Color grading via a LUT file, a reference video, or a style preset.

    Args:
        video: Input video path
        output: Output video path
        reference: Optional reference video for color matching
        style: Style preset (auto, cinematic, vintage, warm, cool, dramatic, noir)
        lut_path: Optional .cube/.3dl LUT file — applied with FFmpeg lut3d and
            overrides both reference and style

    Returns:
        Path to output video

    Raises:
        FileNotFoundError: If video file doesn't exist
        RuntimeError: If FFmpeg processing fails
    """
    _validate_input_path(video)

    # Validate input file
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)

    if lut_path is not None:
        suffix = Path(lut_path).suffix.lower()
        if suffix not in {".cube", ".3dl"}:
            raise MCPVideoError(
                f"LUT file must be a .cube or .3dl file, got '{suffix or lut_path}'",
                error_type="validation_error",
                code="invalid_lut",
            )
        lut_path = _validate_input_path(lut_path)
        return _apply_lut(str(video_path), output, lut_path)

    try:
        params = STYLE_PRESETS[style]
    except KeyError:
        raise MCPVideoError(
            f"Unknown color grade style '{style}'. Valid styles: {', '.join(sorted(STYLE_PRESETS))}",
            error_type="validation_error",
            code="invalid_style",
        ) from None

    # If reference provided, analyze and adjust to match
    if reference:
        _validate_input_path(reference)
        params = _match_reference_colors(video, reference)

    # Build FFmpeg filter chain
    # eq filter for contrast/saturation/gamma/brightness
    # colorbalance for RGB channel adjustments (rs=red shift, gs=green shift, bs=blue shift)

    # Convert multipliers to FFmpeg eq parameters
    contrast = params["contrast"]
    saturation = params["saturation"]
    gamma = params["gamma"]

    # Calculate RGB shifts for colorbalance (normalized -1 to 1 range)
    # 1.0 = no shift, >1.0 = increase, <1.0 = decrease
    # Map 0.8-1.2 range to approximately -0.1 to 0.1 shift
    rs = (params["red"] - 1.0) * 0.5
    gs = (params["green"] - 1.0) * 0.5
    bs = (params["blue"] - 1.0) * 0.5

    # Build filter chain
    # eq filter for basic color adjustments (needs eq= prefix)
    eq_params = f"eq=contrast={contrast}:saturation={saturation}:gamma={gamma}"

    # colorbalance for RGB channel adjustments
    colorbalance_params = f"colorbalance=rs={rs}:gs={gs}:bs={bs}"

    # Combine filters
    filter_string = f"{eq_params},{colorbalance_params}"

    # Build FFmpeg command
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        filter_string,
        "-c:a",
        "copy",  # Copy audio without re-encoding
        "-pix_fmt",
        "yuv420p",  # Ensure compatibility
        output,
    ]

    # Execute FFmpeg
    _validate_output_path(output)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)

    return output


def _apply_lut(video: str, output: str, lut_path: str) -> str:
    """Apply a .cube/.3dl LUT with FFmpeg's lut3d filter."""
    from ..ffmpeg_helpers import _escape_ffmpeg_filter_value

    filter_string = f"lut3d={_escape_ffmpeg_filter_value(lut_path)}"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video,
        "-vf",
        filter_string,
        "-c:a",
        "copy",
        "-pix_fmt",
        "yuv420p",
        output,
    ]
    _validate_output_path(output)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)
    return output


def _match_reference_colors(video: str, reference: str) -> dict:
    """Analyze reference and return matching parameters.

    This is a simplified implementation that extracts basic color statistics
    from both videos and returns adjusted parameters.

    Args:
        video: Input video path
        reference: Reference video path

    Returns:
        Dict with color adjustment parameters
    """

    def extract_mean_color(video_path: str) -> dict:
        """Extract mean RGB values from video using signalstats filter."""
        cmd = ["ffmpeg", "-i", video_path, "-vf", "signalstats", "-f", "null", "-"]
        result = _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)

        # Default values if extraction fails
        mean_rgb = {"r": 128, "g": 128, "b": 128}

        # Parse signalstats output
        # Look for mean values in stderr output
        stderr = result.stderr

        # Try to extract mean Y/U/V or R/G/B values
        # This is a simplified extraction - signalstats outputs in YUV by default
        y_match = re.search(r"YAVG ([\d.]+)", stderr)
        u_match = re.search(r"UAVG ([\d.]+)", stderr)
        v_match = re.search(r"VAVG ([\d.]+)", stderr)

        if y_match and u_match and v_match:
            # Convert YUV to approximate RGB (simplified)
            y = float(y_match.group(1))
            u = float(u_match.group(1)) - 128
            v = float(v_match.group(1)) - 128

            # Approximate RGB from YUV
            mean_rgb["r"] = max(0, min(255, y + 1.402 * v))
            mean_rgb["g"] = max(0, min(255, y - 0.344 * u - 0.714 * v))
            mean_rgb["b"] = max(0, min(255, y + 1.772 * u))

        return mean_rgb

    try:
        # Extract mean colors from both videos
        video_colors = extract_mean_color(video)
        ref_colors = extract_mean_color(reference)

        # Calculate adjustment ratios
        # Avoid division by zero
        def safe_ratio(ref, src):
            if src < 1:
                src = 1
            return min(2.0, max(0.5, ref / src))

        red_adj = safe_ratio(ref_colors["r"], video_colors["r"])
        green_adj = safe_ratio(ref_colors["g"], video_colors["g"])
        blue_adj = safe_ratio(ref_colors["b"], video_colors["b"])

        # Calculate contrast adjustment based on overall brightness difference
        video_avg = (video_colors["r"] + video_colors["g"] + video_colors["b"]) / 3
        ref_avg = (ref_colors["r"] + ref_colors["g"] + ref_colors["b"]) / 3
        contrast_adj = safe_ratio(ref_avg, video_avg)

        return {
            "contrast": contrast_adj,
            "saturation": 1.0,
            "gamma": 1.0,
            "red": red_adj,
            "green": green_adj,
            "blue": blue_adj,
        }
    except (ProcessingError, ValueError, OSError):
        # Fall back to neutral params if analysis fails
        return {"contrast": 1.0, "saturation": 1.0, "gamma": 1.0, "red": 1.0, "green": 1.0, "blue": 1.0}


# ---------------------------------------------------------------------------
# Model Download Integrity Verification
# ---------------------------------------------------------------------------
