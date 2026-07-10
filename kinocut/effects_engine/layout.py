"""Video effects and filters engine.

Visual effects using FFmpeg filters and PIL for custom processing.
"""

from __future__ import annotations

import logging
import warnings as _warnings

from ..errors import MCPVideoError
from ..ffmpeg_helpers import (
    _run_ffmpeg,
    _validate_input_path,
    _validate_output_path,
    _run_command,
    _escape_ffmpeg_filter_value,
)
from ..engine_probe import probe as _probe

logger = logging.getLogger(__name__)

VALID_GRID_LAYOUTS = {"2x2", "3x1", "1x3", "2x3"}
VALID_PIP_POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right"}


def _validate_choice(name: str, value: str, valid_values: set[str]) -> None:
    if value not in valid_values:
        raise MCPVideoError(
            f"{name} must be one of {sorted(valid_values)}, got {value}",
            error_type="validation_error",
            code="invalid_parameter",
        )


def layout_grid(
    clips: list[str],
    layout: str,
    output: str,
    gap: int = 10,
    padding: int = 20,
    background: str = "#141414",
) -> str:
    """Create grid-based multi-video layout using hstack/vstack.

    Args:
        clips: List of video file paths
        layout: Grid layout - "2x2", "3x1", "1x3", "2x3"
        output: Output video path
        gap: Pixels between clips (not used with hstack/vstack)
        padding: Padding around grid (not used with hstack/vstack)
        background: Background color (not used with hstack/vstack)

    Returns:
        Path to output video
    """
    if len(clips) == 0:
        raise MCPVideoError("At least one clip required", error_type="validation_error", code="invalid_parameter")
    _validate_choice("layout", layout, VALID_GRID_LAYOUTS)

    if gap < 0 or padding < 0:
        raise MCPVideoError(
            "gap and padding must be non-negative", error_type="validation_error", code="invalid_parameter"
        )

    clips = [_validate_input_path(clip) for clip in clips]
    _validate_output_path(output)

    # Parse layout
    cols, rows = map(int, layout.split("x"))
    n_cells = cols * rows

    # --- Guardrails: clip count and duration ---
    if len(clips) > n_cells:
        _warnings.warn(
            f"[GRID GUARDRAIL] {len(clips)} clips provided but {layout} only has "
            f"{n_cells} cells. Only the first {n_cells} clips will be used.",
            stacklevel=2,
        )
    try:
        durations = [_probe(c).duration for c in clips[:n_cells]]
        min_dur = min(durations)
        max_dur = max(durations)
        if max_dur - min_dur > 1.0:
            _warnings.warn(
                f"[GRID GUARDRAIL] Clip durations vary from {min_dur:.1f}s to "
                f"{max_dur:.1f}s. Output will be truncated to shortest clip.",
                stacklevel=2,
            )
    except Exception as e:
        logger.warning("Could not validate grid durations: %s", e)
    # --- End guardrails ---

    n_clips = min(len(clips), n_cells)

    # Use even dimensions that work for x264
    cell_w = 640  # Standard width
    cell_h = 480  # Standard height

    inputs = []
    for clip in clips[:n_clips]:
        inputs.extend(["-i", clip])

    # Build filter complex
    filter_parts = []

    # Scale each input to cell size
    for i in range(n_clips):
        filter_parts.append(
            f"[{i}:v]scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,"
            f"setsar=1,pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:black[s{i}];"
        )

    # Stack horizontally within each row, then vertically
    # First, stack each row
    row_outputs = []
    for row in range(rows):
        row_inputs = []
        for col in range(cols):
            idx = row * cols + col
            if idx < n_clips:
                row_inputs.append(f"[s{idx}]")

        if len(row_inputs) == 1:
            # Single column, just rename
            filter_parts.append(f"{row_inputs[0]}format=pix_fmts=yuv420p[row{row}];")
        else:
            # Stack horizontally
            hstack_in = "".join(row_inputs)
            filter_parts.append(f"{hstack_in}hstack=inputs={len(row_inputs)}[row{row}];")
        row_outputs.append(f"[row{row}]")

    # Then stack rows vertically
    if len(row_outputs) == 1:
        filter_parts.append(f"{row_outputs[0]}format=pix_fmts=yuv420p[out];")
    else:
        vstack_in = "".join(row_outputs)
        filter_parts.append(f"{vstack_in}vstack=inputs={len(row_outputs)}[out];")

    filter_complex = "".join(filter_parts).rstrip(";")

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        "-shortest",
        output,
    ]

    _run_command(cmd)

    return output


def layout_pip(
    main: str,
    pip: str,
    output: str,
    position: str = "bottom-right",
    size: float = 0.25,
    margin: int = 20,
    rounded_corners: bool = True,
    border: bool = True,
    border_color: str = "#CCFF00",
    border_width: int = 2,
) -> str:
    """Picture-in-picture overlay.

    Args:
        main: Main video path
        pip: Picture-in-picture video path
        output: Output video path
        position: "top-left", "top-right", "bottom-left", "bottom-right"
        size: PIP size as fraction of main (0-1)
        margin: Margin from edges
        rounded_corners: Apply rounded corners to PIP
        border: Add border around PIP
        border_color: Border color (hex)
        border_width: Border width in pixels

    Returns:
        Path to output video
    """
    _validate_choice("position", position, VALID_PIP_POSITIONS)
    main = _validate_input_path(main)
    pip = _validate_input_path(pip)
    _validate_output_path(output)

    # Get main video dimensions
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=s=x:p=0",
        main,
    ]
    probe = _run_ffmpeg(probe_cmd)
    dims = [d for d in probe.stdout.strip().split("x") if d]
    main_w, main_h = map(int, dims)

    # Calculate PIP dimensions
    pip_w = int(main_w * size)
    pip_h = int(main_h * size)

    # Calculate position
    positions = {
        "top-left": (margin, margin),
        "top-right": (main_w - pip_w - margin, margin),
        "bottom-left": (margin, main_h - pip_h - margin),
        "bottom-right": (main_w - pip_w - margin, main_h - pip_h - margin),
    }
    x, y = positions.get(position, positions["bottom-right"])

    # Build PIP filter
    pip_filters = f"scale={pip_w}:{pip_h}"

    if border:
        # Add border using pad
        safe_border_color = _escape_ffmpeg_filter_value(border_color)
        pad_w = pip_w + border_width * 2
        pad_h = pip_h + border_width * 2
        pip_filters += f",pad={pad_w}:{pad_h}:{border_width}:{border_width}:color={safe_border_color}"

    if rounded_corners:
        # Use format and drawbox for rounded corners simulation
        # This is a simplified version - full rounded corners need more complex filter
        pass

    filter_complex = f"[1:v]{pip_filters}[pip];[0:v][pip]overlay={x}:{y}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        main,
        "-i",
        pip,
        "-filter_complex",
        filter_complex,
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        output,
    ]

    _run_command(cmd)

    return output


# ---------------------------------------------------------------------------
# Text & Typography
# ---------------------------------------------------------------------------
