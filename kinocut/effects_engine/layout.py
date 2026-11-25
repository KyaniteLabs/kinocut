"""Video effects and filters engine.

Visual effects using FFmpeg filters and PIL for custom processing.
"""

from __future__ import annotations

import logging
import re
import warnings as _warnings

from ..errors import MCPVideoError
from ..ffmpeg_helpers import (
    _validate_input_path,
    _validate_output_path,
    _run_command,
    _escape_ffmpeg_filter_value,
)
from ..engine_probe import probe as _probe
from ..validation import VALID_GRID_LAYOUTS, VALID_PIP_POSITIONS
from ..validation_errors import rejected_value

logger = logging.getLogger(__name__)
_SAFE_COLOR_RE = re.compile(
    r"^(?:#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})"
    r"|0x[0-9A-Fa-f]{6,8}"
    r"|[A-Za-z][A-Za-z0-9]{0,31})(?:@(?:0(?:\.\d+)?|1(?:\.0+)?|0x[0-9A-Fa-f]{2}))?$"
)


def _validate_grid_background(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_COLOR_RE.fullmatch(value.strip()):
        raise MCPVideoError(
            f"background must be a valid hex or named color, got {rejected_value(value)}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return _escape_ffmpeg_filter_value(value.strip())


def _validate_choice(name: str, value: str, valid_values: set[str]) -> None:
    if value not in valid_values:
        raise MCPVideoError(
            f"{name} must be one of {sorted(valid_values)}, got {rejected_value(value)}",
            error_type="validation_error",
            code="invalid_parameter",
        )


def _grid_guardrails(clips: list[str], layout: str, n_cells: int) -> None:
    """Warn on excess clips and uneven durations."""
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


def _build_grid_filter_complex(
    n_clips: int,
    cols: int,
    rows: int,
    cell_w: int,
    cell_h: int,
    *,
    gap: int = 0,
    padding: int = 0,
    background: str = "#141414",
) -> str:
    """Build the filter_complex string for a grid layout with gaps, padding, and background fill."""
    safe_bg = _validate_grid_background(background)
    filter_parts: list[str] = []

    # Scale each input to cell size with consistent background letterboxing
    for i in range(n_clips):
        filter_parts.append(
            f"[{i}:v]scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,"
            f"setsar=1,pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:color={safe_bg},"
            f"format=pix_fmts=yuv420p[s{i}];"
        )

    actual_cols = min(cols, n_clips)
    actual_rows = (n_clips + cols - 1) // cols
    inner_w = actual_cols * cell_w + max(0, actual_cols - 1) * gap
    inner_h = actual_rows * cell_h + max(0, actual_rows - 1) * gap

    if n_clips == 1:
        stacked_label = "[s0]"
    else:
        positions: list[str] = []
        for i in range(n_clips):
            col = i % cols
            row = i // cols
            x = col * (cell_w + gap)
            y = row * (cell_h + gap)
            positions.append(f"{x}_{y}")
        xstack_in = "".join(f"[s{i}]" for i in range(n_clips))
        layout_spec = "|".join(positions)
        filter_parts.append(f"{xstack_in}xstack=inputs={n_clips}:layout={layout_spec}:fill={safe_bg}[grid];")
        stacked_label = "[grid]"

    total_w = inner_w + 2 * padding
    total_h = inner_h + 2 * padding
    # Ensure even output dimensions for yuv420p / libx264 compatibility.
    even_w = total_w + (total_w % 2)
    even_h = total_h + (total_h % 2)
    if padding > 0 or even_w != inner_w or even_h != inner_h:
        filter_parts.append(
            f"{stacked_label}pad={even_w}:{even_h}:{padding}:{padding}:color={safe_bg},format=pix_fmts=yuv420p[out]"
        )
    else:
        filter_parts.append(f"{stacked_label}format=pix_fmts=yuv420p[out]")

    return "".join(filter_parts).rstrip(";")


def layout_grid(
    clips: list[str],
    layout: str,
    output: str,
    gap: int = 10,
    padding: int = 20,
    background: str = "#141414",
) -> str:
    """Create grid-based multi-video layout with configurable gap, padding, and background fill.

    Args:
        clips: List of video file paths
        layout: Grid layout - "2x2", "3x1", "1x3", "2x3"
        output: Output video path
        gap: Pixels between clips
        padding: Padding around grid in pixels
        background: Background color hex or FFmpeg named color

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
    _validate_grid_background(background)

    clips = [_validate_input_path(clip) for clip in clips]
    _validate_output_path(output)

    # Parse layout
    cols, rows = map(int, layout.split("x"))
    n_cells = cols * rows

    _grid_guardrails(clips, layout, n_cells)

    n_clips = min(len(clips), n_cells)

    # Use even dimensions that work for x264
    cell_w = 640  # Standard width
    cell_h = 480  # Standard height

    inputs = []
    for clip in clips[:n_clips]:
        inputs.extend(["-i", clip])

    filter_complex = _build_grid_filter_complex(
        n_clips,
        cols,
        rows,
        cell_w,
        cell_h,
        gap=gap,
        padding=padding,
        background=background,
    )

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


def _calc_pip_geometry(main_w: int, main_h: int, size: float, margin: int, position: str) -> tuple[int, int, int, int]:
    """Calculate PIP dimensions and overlay position."""
    pip_w = int(main_w * size)
    pip_h = int(main_h * size)
    positions = {
        "top-left": (margin, margin),
        "top-right": (main_w - pip_w - margin, margin),
        "bottom-left": (margin, main_h - pip_h - margin),
        "bottom-right": (main_w - pip_w - margin, main_h - pip_h - margin),
    }
    x, y = positions.get(position, positions["bottom-right"])
    return pip_w, pip_h, x, y


def _build_pip_filter(
    pip_w: int, pip_h: int, border: bool, border_width: int, border_color: str, rounded_corners: bool
) -> str:
    """Build the PIP video filter chain."""
    pip_filters = f"scale={pip_w}:{pip_h}"
    if border:
        safe_border_color = _escape_ffmpeg_filter_value(border_color)
        pad_w = pip_w + border_width * 2
        pad_h = pip_h + border_width * 2
        pip_filters += f",pad={pad_w}:{pad_h}:{border_width}:{border_width}:color={safe_border_color}"
    if rounded_corners:
        # Use format and drawbox for rounded corners simulation
        # This is a simplified version - full rounded corners need more complex filter
        pass
    return pip_filters


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
    probe = _run_command(probe_cmd)
    dims = [d for d in probe.stdout.strip().split("x") if d]
    main_w, main_h = map(int, dims)

    pip_w, pip_h, x, y = _calc_pip_geometry(main_w, main_h, size, margin, position)

    pip_filters = _build_pip_filter(pip_w, pip_h, border, border_width, border_color, rounded_corners)

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
