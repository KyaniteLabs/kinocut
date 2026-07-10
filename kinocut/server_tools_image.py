"""Image MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp
from .ffmpeg_helpers import _validate_input_path


@mcp.tool()
@_safe_tool
def image_extract_colors(
    image_path: str,
    n_colors: int = 5,
) -> dict[str, Any]:
    """Extract dominant colors from an image or video frame.

    Uses K-means clustering to find the most prominent colors. Returns hex codes,
    RGB values, CSS color names, and percentage coverage.

    Args:
        image_path: Absolute path to the image or video file. If video, extracts a representative frame.
        n_colors: Number of dominant colors to extract (1-20, default 5).
    """
    image_path = _validate_input_path(image_path)
    from .image_engine import extract_colors

    return _result(extract_colors(image_path, n_colors=n_colors))


@mcp.tool()
@_safe_tool
def image_generate_palette(
    image_path: str,
    harmony: str = "complementary",
    n_colors: int = 5,
) -> dict[str, Any]:
    """Generate a color harmony palette from an image or video frame.

    Extracts the dominant color and generates harmonious colors based on
    color theory (complementary, analogous, triadic, split_complementary).

    Args:
        image_path: Absolute path to the image or video file. If video, extracts a representative frame.
        harmony: Harmony type (complementary, analogous, triadic, split_complementary).
        n_colors: Number of dominant colors to base palette on (default 5).
    """
    image_path = _validate_input_path(image_path)
    from .image_engine import generate_palette

    return _result(generate_palette(image_path, harmony=harmony, n_colors=n_colors))


@mcp.tool()
@_safe_tool
def image_analyze_product(
    image_path: str,
    use_ai: bool = False,
    n_colors: int = 5,
) -> dict[str, Any]:
    """Analyze a product image or video frame — extract colors and optionally generate AI description.

    Extracts dominant colors from an image. Optionally uses Claude Vision to
    generate a natural language description of the product.

    Args:
        image_path: Absolute path to the image or video file. If video, extracts a representative frame.
        use_ai: If True, use Claude Vision to generate a description (requires ANTHROPIC_API_KEY).
        n_colors: Number of dominant colors to extract (default 5).
    """
    image_path = _validate_input_path(image_path)
    from .image_engine import analyze_product

    return _result(analyze_product(image_path, use_ai=use_ai, n_colors=n_colors))
