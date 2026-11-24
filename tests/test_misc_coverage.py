"""Targeted tests to raise coverage on small utility modules."""

from pathlib import Path
from unittest.mock import patch

import pytest


class TestServerToolsImage:
    """Test server_tools_image validation and error paths."""

    def test_image_extract_colors_validation_error(self):
        from mcp_video.server_tools_image import image_extract_colors

        with patch("mcp_video.server_tools_image._validate_input_path", side_effect=Exception("bad path")):
            result = image_extract_colors("/bad")
        assert result.get("success") is False

    def test_image_generate_palette_validation_error(self):
        from mcp_video.server_tools_image import image_generate_palette

        with patch("mcp_video.server_tools_image._validate_input_path", side_effect=Exception("bad path")):
            result = image_generate_palette("/bad")
        assert result.get("success") is False

    def test_image_analyze_product_validation_error(self):
        from mcp_video.server_tools_image import image_analyze_product

        with patch("mcp_video.server_tools_image._validate_input_path", side_effect=Exception("bad path")):
            result = image_analyze_product("/bad")
        assert result.get("success") is False


class TestServerToolsHyperframesValidation:
    """Test server_tools_hyperframes validation paths."""

    def test_hyperframes_render_invalid_quality(self):
        from mcp_video.server_tools_hyperframes import hyperframes_render

        result = hyperframes_render("/tmp/proj", quality="bad")
        assert result.get("success") is False

    def test_hyperframes_render_invalid_format(self):
        from mcp_video.server_tools_hyperframes import hyperframes_render

        result = hyperframes_render("/tmp/proj", format="bad")
        assert result.get("success") is False

    def test_hyperframes_render_invalid_width(self):
        from mcp_video.server_tools_hyperframes import hyperframes_render

        result = hyperframes_render("/tmp/proj", width=99999)
        assert result.get("success") is False

    def test_hyperframes_render_invalid_height(self):
        from mcp_video.server_tools_hyperframes import hyperframes_render

        result = hyperframes_render("/tmp/proj", height=99999)
        assert result.get("success") is False

    def test_hyperframes_render_invalid_crf(self):
        from mcp_video.server_tools_hyperframes import hyperframes_render

        result = hyperframes_render("/tmp/proj", crf=999)
        assert result.get("success") is False

    def test_hyperframes_preview_invalid_port(self):
        from mcp_video.server_tools_hyperframes import hyperframes_preview

        result = hyperframes_preview("/tmp/proj", port=99999)
        assert result.get("success") is False

    def test_hyperframes_init_invalid_name(self):
        from mcp_video.server_tools_hyperframes import hyperframes_init

        result = hyperframes_init("bad name!")
        assert result.get("success") is False

    def test_hyperframes_init_invalid_template(self):
        from mcp_video.server_tools_hyperframes import hyperframes_init

        result = hyperframes_init("test", template="not-real")
        assert result.get("success") is False

    def test_hyperframes_tts_requires_text_unless_listing_voices(self):
        from mcp_video.server_tools_hyperframes import hyperframes_tts

        result = hyperframes_tts()

        assert result.get("success") is False
        assert (
            result.get("error", {})
            .get("message", "")
            .startswith("text_or_file is required unless list_voices is true; retry with call hyperframes_tts")
        )


class TestAudioEngineInit:
    """Test audio_engine/__init__.py add_generated_audio."""

    def test_add_generated_audio_no_events(self, tmp_path):
        from mcp_video.errors import MCPVideoError
        from mcp_video.audio_engine import add_generated_audio

        video = str(tmp_path / "v.mp4")
        video_path = Path(video)
        video_path.write_bytes(b"fake")

        with pytest.raises(MCPVideoError, match="No audio events"):
            add_generated_audio(video, {"events": []}, str(tmp_path / "out.mp4"))

    def test_add_generated_audio_null_bytes(self, tmp_path):
        from mcp_video.errors import InputFileError
        from mcp_video.audio_engine import add_generated_audio

        with pytest.raises(InputFileError):
            add_generated_audio("/tmp/bad\x00path", {"events": [{"type": "tone"}]}, str(tmp_path / "out.mp4"))

    def test_add_generated_audio_missing_file(self, tmp_path):
        from mcp_video.errors import InputFileError
        from mcp_video.audio_engine import add_generated_audio

        with pytest.raises(InputFileError):
            add_generated_audio("/nonexistent.mp4", {"events": [{"type": "tone"}]}, str(tmp_path / "out.mp4"))

    def test_add_generated_audio_unreadable_video_is_a_processing_error(self, tmp_path):
        from kinocut.audio_engine import add_generated_audio
        from kinocut.errors import ProcessingError

        video = tmp_path / "not-a-video.mp4"
        video.write_bytes(b"\x00" * 4096)

        with pytest.raises(ProcessingError):
            add_generated_audio(
                str(video),
                {"events": [{"type": "tone", "at": 0, "duration": 1, "freq": 440}]},
                str(tmp_path / "out.mp4"),
            )
        assert not (tmp_path / "out.mp4").exists()


class TestServerToolsImageSuccess:
    """Test server_tools_image success paths."""

    def test_image_extract_colors_success(self):
        from mcp_video.server_tools_image import image_extract_colors

        with (
            patch("mcp_video.server_tools_image._validate_input_path", return_value="/tmp/img.jpg"),
            patch("mcp_video.image_engine.extract_colors", return_value={"colors": []}),
        ):
            result = image_extract_colors("/tmp/img.jpg")
        assert result.get("success") is True

    def test_image_generate_palette_success(self):
        from mcp_video.server_tools_image import image_generate_palette

        with (
            patch("mcp_video.server_tools_image._validate_input_path", return_value="/tmp/img.jpg"),
            patch("mcp_video.image_engine.generate_palette", return_value={"palette": []}),
        ):
            result = image_generate_palette("/tmp/img.jpg")
        assert result.get("success") is True

    def test_image_analyze_product_success(self):
        from mcp_video.server_tools_image import image_analyze_product

        with (
            patch("mcp_video.server_tools_image._validate_input_path", return_value="/tmp/img.jpg"),
            patch("mcp_video.image_engine.analyze_product", return_value={"description": "test"}),
        ):
            result = image_analyze_product("/tmp/img.jpg", use_ai=True)
        assert result.get("success") is True
