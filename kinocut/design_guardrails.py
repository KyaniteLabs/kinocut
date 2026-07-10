"""Visual quality guardrails for text overlays and video composition.

Prevents common failure modes that produce unreadable or unprofessional output:
  - Text overlap at the same position
  - Insufficient contrast against background
  - Text outside safe areas
  - Excessive sequential re-encoding
  - Font size too small or too large for the video
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import MCPVideoError

# ---------------------------------------------------------------------------
# Safe area constants (title-safe and action-safe per SMPTE standards)
# ---------------------------------------------------------------------------
TITLE_SAFE_MARGIN_PCT = 0.10  # 10% margin on each side
ACTION_SAFE_MARGIN_PCT = 0.05  # 5% margin on each side
MIN_TEXT_SIZE_PX = 12
MAX_TEXT_SIZE_PX = 300

# ---------------------------------------------------------------------------
# Contrast constants
# ---------------------------------------------------------------------------
MIN_CONTRAST_RATIO = 2.5  # WCAG AA for large text is 3.0; we use 2.5 for video


@dataclass(frozen=True)
class TextOverlaySpec:
    """Specification for a single text overlay element."""

    text: str
    position: str | dict[str, float]
    size: int
    color: str
    shadow: bool = True
    start_time: float | None = None
    duration: float | None = None


@dataclass(frozen=True)
class LayoutWarning:
    """A detected layout issue."""

    code: str
    message: str
    severity: str  # "error" | "warning" | "info"
    overlay_indices: tuple[int, ...] = ()


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Convert hex or CSS named color to RGB tuple."""
    color = color.lower().strip()

    # Named colors mapping (subset of common video-safe colors)
    named: dict[str, str] = {
        "white": "#FFFFFF",
        "black": "#000000",
        "red": "#FF0000",
        "green": "#008000",
        "blue": "#0000FF",
        "yellow": "#FFFF00",
        "cyan": "#00FFFF",
        "magenta": "#FF00FF",
        "orange": "#FFA500",
        "gray": "#808080",
        "grey": "#808080",
    }
    if color in named:
        color = named[color]

    if color.startswith("#"):
        color = color[1:]
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) == 6:
        return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))

    # Fallback: return mid-gray if unparseable
    return (128, 128, 128)


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Calculate relative luminance per WCAG 2.1."""

    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(color1: str, color2: str) -> float:
    """Calculate contrast ratio between two colors."""
    lum1 = _luminance(_hex_to_rgb(color1))
    lum2 = _luminance(_hex_to_rgb(color2))
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Layout analysis
# ---------------------------------------------------------------------------


def _position_y_pct(position: str | dict[str, float]) -> float:
    """Estimate the vertical position as a percentage of screen height (0-1).

    Returns approximate center-point of the text block.
    """
    if isinstance(position, dict):
        if "y_pct" in position:
            return position["y_pct"]
        if "y" in position:
            # Can't know video height here; assume 1080p
            return position["y"] / 1080.0
        return 0.5

    mapping: dict[str, float] = {
        "top-left": 0.05,
        "top-center": 0.05,
        "top-right": 0.05,
        "center-left": 0.50,
        "center": 0.50,
        "center-right": 0.50,
        "bottom-left": 0.95,
        "bottom-center": 0.95,
        "bottom-right": 0.95,
    }
    return mapping.get(position, 0.5)


def _position_x_pct(position: str | dict[str, float]) -> float:
    """Estimate the horizontal position as a percentage of screen width (0-1)."""
    if isinstance(position, dict):
        if "x_pct" in position:
            return position["x_pct"]
        if "x" in position:
            return position["x"] / 1920.0
        return 0.5

    mapping: dict[str, float] = {
        "top-left": 0.05,
        "top-center": 0.50,
        "top-right": 0.95,
        "center-left": 0.05,
        "center": 0.50,
        "center-right": 0.95,
        "bottom-left": 0.05,
        "bottom-center": 0.50,
        "bottom-right": 0.95,
    }
    return mapping.get(position, 0.5)


def _overlaps(y1: float, y2: float, size1: int, size2: int, video_height: int = 1080) -> bool:
    """Check if two text elements overlap vertically.

    Approximates text height as size * 1.2 (line height).
    """
    h1 = (size1 * 1.2) / video_height
    h2 = (size2 * 1.2) / video_height
    # Check if vertical ranges overlap
    return abs(y1 - y2) < (h1 / 2 + h2 / 2 + 0.02)


def _same_horizontal_band(x1: float, x2: float, text1: str, text2: str, size1: int, size2: int) -> bool:
    """Check if two text elements are in the same horizontal band.

    Approximates text width as len(text) * size * 0.6 (avg char width).
    """
    w1 = (len(text1) * size1 * 0.6) / 1920.0
    w2 = (len(text2) * size2 * 0.6) / 1920.0
    return abs(x1 - x2) < (w1 / 2 + w2 / 2 + 0.02)


# ---------------------------------------------------------------------------
# Main validation entrypoint
# ---------------------------------------------------------------------------


def validate_text_layout(
    overlays: list[TextOverlaySpec],
    video_width: int = 1920,
    video_height: int = 1080,
    background_color: str = "#000000",
    existing_overlays: list[TextOverlaySpec] | None = None,
) -> list[LayoutWarning]:
    """Validate a set of text overlays for common visual failure modes.

    Args:
        overlays: List of text overlays to validate.
        video_width: Video width in pixels.
        video_height: Video height in pixels.
        background_color: Background color for contrast checking.
        existing_overlays: Existing overlays already on the video.

    Returns:
        List of warnings. Empty list means the layout is clean.
    """
    warnings: list[LayoutWarning] = []
    all_overlays = list(existing_overlays or []) + list(overlays)

    # 1. Check for overlaps between simultaneous overlays
    for i, o1 in enumerate(all_overlays):
        for j, o2 in enumerate(all_overlays):
            if i >= j:
                continue

            # Only check if they're visible at the same time
            time_overlap = True
            if o1.start_time is not None and o1.duration is not None:
                o1_end = o1.start_time + o1.duration
            else:
                o1_end = float("inf")
            if o2.start_time is not None and o2.duration is not None:
                o2_end = o2.start_time + o2.duration
            else:
                o2_end = float("inf")

            if (
                o1.start_time is not None
                and o2.start_time is not None
                and (o1.start_time >= o2_end or o2.start_time >= o1_end)
            ):
                time_overlap = False

            if not time_overlap:
                continue

            y1 = _position_y_pct(o1.position)
            y2 = _position_y_pct(o2.position)
            x1 = _position_x_pct(o1.position)
            x2 = _position_x_pct(o2.position)

            if _overlaps(y1, y2, o1.size, o2.size, video_height) and _same_horizontal_band(
                x1, x2, o1.text, o2.text, o1.size, o2.size
            ):
                warnings.append(
                    LayoutWarning(
                        code="text_overlap",
                        message=(
                            f"Text '{o1.text[:30]}...' and '{o2.text[:30]}...' "
                            f"overlap at position ({o1.position}, {o2.position}). "
                            f"Use pixel positioning {{'x': N, 'y': N}} or "
                            f"different named positions to separate them."
                        ),
                        severity="error",
                        overlay_indices=(i, j),
                    )
                )

    # 2. Check contrast for each overlay
    for i, overlay in enumerate(overlays):
        try:
            ratio = contrast_ratio(overlay.color, background_color)
            if ratio < MIN_CONTRAST_RATIO:
                warnings.append(
                    LayoutWarning(
                        code="low_contrast",
                        message=(
                            f"Text '{overlay.text[:30]}...' has low contrast "
                            f"({ratio:.1f}:1) against background. "
                            f"Minimum recommended is {MIN_CONTRAST_RATIO}:1. "
                            f"Consider a lighter/darker color or adding shadow."
                        ),
                        severity="warning",
                        overlay_indices=(i,),
                    )
                )
        except Exception:  # noqa: S110
            pass

    # 3. Check text size
    for i, overlay in enumerate(overlays):
        if overlay.size < MIN_TEXT_SIZE_PX:
            warnings.append(
                LayoutWarning(
                    code="text_too_small",
                    message=(f"Text size {overlay.size}px is very small. Minimum recommended is {MIN_TEXT_SIZE_PX}px."),
                    severity="warning",
                    overlay_indices=(i,),
                )
            )
        if overlay.size > MAX_TEXT_SIZE_PX:
            warnings.append(
                LayoutWarning(
                    code="text_too_large",
                    message=(
                        f"Text size {overlay.size}px is very large. "
                        f"Maximum recommended is {MAX_TEXT_SIZE_PX}px. "
                        f"Text may exceed screen bounds."
                    ),
                    severity="warning",
                    overlay_indices=(i,),
                )
            )

    # 4. Check safe areas
    margin_y = TITLE_SAFE_MARGIN_PCT * video_height
    margin_x = TITLE_SAFE_MARGIN_PCT * video_width
    for i, overlay in enumerate(overlays):
        if isinstance(overlay.position, dict):
            if "y" in overlay.position:
                y = overlay.position["y"]
                if y < margin_y or y > video_height - margin_y:
                    warnings.append(
                        LayoutWarning(
                            code="outside_safe_area",
                            message=(
                                f"Text '{overlay.text[:30]}...' may be outside "
                                f"the title-safe area. Keep text within "
                                f"{TITLE_SAFE_MARGIN_PCT * 100:.0f}% margins."
                            ),
                            severity="info",
                            overlay_indices=(i,),
                        )
                    )
            if "x" in overlay.position:
                x = overlay.position["x"]
                if x < margin_x or x > video_width - margin_x:
                    warnings.append(
                        LayoutWarning(
                            code="outside_safe_area",
                            message=(f"Text '{overlay.text[:30]}...' may be outside the title-safe area horizontally."),
                            severity="info",
                            overlay_indices=(i,),
                        )
                    )

    # 5. Check for multiple sequential overlays (quality warning)
    if len(overlays) > 5:
        warnings.append(
            LayoutWarning(
                code="excessive_overlays",
                message=(
                    f"{len(overlays)} sequential text overlays detected. "
                    f"Each overlay re-encodes the video, degrading quality. "
                    f"Consider using a timeline-based approach (video_edit) "
                    f"or rendering text in a single FFmpeg pass."
                ),
                severity="warning",
                overlay_indices=tuple(range(len(overlays))),
            )
        )

    # 6. Check shadow effectiveness
    for i, overlay in enumerate(overlays):
        if not overlay.shadow:
            try:
                ratio = contrast_ratio(overlay.color, background_color)
                if ratio < 4.0:
                    warnings.append(
                        LayoutWarning(
                            code="missing_shadow",
                            message=(
                                f"Text '{overlay.text[:30]}...' has no shadow "
                                f"and moderate contrast ({ratio:.1f}:1). "
                                f"Shadow=True is recommended for readability."
                            ),
                            severity="info",
                            overlay_indices=(i,),
                        )
                    )
            except Exception:  # noqa: S110
                pass

    return warnings


def validate_single_text(
    text: str,
    position: str | dict[str, float],
    size: int,
    color: str,
    shadow: bool = True,
    video_width: int = 1920,
    video_height: int = 1080,
    background_color: str = "#000000",
) -> list[LayoutWarning]:
    """Validate a single text overlay."""
    return validate_text_layout(
        [TextOverlaySpec(text=text, position=position, size=size, color=color, shadow=shadow)],
        video_width=video_width,
        video_height=video_height,
        background_color=background_color,
    )


# ---------------------------------------------------------------------------
# Layout helper: auto-calculate Y offsets for multi-line text
# ---------------------------------------------------------------------------


def calculate_stacked_positions(
    texts: list[tuple[str, int]],
    base_position: str = "center",
    video_height: int = 1080,
    line_spacing: float = 1.3,
) -> list[dict[str, float]]:
    """Calculate pixel positions for vertically stacked text elements.

    Args:
        texts: List of (text, font_size) tuples.
        base_position: Named position to center around.
        video_height: Video height in pixels.
        line_spacing: Multiplier for line height.

    Returns:
        List of {'x': float, 'y': float} positions.
    """
    # Calculate total block height
    total_height = sum(int(size * line_spacing) for _, size in texts)

    # Determine base Y
    base_y_mapping: dict[str, float] = {
        "top-left": 0.05,
        "top-center": 0.05,
        "top-right": 0.05,
        "center-left": 0.50,
        "center": 0.50,
        "center-right": 0.50,
        "bottom-left": 0.95,
        "bottom-center": 0.95,
        "bottom-right": 0.95,
    }
    base_y_pct = base_y_mapping.get(base_position, 0.5)
    base_y = base_y_pct * video_height

    # Determine X center
    base_x = 0.5 * 1920  # Default 1920 width

    if base_position in ("top-left", "center-left", "bottom-left"):
        base_x = 0.05 * 1920
    elif base_position in ("top-right", "center-right", "bottom-right"):
        base_x = 0.95 * 1920

    # For "center" positions, stack around the center point
    if base_position in ("center-left", "center", "center-right"):
        start_y = base_y - total_height / 2
    elif base_position in ("bottom-left", "bottom-center", "bottom-right"):
        start_y = base_y - total_height
    else:  # top positions
        start_y = base_y

    positions: list[dict[str, float]] = []
    current_y = start_y
    for _, size in texts:
        positions.append({"x": base_x, "y": current_y + (size * line_spacing) / 2})
        current_y += int(size * line_spacing)

    return positions


# ---------------------------------------------------------------------------
# Preview helper: extract a verification frame
# ---------------------------------------------------------------------------


def extract_verification_frame(
    video_path: str,
    timestamp: float = 0.0,
    output_path: str | None = None,
) -> str:
    """Extract a single frame from a video for visual verification.

    Args:
        video_path: Path to the video.
        timestamp: Time in seconds to extract.
        output_path: Where to save the frame. Auto-generated if omitted.

    Returns:
        Path to the extracted frame.
    """
    import os
    import subprocess

    from .ffmpeg_helpers import _validate_input_path, DEFAULT_FFMPEG_TIMEOUT

    video_path = _validate_input_path(video_path)
    if output_path is None:
        base, _ = os.path.splitext(video_path)
        output_path = f"{base}_frame_{int(timestamp)}s.png"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(timestamp),
        "-i",
        video_path,
        "-vframes",
        "1",
        "-q:v",
        "2",
        output_path,
    ]

    try:
        subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_FFMPEG_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise MCPVideoError(
            f"Failed to extract verification frame: {exc.stderr[-200:]}",
            error_type="processing_error",
            code="frame_extraction_failed",
        ) from exc

    return output_path
