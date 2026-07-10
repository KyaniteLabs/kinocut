"""Image analysis engine — color extraction, palette generation, product analysis.

Pure Python (no FFmpeg). Requires optional deps: Pillow, scikit-learn, webcolors.
Install with: pip install mcp-video[image]
"""

from __future__ import annotations

import colorsys
import os

from .errors import MCPVideoError
from .image_models import (
    ColorExtractionResult,
    DominantColor,
    PaletteColor,
    PaletteResult,
    ProductAnalysisResult,
)

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"})


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _require_image_deps() -> None:
    """Raise a helpful error if optional image deps are not installed."""
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        raise MCPVideoError(
            "Image analysis requires optional dependencies. Install with: pip install mcp-video[image]",
            error_type="dependency_error",
            code="missing_optional_dep",
            suggested_action={
                "auto_fix": False,
                "description": "Run: pip install mcp-video[image]",
            },
        ) from None


VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi"})


def _validate_image(path: str) -> None:
    """Check file exists and is a supported image or video format."""
    if not os.path.isfile(path):
        raise MCPVideoError(
            f"File not found: {path}",
            error_type="input_error",
            code="file_not_found",
        )
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS and ext not in VIDEO_EXTENSIONS:
        raise MCPVideoError(
            (
                f"Unsupported format: {ext}. "
                f"Supported images: {', '.join(sorted(SUPPORTED_EXTENSIONS))}. "
                f"Supported videos: {', '.join(sorted(VIDEO_EXTENSIONS))}"
            ),
            error_type="validation_error",
            code="unsupported_format",
        )


def _extract_frame_if_video(path: str) -> str:
    """If path is a video, extract a frame and return the temp frame path."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        return path
    from .engine_thumbnail import thumbnail
    import tempfile

    frame_path = os.path.join(tempfile.gettempdir(), f"mcp_video_frame_{os.path.basename(path)}.jpg")
    result = thumbnail(path, output_path=frame_path)
    return result.frame_path


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB (0-255) to hex string like '#8B4513'."""
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert RGB (0-255) to HSL (0-1 range)."""
    return colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)


def _hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[int, int, int]:
    """Convert HSL (0-1 range) to RGB (0-255)."""
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def _closest_color_name(r: int, g: int, b: int) -> str:
    """Find the nearest CSS color name for an RGB value using webcolors."""
    try:
        import webcolors
    except ImportError:
        return _rgb_to_hex(r, g, b)

    try:
        return webcolors.hex_to_name(_rgb_to_hex(r, g, b))
    except ValueError:
        pass

    # Find closest by Euclidean distance
    best_name = ""
    best_dist = float("inf")
    for name in webcolors.names(webcolors.CSS3):
        try:
            hex_val = webcolors.name_to_hex(name)
        except ValueError:
            continue
        cr = int(hex_val[1:3], 16)
        cg = int(hex_val[3:5], 16)
        cb = int(hex_val[5:7], 16)
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_colors(
    image_path: str,
    n_colors: int = 5,
) -> ColorExtractionResult:
    """Extract dominant colors from an image using K-means clustering."""
    _require_image_deps()
    _validate_image(image_path)

    # If video input, extract a representative frame
    frame_path = _extract_frame_if_video(image_path)
    if frame_path != image_path:
        image_path = frame_path

    if n_colors < 1 or n_colors > 20:
        raise MCPVideoError(
            "n_colors must be between 1 and 20",
            error_type="validation_error",
            code="invalid_n_colors",
        )

    import numpy as np
    from PIL import Image
    from sklearn.cluster import MiniBatchKMeans

    img = Image.open(image_path).convert("RGB")
    # Resize for speed — max 200px on the longest side
    img.thumbnail((200, 200))
    pixels = np.array(img).reshape(-1, 3).astype(float)
    if len(pixels) > 50000:
        pixels = pixels[:50000]

    kmeans = MiniBatchKMeans(n_clusters=n_colors, random_state=42, n_init=3)
    labels = kmeans.fit_predict(pixels)

    # Count pixels per cluster
    counts: dict[int, int] = {}
    for label in labels:
        counts[int(label)] = counts.get(int(label), 0) + 1
    total = len(labels)

    # Sort by pixel count descending
    sorted_clusters = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    colors: list[DominantColor] = []
    for cluster_id, count in sorted_clusters:
        center = kmeans.cluster_centers_[cluster_id]
        r, g, b = round(center[0]), round(center[1]), round(center[2])
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        colors.append(
            DominantColor(
                hex=_rgb_to_hex(r, g, b),
                rgb=(r, g, b),
                name=_closest_color_name(r, g, b),
                percentage=round(count / total * 100, 1),
            )
        )

    return ColorExtractionResult(
        image_path=image_path,
        colors=colors,
        n_colors=n_colors,
    )


def generate_palette(
    image_path: str,
    harmony: str = "complementary",
    n_colors: int = 5,
) -> PaletteResult:
    """Generate a color harmony palette from an image's dominant color."""
    _require_image_deps()
    _validate_image(image_path)

    # If video input, extract a representative frame
    frame_path = _extract_frame_if_video(image_path)
    if frame_path != image_path:
        image_path = frame_path

    valid_harmonies = {"complementary", "analogous", "triadic", "split_complementary"}
    if harmony not in valid_harmonies:
        raise MCPVideoError(
            f"Invalid harmony '{harmony}'. Valid options: {', '.join(sorted(valid_harmonies))}",
            error_type="validation_error",
            code="invalid_harmony",
        )

    # Get dominant color
    extraction = extract_colors(image_path, n_colors=n_colors)
    source = extraction.colors[0]
    r, g, b = source.rgb

    # Convert to HSL for harmony math
    h, lightness, s = _rgb_to_hsl(r, g, b)

    # Harmony rotation rules
    harmony_offsets: dict[str, list[float]] = {
        "complementary": [0.0, 0.5],
        "analogous": [0.0, 1 / 12, -1 / 12, 2 / 12, -2 / 12],
        "triadic": [0.0, 1 / 3, 2 / 3],
        "split_complementary": [0.0, 150 / 360, 210 / 360],
    }
    offsets = harmony_offsets[harmony]

    role_names: dict[str, list[str]] = {
        "complementary": ["base", "complement"],
        "analogous": ["base", "analogous1", "analogous2", "analogous3", "analogous4"],
        "triadic": ["base", "triadic1", "triadic2"],
        "split_complementary": ["base", "split1", "split2"],
    }

    palette: list[PaletteColor] = []
    for i, offset in enumerate(offsets):
        new_h = (h + offset) % 1.0
        nr, ng, nb = _hsl_to_rgb(new_h, s, lightness)
        role = role_names[harmony][i] if i < len(role_names[harmony]) else f"accent{i}"
        palette.append(
            PaletteColor(
                hex=_rgb_to_hex(nr, ng, nb),
                rgb=(nr, ng, nb),
                role=role,
            )
        )

    return PaletteResult(
        image_path=image_path,
        harmony=harmony,
        palette=palette,
        source_color=source,
    )


def analyze_product(
    image_path: str,
    use_ai: bool = False,
    n_colors: int = 5,
) -> ProductAnalysisResult:
    """Analyze a product image — colors + optional AI description."""
    _require_image_deps()
    _validate_image(image_path)

    # If video input, extract a representative frame
    frame_path = _extract_frame_if_video(image_path)
    if frame_path != image_path:
        image_path = frame_path

    colors_result = extract_colors(image_path, n_colors=n_colors)

    description: str | None = None
    if use_ai:
        try:
            import anthropic
        except ImportError:
            raise MCPVideoError(
                "AI description requires the anthropic package. Install with: pip install mcp-video[image-ai]",
                error_type="dependency_error",
                code="missing_ai_dep",
                suggested_action={
                    "auto_fix": False,
                    "description": "Run: pip install mcp-video[image-ai]",
                },
            ) from None

        import base64
        import mimetypes

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MCPVideoError(
                "ANTHROPIC_API_KEY environment variable is required for AI descriptions.",
                error_type="auth_error",
                code="missing_api_key",
            )

        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": img_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Describe this product image concisely in 2-3 sentences. "
                            "Focus on the product type, colors, and key visual features.",
                        },
                    ],
                }
            ],
        )
        description = response.content[0].text

    return ProductAnalysisResult(
        image_path=image_path,
        colors=colors_result.colors,
        description=description,
        ai_description=use_ai,
    )
