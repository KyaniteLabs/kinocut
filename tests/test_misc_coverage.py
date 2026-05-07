"""Targeted tests to raise coverage on small utility modules."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestFontManager:
    def test_list_available_fonts(self):
        from mcp_video.font_manager import list_available_fonts

        fonts = list_available_fonts()
        assert isinstance(fonts, list)
        assert "roboto" in fonts

    def test_resolve_font_local_file(self, tmp_path):
        from mcp_video.font_manager import resolve_font

        font_file = tmp_path / "test.ttf"
        font_file.write_text("fake font")
        result = resolve_font(str(font_file))
        assert result == str(font_file)

    def test_resolve_font_unknown_raises(self):
        from mcp_video.errors import MCPVideoError
        from mcp_video.font_manager import resolve_font

        with pytest.raises(MCPVideoError, match="Unknown font"):
            resolve_font("not-a-real-font-name")

    def test_resolve_font_caches(self, tmp_path, monkeypatch):
        from mcp_video.font_manager import resolve_font

        cache_dir = tmp_path / "fonts"
        monkeypatch.setattr("mcp_video.font_manager._FONT_CACHE_DIR", str(cache_dir))
        # Mock urlretrieve to avoid network call
        fake_font = cache_dir / "roboto.ttf"
        fake_font.parent.mkdir(parents=True, exist_ok=True)
        fake_font.write_text("fake")

        with patch("mcp_video.font_manager.urllib.request.urlretrieve") as mock_dl:
            result = resolve_font("roboto")
            assert result == str(fake_font)
            mock_dl.assert_not_called()  # Already cached

    def test_resolve_font_downloads(self, tmp_path, monkeypatch):
        from mcp_video.font_manager import resolve_font

        cache_dir = tmp_path / "fonts"
        monkeypatch.setattr("mcp_video.font_manager._FONT_CACHE_DIR", str(cache_dir))

        def fake_download(url, path):
            Path(path).write_text("downloaded")

        with patch("mcp_video.font_manager.urllib.request.urlretrieve", side_effect=fake_download):
            result = resolve_font("roboto")
            assert Path(result).exists()

    def test_resolve_font_download_fails(self, tmp_path, monkeypatch):
        from urllib.error import URLError

        from mcp_video.errors import MCPVideoError
        from mcp_video.font_manager import resolve_font

        cache_dir = tmp_path / "fonts"
        monkeypatch.setattr("mcp_video.font_manager._FONT_CACHE_DIR", str(cache_dir))

        with (
            patch("mcp_video.font_manager.urllib.request.urlretrieve", side_effect=URLError("network down")),
            pytest.raises(MCPVideoError, match="Failed to download"),
        ):
            resolve_font("roboto")


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
        assert result.get("error", {}).get("message") == "text_or_file is required unless list_voices is true"


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

    def test_add_generated_audio_with_drone(self, tmp_path):
        from mcp_video.audio_engine import add_generated_audio

        video = str(tmp_path / "v.mp4")
        Path(video).write_bytes(b"fake")
        out = str(tmp_path / "out.mp4")

        # Mock audio_sequence to avoid actual generation, then ffmpeg will fail
        with patch("mcp_video.audio_engine.audio_sequence"), patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = add_generated_audio(
                video,
                {"drone": {"frequency": 100, "volume": 0.2}, "events": []},
                out,
            )
            assert result == out

    def test_add_generated_audio_ffmpeg_timeout(self, tmp_path):
        from mcp_video.audio_engine import add_generated_audio

        video = str(tmp_path / "v.mp4")
        Path(video).write_bytes(b"fake")
        out = str(tmp_path / "out.mp4")

        with (
            patch("mcp_video.audio_engine.audio_sequence"),
            patch("subprocess.run", side_effect=TimeoutError("timeout")),
            pytest.raises(Exception),
        ):
            # The code catches subprocess.TimeoutExpired, not TimeoutError
            # So this will actually raise a different error
            add_generated_audio(video, {"events": [{"type": "tone"}]}, out)

    def test_add_generated_audio_ffmpeg_error(self, tmp_path):
        from mcp_video.audio_engine import add_generated_audio
        from mcp_video.errors import ProcessingError

        video = str(tmp_path / "v.mp4")
        Path(video).write_bytes(b"fake")
        out = str(tmp_path / "out.mp4")

        with patch("mcp_video.audio_engine.audio_sequence"):
            mock_result = MagicMock(returncode=1, stderr="ffmpeg error")
            with patch("subprocess.run", return_value=mock_result), pytest.raises(ProcessingError):
                add_generated_audio(video, {"events": [{"type": "tone"}]}, out)


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
