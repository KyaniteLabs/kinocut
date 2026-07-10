"""mcp-video Python client — clean API for programmatic video editing."""

from __future__ import annotations


class ClientImageMixin:
    """Image operations mixin."""

    def extract_colors(
        self,
        image_path: str,
        n_colors: int = 5,
    ) -> dict:
        """Extract dominant colors from an image using K-means clustering."""
        from ..image_engine import extract_colors

        return extract_colors(image_path, n_colors=n_colors)

    def generate_palette(
        self,
        image_path: str,
        harmony: str = "complementary",
        n_colors: int = 5,
    ) -> dict:
        """Generate a color harmony palette from an image's dominant color."""
        from ..image_engine import generate_palette

        return generate_palette(image_path, harmony=harmony, n_colors=n_colors)

    def analyze_product(
        self,
        image_path: str,
        use_ai: bool = False,
        n_colors: int = 5,
    ) -> dict:
        """Analyze a product image — extract colors and optionally generate AI description."""
        from ..image_engine import analyze_product

        return analyze_product(image_path, use_ai=use_ai, n_colors=n_colors)
