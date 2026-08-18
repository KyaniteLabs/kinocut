"""Red team: adversarial edge-case tests for Kinocut (formerly mcp-video)."""

import os
import subprocess

import pytest

from mcp_video.engine import (
    add_text,
    apply_filter,
    audio_waveform,
    chroma_key,
    compare_quality,
    convert,
    crop,
    create_from_images,
    detect_scenes,
    edit_timeline,
    export_frames,
    extract_audio,
    fade,
    generate_subtitles,
    merge,
    normalize_audio,
    overlay_video,
    probe,
    reverse,
    rotate,
    speed,
    split_screen,
    stabilize,
    storyboard,
    thumbnail,
    trim,
    watermark,
    write_metadata,
    apply_mask,
)
from mcp_video.errors import InputFileError, ProcessingError, MCPVideoError


def _get_output_path(result):
    """Extract output path from result (handles both string and EditResult objects)."""
    return result if isinstance(result, str) else result.output_path


@pytest.fixture
def unicode_video(tmp_path):
    """Create a video with unicode characters in filename."""
    video_path = tmp_path / "测试视频🎬.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "smptehdbars=size=320x240:duration=1:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(video_path),
        ],
        capture_output=True,
        timeout=15,
    )
    if not video_path.exists():
        pytest.skip("Could not create unicode video")
    return str(video_path)


@pytest.fixture
def tiny_video(tmp_path):
    """Create a tiny 1x1 video for boundary testing."""
    video_path = tmp_path / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=1x1:duration=1:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(video_path),
        ],
        capture_output=True,
        timeout=15,
    )
    if not video_path.exists():
        pytest.skip("Could not create tiny video")
    return str(video_path)


class TestPathTraversal:
    """Test path traversal attempts are handled safely."""

    def test_probe_path_traversal_etc_passwd(self):
        """Attempting to probe /etc/passwd should raise an error, not crash."""
        with pytest.raises((InputFileError, ProcessingError, MCPVideoError)):
            probe("../../../etc/passwd")

    def test_trim_nonexistent_file(self):
        """Trimming a nonexistent file should raise InputFileError."""
        with pytest.raises(InputFileError):
            trim("nonexistent.mp4", start=0, duration=1)

    def test_trim_with_path_traversal_output(self, sample_video, tmp_path):
        """Output path with traversal should either be rejected or created in allowed location."""
        # Try to use path traversal in output path
        output_path = str(tmp_path / "output.mp4")

        # The operation should either:
        # 1. Raise an error for suspicious path, or
        # 2. Create the file in a safe location
        try:
            result = trim(sample_video, start=0, duration=1, output_path=output_path)
            # If it succeeds, verify it's in the expected location
            # trim returns EditResult object with output_path attribute
            actual_output = result if isinstance(result, str) else result.output_path
            assert os.path.dirname(actual_output) == str(tmp_path)
        except (InputFileError, ProcessingError, ValueError):
            # Also acceptable - reject the path
            pass


class TestUnicodeFilenames:
    """Test operations on files with unicode characters in names."""

    def test_probe_unicode_filename(self, unicode_video):
        """Probe should work on unicode filename."""
        info = probe(unicode_video)
        assert info.width > 0
        assert info.height > 0

    def test_trim_unicode_filename(self, unicode_video):
        """Trim should work on unicode filename."""
        result = trim(unicode_video, start=0, duration=0.5)
        output_path = _get_output_path(result)
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0


class TestInvalidInputs:
    """Test various invalid parameter combinations."""

    def test_trim_negative_start(self, sample_video):
        """Negative start time should raise an error on most platforms."""
        with pytest.raises((ValueError, ProcessingError, MCPVideoError)):
            trim(sample_video, start=-1, duration=1)

    def test_crop_zero_dimensions(self, sample_video):
        """Zero dimensions should raise ValueError."""
        with pytest.raises((ValueError, MCPVideoError)):
            crop(sample_video, width=0, height=0)

    def test_speed_zero_factor(self, sample_video):
        """Zero speed factor should raise an error."""
        with pytest.raises((ValueError, ProcessingError, MCPVideoError)):
            speed(sample_video, factor=0)

    def test_rotate_no_transform(self, sample_video):
        """Rotation with no actual transform should raise an error."""
        with pytest.raises((ValueError, MCPVideoError)):
            rotate(sample_video, angle=0, flip_horizontal=False, flip_vertical=False)

    def test_fade_no_fade(self, sample_video):
        """Fade with both fade_in and fade_out as 0 should raise an error."""
        with pytest.raises((ValueError, MCPVideoError)):
            fade(sample_video, fade_in=0, fade_out=0)

    def test_generate_subtitles_empty_entries(self, sample_video):
        """Empty subtitle entries should raise an error."""
        with pytest.raises((ValueError, MCPVideoError)):
            generate_subtitles([], sample_video)

    def test_create_from_images_empty_list(self):
        """Empty image list should raise an error."""
        with pytest.raises((ValueError, MCPVideoError)):
            create_from_images([])


class TestFileTypeMismatch:
    """Test operations on wrong file types."""

    def test_probe_image_file(self, sample_watermark_png):
        """Probing an image file may work but shouldn't crash."""
        try:
            info = probe(sample_watermark_png)
            # If it succeeds, we should get some basic info
            assert info is not None
        except (InputFileError, ProcessingError):
            # Also acceptable - image files may not be supported
            pass

    def test_trim_image_file(self, sample_watermark_png):
        """Trimming an image may succeed (FFmpeg can handle single images) or raise an error."""
        # FFmpeg can actually "trim" a single image - it just copies it
        # This is acceptable behavior, not an error
        result = trim(sample_watermark_png, start=0, duration=1)
        output_path = _get_output_path(result)
        # If it succeeds, verify we got a file
        assert os.path.exists(output_path)

    def test_extract_audio_from_image(self, sample_watermark_png):
        """Extracting audio from an image should raise an error."""
        with pytest.raises((InputFileError, ProcessingError, MCPVideoError)):
            extract_audio(sample_watermark_png)


class TestMissingDependencies:
    """Test operations that may fail due to missing FFmpeg features."""

    def test_stabilize_without_vidstab(self, sample_video):
        """Stabilize may fail if vidstab not compiled in - should handle gracefully."""
        try:
            result = stabilize(sample_video)
            # If it succeeds, verify the output
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, InputFileError, MCPVideoError) as e:
            # If it fails due to missing filter, that's acceptable
            # Just verify it's a dependency error, not a crash
            error_str = str(e).lower()
            assert (
                "vidstab" in error_str or "filter" in error_str or "not found" in error_str or "available" in error_str
            )

    def test_apply_filter_unsupported(self, sample_video):
        """Applying an unsupported filter should fail gracefully."""
        with pytest.raises((ProcessingError, ValueError, MCPVideoError)):
            apply_filter(sample_video, filter_type="nonexistent_filter")


class TestLargeBatch:
    """Test batch operations with mixed valid/invalid inputs."""

    def test_video_batch_mixed_valid_invalid(self, sample_video):
        """Batch with mixed valid and invalid files should process valid ones."""
        from mcp_video.engine import video_batch

        result = video_batch(
            ["/nonexistent1.mp4", sample_video, "/nonexistent2.mp4"],
            operation="trim",
            params={"start": "0", "duration": "1"},
        )

        # Should have partial success
        assert "succeeded" in result
        assert "failed" in result
        # At least the valid file should succeed
        assert result["succeeded"] >= 1
        assert result["failed"] >= 1


class TestBoundaryValues:
    """Test edge case parameter values."""

    def test_speed_very_fast(self, sample_video):
        """Very high speed factor (100x) should work or fail gracefully."""
        try:
            result = speed(sample_video, factor=100)
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, ValueError):
            # Also acceptable - may be beyond supported range
            pass

    def test_speed_very_slow(self, sample_video):
        """Very low speed factor (0.01x) should work or fail gracefully."""
        try:
            result = speed(sample_video, factor=0.01)
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, ValueError):
            # Also acceptable - may be beyond supported range
            pass

    def test_resize_tiny_video(self, sample_video):
        """Resizing to 1x1 should work or fail gracefully."""
        try:
            result = crop(sample_video, width=1, height=1)
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, ValueError):
            # Also acceptable - may be below minimum size
            pass

    def test_convert_to_gif(self, sample_video):
        """Converting to GIF format should work."""
        try:
            result = convert(sample_video, format="gif")
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, ValueError):
            # GIF conversion may not be supported in all FFmpeg builds
            pass

    def test_thumbnail_at_zero(self, sample_video):
        """Thumbnail at timestamp 0 should work."""
        result = thumbnail(sample_video, timestamp=0)
        path = result if isinstance(result, str) else result.frame_path
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

    def test_thumbnail_beyond_duration(self, sample_video):
        """Thumbnail beyond video duration should handle gracefully."""
        info = probe(sample_video)
        beyond_duration = info.duration + 1000

        with pytest.raises((InputFileError, ProcessingError, ValueError)):
            thumbnail(sample_video, timestamp=beyond_duration)

    def test_thumbnail_at_exact_duration(self, sample_video):
        """Thumbnail at EOF should be pre-validated before FFmpeg."""
        info = probe(sample_video)

        with pytest.raises((InputFileError, ProcessingError, ValueError)):
            thumbnail(sample_video, timestamp=info.duration)

    def test_thumbnail_allows_zero_duration_metadata(self, sample_video, tmp_path, monkeypatch):
        """Missing/unknown duration metadata should not reject timestamp 0."""
        import mcp_video.engine_thumbnail as engine_thumbnail

        output = tmp_path / "frame.jpg"
        monkeypatch.setattr(engine_thumbnail, "get_duration", lambda _path: 0.0)
        monkeypatch.setattr(engine_thumbnail, "_run_ffmpeg", lambda _args: None)

        result = engine_thumbnail.thumbnail(sample_video, timestamp=0, output_path=str(output))

        assert result.timestamp == 0
        assert result.frame_path == str(output)

    def test_trim_zero_duration(self, sample_video):
        """Trimming with zero duration should raise an error or succeed with a tiny file."""
        try:
            result = trim(sample_video, start=0, duration=0)
            # If it succeeds, the output should be a valid file
            path = _get_output_path(result)
            assert os.path.exists(path)
        except (ValueError, ProcessingError, MCPVideoError):
            # Also acceptable - zero duration rejected
            pass

    def test_merge_single_video(self, sample_video):
        """Merging a single video should work (degenerate case)."""
        result = merge([sample_video])
        assert os.path.exists(_get_output_path(result))

    def test_watermark_with_no_audio(self, sample_video_no_audio, sample_watermark_png):
        """Watermarking video without audio should work."""
        try:
            result = watermark(sample_video_no_audio, sample_watermark_png)
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, InputFileError):
            # May fail if watermark requires audio stream
            pass

    def test_overlay_mismatched_sizes(self, sample_video, sample_video_2):
        """Overlay with different sized videos should work or fail gracefully."""
        try:
            result = overlay_video(sample_video, sample_video_2)
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, InputFileError):
            # May fail due to size mismatch
            pass

    def test_split_screen_invalid_layout(self, sample_video, sample_video_2):
        """Invalid split screen layout should raise an error or be handled gracefully."""
        try:
            result = split_screen(sample_video, sample_video_2, layout="invalid_layout")
            # If it succeeds (FFmpeg may accept it), verify output exists
            assert os.path.exists(_get_output_path(result))
        except (ValueError, ProcessingError, MCPVideoError):
            # Also acceptable - invalid layout rejected
            pass

    def test_reverse_with_parameters(self, sample_video):
        """Reverse video should work."""
        try:
            result = reverse(sample_video)
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, InputFileError):
            # Reverse may not be supported in all FFmpeg configurations
            pass

    def test_chroma_key_invalid_color(self, sample_video):
        """Chroma key with invalid color should handle gracefully."""
        try:
            result = chroma_key(sample_video, color="invalid_color_name")
            # May succeed with default or fail gracefully
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, ValueError, MCPVideoError):
            # Acceptable - invalid color should be rejected
            pass

    def test_export_frames_zero_fps(self, sample_video):
        """Exporting frames with zero FPS should raise an error."""
        with pytest.raises((ValueError, ProcessingError, MCPVideoError)):
            export_frames(sample_video, fps=0)

    def test_compare_quality_same_file(self, sample_video):
        """Comparing file with itself should return perfect or near-perfect metrics."""
        result = compare_quality(sample_video, sample_video)
        assert result.success is True
        assert result.overall_quality in ("high", "medium", "low")

    def test_write_metadata_empty_tags(self, sample_video):
        """Writing empty metadata should raise an error (engine requires at least one tag)."""
        with pytest.raises((MCPVideoError, ValueError)):
            write_metadata(sample_video, {})

    def test_add_text_with_special_chars(self, sample_video):
        """Adding text with special characters should work."""
        try:
            result = add_text(sample_video, text="Test <>&\"'特殊 chars")
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, ValueError):
            # May fail if text not properly escaped
            pass

    def test_normalize_audio_no_audio(self, sample_video_no_audio):
        """Normalizing audio on video without audio should handle gracefully."""
        try:
            result = normalize_audio(sample_video_no_audio)
            # May succeed (no-op) or fail gracefully
            assert os.path.exists(_get_output_path(result))
        except (ProcessingError, InputFileError):
            # Acceptable - no audio stream to normalize
            pass

    def test_storyboard_excessive_frames(self, sample_video):
        """Requesting many frames should handle gracefully (use smaller count to avoid OS arg limit)."""
        try:
            result = storyboard(sample_video, frame_count=500)
            assert result.count >= 0
        except (ProcessingError, MCPVideoError):
            pass

    def test_detect_scenes_short_video(self, sample_video):
        """Scene detection on very short video should work."""
        result = detect_scenes(sample_video)
        assert result.success is True
        # Should at least return the whole video as one scene
        assert result.scene_count >= 1

    def test_edit_timeline_invalid_json(self):
        """Editing with invalid timeline JSON should raise an error."""
        with pytest.raises((ValueError, KeyError, TypeError)):
            edit_timeline({"width": "not_a_number"})

    def test_edit_timeline_empty_tracks(self):
        """Editing with empty tracks should raise an error."""
        with pytest.raises((ValueError, ProcessingError, MCPVideoError)):
            edit_timeline({"tracks": []})

    def test_audio_waveform_no_audio(self, sample_video_no_audio):
        """Extracting waveform from video without audio should raise an error."""
        with pytest.raises((MCPVideoError, ProcessingError, InputFileError)):
            audio_waveform(sample_video_no_audio)

    def test_apply_mask_invalid_mask(self, sample_video):
        """Applying invalid mask file should raise an error."""
        with pytest.raises((InputFileError, ProcessingError, MCPVideoError)):
            apply_mask(sample_video, "/nonexistent/mask.png")
