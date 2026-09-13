"""Tests for output path derivation helpers."""

import os

import pytest

from mcp_video.paths import _auto_output, _auto_output_dir


class TestAutoOutputAbsolutePaths:
    """Derived output paths must stay absolute on every platform.

    On Windows the leading ``C:`` is a drive separator, not an FFmpeg filter
    hazard. Sanitising it turns an absolute path into a relative one and every
    default-output operation fails.
    """

    def test_auto_output_preserves_absolute_input(self, tmp_path):
        result = _auto_output(str(tmp_path / "clip.mp4"))
        assert os.path.isabs(result)
        assert os.path.dirname(result) == str(tmp_path)

    def test_auto_output_dir_preserves_absolute_input(self, tmp_path):
        result = _auto_output_dir(str(tmp_path / "clip.mp4"))
        assert os.path.isabs(result)
        assert os.path.dirname(result) == str(tmp_path)

    @pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
    def test_auto_output_keeps_drive_letter(self):
        assert _auto_output(r"C:\media\clip.mp4") == r"C:\media\clip_edited.mp4"

    @pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
    def test_auto_output_dir_keeps_drive_letter(self):
        assert _auto_output_dir(r"C:\media\clip.mp4") == r"C:\media\clip_output"


class TestAutoOutputColonSanitising:
    """Colons outside the drive prefix are still replaced."""

    def test_colon_in_directory_is_sanitised(self):
        result = _auto_output("/media/a:b/clip.mp4")
        assert ":" not in result
        assert "a_b" in result

    def test_colon_in_filename_is_sanitised(self):
        assert "we_ird" in _auto_output("/media/x/we:ird.mp4")

    @pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
    def test_drive_kept_while_other_colons_sanitised(self):
        assert _auto_output(r"C:\media\a:b\clip.mp4") == r"C:\media\a_b\clip_edited.mp4"


class TestAutoOutputExistingBehaviour:
    """Pre-existing contract must not change."""

    def test_suffix_and_extension(self):
        assert _auto_output("/media/clip.mp4", "trimmed") == "/media/clip_trimmed.mp4"

    def test_explicit_extension_override(self):
        assert _auto_output("/media/clip.mp4", "audio", ext=".mp3") == "/media/clip_audio.mp3"

    def test_missing_extension_defaults_to_mp4(self):
        assert _auto_output("/media/clip", "out") == "/media/clip_out.mp4"

    def test_output_never_equals_input(self):
        source = "/media/clip.mp4"
        assert _auto_output(source) != source
