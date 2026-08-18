"""Tests for image analysis engine — color extraction, palette generation, product analysis.

Unit tests (no deps needed) and integration tests (requires Pillow + scikit-learn).
"""

import os
import tempfile

import pytest

from mcp_video.errors import MCPVideoError


# ---------------------------------------------------------------------------
# Unit tests — no image deps needed (mocked)
# ---------------------------------------------------------------------------


class TestRgbToHex:
    def test_basic(self):
        from mcp_video.image_engine import _rgb_to_hex

        assert _rgb_to_hex(139, 69, 19) == "#8B4513"

    def test_black(self):
        from mcp_video.image_engine import _rgb_to_hex

        assert _rgb_to_hex(0, 0, 0) == "#000000"

    def test_white(self):
        from mcp_video.image_engine import _rgb_to_hex

        assert _rgb_to_hex(255, 255, 255) == "#FFFFFF"

    def test_red(self):
        from mcp_video.image_engine import _rgb_to_hex

        assert _rgb_to_hex(255, 0, 0) == "#FF0000"


class TestRgbToHsl:
    def test_red(self):
        from mcp_video.image_engine import _rgb_to_hsl

        h, lightness, s = _rgb_to_hsl(255, 0, 0)
        assert h == pytest.approx(0.0, abs=0.01)
        assert s == pytest.approx(1.0, abs=0.01)
        assert lightness == pytest.approx(0.5, abs=0.01)

    def test_white(self):
        from mcp_video.image_engine import _rgb_to_hsl

        _, lightness, _ = _rgb_to_hsl(255, 255, 255)
        assert lightness == pytest.approx(1.0, abs=0.01)

    def test_black(self):
        from mcp_video.image_engine import _rgb_to_hsl

        _, lightness, _ = _rgb_to_hsl(0, 0, 0)
        assert lightness == pytest.approx(0.0, abs=0.01)


class TestHslToRgb:
    def test_roundtrip_red(self):
        from mcp_video.image_engine import _hsl_to_rgb, _rgb_to_hsl

        h, lightness, s = _rgb_to_hsl(255, 0, 0)
        r, g, b = _hsl_to_rgb(h, s, lightness)
        assert (r, g, b) == (255, 0, 0)

    def test_roundtrip_blue(self):
        from mcp_video.image_engine import _hsl_to_rgb, _rgb_to_hsl

        h, lightness, s = _rgb_to_hsl(0, 0, 255)
        r, g, b = _hsl_to_rgb(h, s, lightness)
        assert (r, g, b) == (0, 0, 255)


class TestModelsValidate:
    def test_dominant_color(self):
        from mcp_video.image_models import DominantColor

        c = DominantColor(hex="#FF0000", rgb=(255, 0, 0), name="red", percentage=50.0)
        assert c.hex == "#FF0000"
        assert c.percentage == 50.0

    def test_color_extraction_result(self):
        from mcp_video.image_models import ColorExtractionResult, DominantColor

        colors = [DominantColor(hex="#FF0000", rgb=(255, 0, 0), name="red", percentage=100.0)]
        result = ColorExtractionResult(image_path="/tmp/test.jpg", colors=colors, n_colors=1)
        assert result.success is True
        assert len(result.colors) == 1

    def test_palette_result(self):
        from mcp_video.image_models import PaletteColor, PaletteResult, DominantColor

        source = DominantColor(hex="#FF0000", rgb=(255, 0, 0), name="red", percentage=50.0)
        palette = [PaletteColor(hex="#00FFFF", rgb=(0, 255, 255), role="complement")]
        result = PaletteResult(
            image_path="/tmp/test.jpg", harmony="complementary", palette=palette, source_color=source
        )
        assert result.harmony == "complementary"

    def test_product_analysis_result(self):
        from mcp_video.image_models import ProductAnalysisResult, DominantColor

        colors = [DominantColor(hex="#FF0000", rgb=(255, 0, 0), name="red", percentage=100.0)]
        result = ProductAnalysisResult(image_path="/tmp/test.jpg", colors=colors)
        assert result.ai_description is False
        assert result.description is None


class TestValidateImage:
    def test_missing_file(self):
        from mcp_video.image_engine import _validate_image

        with pytest.raises(MCPVideoError) as exc_info:
            _validate_image("/nonexistent/path/image.jpg")
        assert exc_info.value.code == "file_not_found"

    def test_unsupported_format(self):
        from mcp_video.image_engine import _validate_image

        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"not an image")
            tmp_path = f.name
        try:
            with pytest.raises(MCPVideoError) as exc_info:
                _validate_image(tmp_path)
            assert exc_info.value.code == "unsupported_format"
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Integration tests — requires Pillow + scikit-learn
# ---------------------------------------------------------------------------

try:
    import PIL.Image
    import importlib.util

    HAS_IMAGE_DEPS = all(importlib.util.find_spec(module) is not None for module in ("numpy", "sklearn"))
except ImportError:
    HAS_IMAGE_DEPS = False

pytestmark = pytest.mark.skipif(not HAS_IMAGE_DEPS, reason="Image deps not installed")


def _create_solid_image(color: tuple[int, int, int], size: tuple[int, int] = (100, 100), fmt: str = "PNG") -> str:
    """Create a temporary solid-color image for testing."""
    img = PIL.Image.new("RGB", size, color)
    ext = ".jpg" if fmt == "JPEG" else ".png"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        path = tmp.name
    img.save(path, format=fmt)
    return path


def _create_two_color_image(
    color1: tuple[int, int, int],
    color2: tuple[int, int, int],
    size: tuple[int, int] = (200, 100),
) -> str:
    """Create a temporary image with left half color1, right half color2."""
    img = PIL.Image.new("RGB", size, color1)
    right_half = PIL.Image.new("RGB", (size[0] // 2, size[1]), color2)
    img.paste(right_half, (size[0] // 2, 0))
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = tmp.name
    img.save(path, format="PNG")
    return path


class TestExtractColors:
    def test_solid_color_image(self):
        from mcp_video.image_engine import extract_colors

        path = _create_solid_image((255, 0, 0))
        try:
            result = extract_colors(path, n_colors=3)
            assert result.success is True
            assert len(result.colors) >= 1
            top = result.colors[0]
            # Red should be dominant
            assert top.rgb[0] > 200
            assert top.percentage > 90
        finally:
            os.unlink(path)

    def test_two_color_image(self):
        from mcp_video.image_engine import extract_colors

        path = _create_two_color_image((255, 0, 0), (0, 0, 255))
        try:
            result = extract_colors(path, n_colors=2)
            assert result.success is True
            assert len(result.colors) == 2
            # Both colors should have ~50% coverage
            for c in result.colors:
                assert c.percentage > 30
        finally:
            os.unlink(path)

    def test_n_colors_validated(self):
        from mcp_video.image_engine import extract_colors

        path = _create_solid_image((0, 0, 0))
        try:
            with pytest.raises(MCPVideoError):
                extract_colors(path, n_colors=0)
        finally:
            os.unlink(path)

    def test_result_has_hex(self):
        from mcp_video.image_engine import extract_colors

        path = _create_solid_image((128, 64, 32))
        try:
            result = extract_colors(path, n_colors=1)
            hex_val = result.colors[0].hex
            assert hex_val.startswith("#")
            assert len(hex_val) == 7
        finally:
            os.unlink(path)


class TestGeneratePalette:
    def test_complementary_from_red(self):
        from mcp_video.image_engine import generate_palette

        path = _create_solid_image((255, 0, 0))
        try:
            result = generate_palette(path, harmony="complementary")
            assert result.harmony == "complementary"
            assert len(result.palette) == 2
            assert result.palette[0].role == "base"
            assert result.palette[1].role == "complement"
            # Complement of red should be cyan-ish
            comp = result.palette[1].rgb
            assert comp[2] > 200  # High blue
        finally:
            os.unlink(path)

    def test_triadic_from_red(self):
        from mcp_video.image_engine import generate_palette

        path = _create_solid_image((255, 0, 0))
        try:
            result = generate_palette(path, harmony="triadic")
            assert len(result.palette) == 3
            # Triadic from red should include green and blue tones
        finally:
            os.unlink(path)

    def test_invalid_harmony(self):
        from mcp_video.image_engine import generate_palette

        path = _create_solid_image((128, 128, 128))
        try:
            with pytest.raises(MCPVideoError) as exc_info:
                generate_palette(path, harmony="invalid")
            assert exc_info.value.code == "invalid_harmony"
        finally:
            os.unlink(path)


class TestAnalyzeProduct:
    def test_no_ai(self):
        from mcp_video.image_engine import analyze_product

        path = _create_solid_image((64, 128, 200))
        try:
            result = analyze_product(path, use_ai=False)
            assert result.success is True
            assert result.ai_description is False
            assert result.description is None
            assert len(result.colors) > 0
        finally:
            os.unlink(path)


class TestGracefulError:
    def test_missing_deps_error_message(self):
        """Verify _require_image_deps raises the expected error structure."""
        # We can only test this if we mock the import to fail
        # Since deps ARE installed in test env, we mock instead
        from unittest.mock import patch
        from mcp_video.image_engine import _require_image_deps

        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            # Force ImportError by patching the import
            import builtins

            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "PIL.Image":
                    raise ImportError("No module named 'PIL'")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                with pytest.raises(MCPVideoError) as exc_info:
                    _require_image_deps()
                assert exc_info.value.code == "missing_optional_dep"
                assert "kinocut[image]" in str(exc_info.value)
