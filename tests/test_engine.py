"""Tests for the FFmpeg engine."""

import os

import pytest

from mcp_video.engine import (
    _check_filter_available,
    _generate_thumbnail_base64,
    _parse_ffmpeg_time,
    add_audio,
    add_text,
    add_texts,
    apply_filter,
    chroma_key,
    convert,
    extract_audio,
    merge,
    preview,
    probe,
    probe_audio_input,
    reverse,
    storyboard,
    speed,
    subtitles,
    thumbnail,
    trim,
)
from mcp_video.errors import InputFileError, MCPVideoError
from mcp_video.models import VideoInfo


def requires_filter(name: str, feature: str):
    """Skip test if FFmpeg filter is not available."""
    return pytest.mark.skipif(
        not _check_filter_available(name),
        reason=f"FFmpeg filter '{name}' not available ({feature} requires it)",
    )


def test_probe_duration_falls_back_to_stream_before_limit():
    from mcp_video.engine_probe import _build_video_info
    from mcp_video.limits import MAX_VIDEO_DURATION

    data = {
        "format": {"duration": "N/A"},
        "streams": [
            {
                "codec_type": "video",
                "duration": str(MAX_VIDEO_DURATION + 1),
                "width": 640,
                "height": 360,
                "r_frame_rate": "30/1",
                "codec_name": "h264",
            }
        ],
    }

    with pytest.raises(MCPVideoError, match="exceeds maximum"):
        _build_video_info("video.mp4", data)


class TestProbe:
    def test_probe_returns_video_info(self, sample_video):
        info = probe(sample_video)
        assert isinstance(info, VideoInfo)
        assert info.duration > 0
        assert info.width == 640
        assert info.height == 480
        assert info.codec == "h264"
        assert info.audio_codec is not None

    def test_probe_nonexistent_file(self):
        with pytest.raises(InputFileError):
            probe("/nonexistent/video.mp4")

    def test_probe_corrupted_file(self, tmp_path):
        video = tmp_path / "corrupted.mp4"
        video.write_bytes(b"not a real media file")

        with pytest.raises(InputFileError):
            probe(str(video))

    def test_probe_audio_input_on_video(self, sample_video):
        """probe_audio_input must defer to the normal video probe for video."""
        info = probe_audio_input(sample_video)
        assert isinstance(info, VideoInfo)
        assert info.width == 640
        assert info.height == 480

    def test_probe_audio_input_on_audio_only_wav(self, sample_audio_wav):
        """Issue #7: an audio-only WAV must probe without raising and must
        carry audio metadata, not be rejected for lacking a video stream."""
        info = probe_audio_input(sample_audio_wav)
        assert isinstance(info, VideoInfo)
        assert info.duration > 0
        assert info.audio_codec is not None
        assert info.audio_sample_rate is not None
        # No video stream: video-shaped fields are zeroed, not fabricated.
        assert info.width == 0
        assert info.height == 0

    def test_probe_audio_input_corrupted_still_raises(self, tmp_path):
        """A genuinely broken input still fails — the fallback is audio-aware,
        not a blanket swallow of probe errors."""
        bad = tmp_path / "corrupted.wav"
        bad.write_bytes(b"not a real media file")
        with pytest.raises(InputFileError):
            probe_audio_input(str(bad))

    def test_resolution_property(self, sample_video):
        info = probe(sample_video)
        assert info.resolution == "640x480"

    def test_aspect_ratio_property(self, sample_video):
        info = probe(sample_video)
        assert info.aspect_ratio == "4:3"

    def test_size_mb_property(self, sample_video):
        info = probe(sample_video)
        assert info.size_mb is not None
        assert info.size_mb > 0


class TestTrim:
    def test_trim_by_duration(self, sample_video):
        result = trim(sample_video, start="0", duration="1")
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert abs(info.duration - 1.0) < 0.5
        assert result.operation == "trim"

    def test_trim_by_end(self, sample_video):
        result = trim(sample_video, start="0", end="2")
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert abs(info.duration - 2.0) < 0.5

    def test_trim_custom_output(self, sample_video, tmp_path):
        out = str(tmp_path / "custom_trim.mp4")
        result = trim(sample_video, start="0", duration="1", output_path=out)
        assert result.output_path == out


class TestMerge:
    def test_merge_two_clips(self, sample_video):
        result = merge([sample_video, sample_video])
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        # Merged video should be roughly 2x duration
        assert info.duration > 4
        assert result.operation == "merge"

    def test_merge_single_clip(self, sample_video):
        result = merge([sample_video])
        assert os.path.isfile(result.output_path)

    def test_merge_single_clip_remux_different_extension(self, sample_video, tmp_path):
        """Single-clip merge must remux via FFmpeg when output extension differs."""
        output_mov = str(tmp_path / "out.mov")
        result = merge([sample_video], output_path=output_mov)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        # Probed output should be a valid video in the requested container
        assert info.duration > 0

    def test_merge_persists_validated_multi_clip_paths(self, monkeypatch, tmp_path):
        import types

        import mcp_video.engine_merge as engine_merge

        original_a = str(tmp_path / "a-link.mp4")
        original_b = str(tmp_path / "b-link.mp4")
        resolved_a = str(tmp_path / "a-real.mp4")
        resolved_b = str(tmp_path / "b-real.mp4")
        output = str(tmp_path / "merged.mp4")
        seen_probe_paths = []

        def fake_validate(path):
            return {original_a: resolved_a, original_b: resolved_b}[path]

        def fake_probe(path):
            seen_probe_paths.append(path)
            return types.SimpleNamespace(
                duration=1.0,
                resolution="320x240",
                display_resolution="320x240",
                width=320,
                height=240,
                display_width=320,
                display_height=240,
                codec="h264",
                size_mb=1.0,
                rotation=0,
                audio_codec="aac",
                audio_sample_rate=48000,
                fps=30.0,
            )

        def fake_run_ffmpeg(args):
            concat_file = args[args.index("-i") + 1]
            with open(concat_file, encoding="utf-8") as f:
                concat_data = f.read()
            assert resolved_a in concat_data
            assert resolved_b in concat_data
            assert original_a not in concat_data
            assert original_b not in concat_data

        monkeypatch.setattr(engine_merge, "_validate_input_path", fake_validate)
        monkeypatch.setattr(engine_merge, "probe", fake_probe)
        monkeypatch.setattr("mcp_video.engine_probe.probe", fake_probe)
        monkeypatch.setattr(engine_merge, "_run_ffmpeg", fake_run_ffmpeg)

        result = engine_merge.merge([original_a, original_b], output_path=output)

        assert result.output_path == output
        assert seen_probe_paths[:2] == [resolved_a, resolved_b]

    def test_merge_no_clips_raises(self):
        with pytest.raises(InputFileError):
            merge([])


class TestAddText:
    @requires_filter("drawtext", "Text overlay")
    def test_add_text_overlay(self, sample_video):
        result = add_text(sample_video, text="Hello World")
        assert os.path.isfile(result.output_path)
        assert result.operation == "add_text"

    @requires_filter("drawtext", "Text overlay")
    def test_add_text_with_timing(self, sample_video):
        result = add_text(
            sample_video,
            text="Timed",
            start_time=0.5,
            duration=1.0,
        )
        assert os.path.isfile(result.output_path)


class TestAddTexts:
    @requires_filter("drawtext", "Text overlay")
    def test_add_texts_overlay(self, sample_video):
        result = add_texts(
            sample_video,
            texts=[
                {"text": "Line 1", "position": "center", "size": 48},
                {"text": "Line 2", "position": "center", "size": 36},
            ],
        )
        assert os.path.isfile(result.output_path)
        assert result.operation == "add_texts"

    @requires_filter("drawtext", "Text overlay")
    def test_add_texts_auto_layout(self, sample_video):
        result = add_texts(
            sample_video,
            texts=[
                {"text": "Top", "position": "top-center", "size": 40},
                {"text": "Middle", "position": "top-center", "size": 40},
                {"text": "Bottom", "position": "top-center", "size": 40},
            ],
            auto_layout=True,
        )
        assert os.path.isfile(result.output_path)

    @requires_filter("drawtext", "Text overlay")
    def test_add_texts_with_timing(self, sample_video):
        result = add_texts(
            sample_video,
            texts=[
                {"text": "First", "start_time": 0.5, "duration": 1.0},
                {"text": "Second", "start_time": 2.0, "duration": 1.0},
            ],
        )
        assert os.path.isfile(result.output_path)


class TestAddAudio:
    def test_replace_audio(self, sample_video, sample_audio):
        result = add_audio(sample_video, sample_audio)
        assert os.path.isfile(result.output_path)
        assert result.operation == "add_audio"

    def test_mix_audio(self, sample_video, sample_audio):
        result = add_audio(sample_video, sample_audio, mix=True)
        assert os.path.isfile(result.output_path)

    def test_audio_with_fade(self, sample_video, sample_audio):
        result = add_audio(
            sample_video,
            sample_audio,
            fade_in=0.5,
            fade_out=0.5,
        )
        assert os.path.isfile(result.output_path)

    def test_audio_only_wav_no_video_stream_warning(self, sample_video, sample_audio_wav):
        """Regression for #7: a valid audio-only WAV must not be probed as
        video, which produced a misleading 'No video stream found' guardrail
        warning even though the input was a perfectly valid audio file."""
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = add_audio(sample_video, sample_audio_wav)

        assert os.path.isfile(result.output_path)
        messages = [str(w.message) for w in caught]
        offending = [m for m in messages if "No video stream" in m or "Could not validate audio mix" in m]
        assert not offending, (
            f"valid audio-only WAV should not trigger a video-stream guardrail warning, got: {offending}"
        )


class TestResize:
    def test_resize_by_dimensions(self, sample_video):
        from mcp_video.engine import resize

        result = resize(sample_video, width=320, height=240)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.width == 320
        assert info.height == 240

    def test_resize_by_aspect_ratio(self, sample_video):
        from mcp_video.engine import resize

        result = resize(sample_video, aspect_ratio="1:1")
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.width == info.height


class TestConvert:
    def test_convert_to_webm(self, sample_video):
        result = convert(sample_video, format="webm")
        assert os.path.isfile(result.output_path)
        assert result.format == "webm"

    def test_convert_to_gif(self, sample_video):
        result = convert(sample_video, format="gif")
        assert os.path.isfile(result.output_path)
        assert result.format == "gif"


class TestSpeed:
    def test_double_speed(self, sample_video):
        result = speed(sample_video, factor=2.0)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        orig = probe(sample_video)
        assert info.duration < orig.duration


class TestThumbnail:
    def test_extract_frame(self, sample_video):
        result = thumbnail(sample_video, timestamp=1.0)
        assert os.path.isfile(result.frame_path)
        assert result.timestamp == 1.0


class TestPreview:
    def test_generate_preview(self, sample_video):
        result = preview(sample_video)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        orig = probe(sample_video)
        assert info.width < orig.width
        assert info.height < orig.height
        assert result.operation == "preview"


class TestStoryboard:
    def test_extract_frames(self, sample_video):
        result = storyboard(sample_video, frame_count=4)
        assert result.count == 4
        for frame in result.frames:
            assert os.path.isfile(frame)


class TestExtractAudio:
    def test_extract_mp3(self, sample_video):
        result = extract_audio(sample_video, format="mp3")
        assert os.path.isfile(result)


class TestSubtitles:
    @requires_filter("subtitles", "Subtitle burn-in")
    def test_burn_subtitles(self, sample_video, tmp_path):
        srt_path = tmp_path / "subs.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nTest subtitle\n")
        result = subtitles(input_path=str(sample_video), subtitle_path=str(srt_path))
        assert os.path.isfile(result.output_path)


class TestProgressCallbacks:
    """Tests for progress callback functionality."""

    def test_parse_ffmpeg_time_parsing(self):
        """Test _parse_ffmpeg_time with various time formats."""
        # Format: HH:MM:SS.xx
        assert _parse_ffmpeg_time("00:00:05.12") == 5.12
        assert _parse_ffmpeg_time("00:01:30.00") == 90.0
        assert _parse_ffmpeg_time("00:00:00.00") == 0.0
        assert _parse_ffmpeg_time("01:00:00.00") == 3600.0
        assert _parse_ffmpeg_time("00:00:59.99") == 59.99

    def test_parse_ffmpeg_time_invalid_format(self):
        """Test _parse_ffmpeg_time with invalid format returns 0.0."""
        assert _parse_ffmpeg_time("invalid") == 0.0
        assert _parse_ffmpeg_time("00:00") == 0.0
        assert _parse_ffmpeg_time("") == 0.0

    def test_run_ffmpeg_with_progress_no_duration(self, sample_video, tmp_path):
        """When estimated_duration is None, should fall back to regular _run_ffmpeg."""
        from mcp_video.engine import _run_ffmpeg_with_progress
        import subprocess

        # Create a simple FFmpeg command
        output = str(tmp_path / "output.mp4")
        args = [
            "-i",
            sample_video,
            "-t",
            "1",
            "-c",
            "copy",
            output,
        ]

        # With estimated_duration=None, on_progress should not be called
        progress_calls = []

        def mock_on_progress(pct):
            progress_calls.append(pct)

        result = _run_ffmpeg_with_progress(args, estimated_duration=None, on_progress=mock_on_progress)
        assert isinstance(result, subprocess.CompletedProcess)
        # Progress callback should not have been called (falls back to regular _run_ffmpeg)
        assert len(progress_calls) == 0

    def test_run_ffmpeg_with_progress_convert(self, sample_video):
        """Use convert with on_progress callback, verify progress reaches 100."""
        progress_values = []

        def track_progress(pct):
            progress_values.append(pct)

        result = convert(sample_video, format="webm", on_progress=track_progress)

        # Verify the conversion succeeded
        assert os.path.isfile(result.output_path)
        assert result.format == "webm"

        # Verify progress was tracked and reached 100
        assert len(progress_values) > 0
        assert 100.0 in progress_values

    def test_run_ffmpeg_with_progress_propagates_callback_failure(self, sample_video, tmp_path):
        """Exceptions from progress callbacks must not disappear in stderr reader threads."""
        from mcp_video.engine import _run_ffmpeg_with_progress

        output = str(tmp_path / "callback_failure.mp4")
        args = [
            "-i",
            sample_video,
            "-t",
            "1",
            "-c",
            "copy",
            output,
        ]

        def fail_on_progress(pct):
            raise RuntimeError(f"progress failed at {pct}")

        with pytest.raises(RuntimeError, match="progress failed"):
            _run_ffmpeg_with_progress(args, estimated_duration=1.0, on_progress=fail_on_progress)

    def test_convert_returns_progress_field(self, sample_video):
        """Verify that convert returns EditResult with progress=100.0."""
        result = convert(sample_video, format="webm")
        assert result.progress == 100.0
        assert result.success is True


class TestThumbnailBase64:
    """Tests for base64 thumbnail generation."""

    def test_generate_thumbnail_base64_valid_video(self, sample_video):
        """Call _generate_thumbnail_base64 on a real video, verify it returns valid base64."""
        import base64

        thumb_b64 = _generate_thumbnail_base64(sample_video)
        assert isinstance(thumb_b64, str)
        assert len(thumb_b64) > 0

        # Verify it's valid base64 by attempting to decode it
        try:
            decoded = base64.b64decode(thumb_b64, validate=True)
            assert len(decoded) > 0
        except Exception as e:
            pytest.fail(f"Failed to decode base64 thumbnail: {e}")

    def test_generate_thumbnail_base64_invalid_path(self):
        """Call with nonexistent path, verify it returns None."""
        result = _generate_thumbnail_base64("/nonexistent/video.mp4")
        assert result is None


class TestReverse:
    def test_reverse_video(self, sample_video):
        result = reverse(sample_video)
        assert result.success is True
        assert result.operation == "reverse"
        assert result.output_path.endswith(".mp4")
        assert os.path.isfile(result.output_path)

    def test_reverse_preserves_duration(self, sample_video):
        original = probe(sample_video)
        result = reverse(sample_video)
        assert abs(result.duration - original.duration) < 0.5


class TestChromaKey:
    def test_chroma_key_default(self, sample_video):
        result = chroma_key(sample_video)
        assert result.success is True
        assert result.operation == "chroma_key"
        assert os.path.isfile(result.output_path)

    def test_chroma_key_custom_color(self, sample_video):
        result = chroma_key(sample_video, color="0xFF0000", similarity=0.05)
        assert result.success is True

    def test_chroma_key_preserves_alpha_with_mov(self, sample_video):
        """MOV output should use prores_ks with alpha channel support."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mov", delete=False) as tmp:
            result = chroma_key(sample_video, output_path=tmp.name)
            assert result.success is True
            assert os.path.isfile(result.output_path)
        os.unlink(tmp.name)


class TestDenoiseFilter:
    def test_denoise_filter(self, sample_video):
        result = apply_filter(sample_video, filter_type="denoise")
        assert result.success is True
        assert result.operation == "filter_denoise"
        assert os.path.isfile(result.output_path)


class TestDeinterlaceFilter:
    def test_deinterlace_filter(self, sample_video):
        result = apply_filter(sample_video, filter_type="deinterlace")
        assert result.success is True
        assert result.operation == "filter_deinterlace"
        assert os.path.isfile(result.output_path)


class TestHlsValidation:
    def test_hls_rejects_unknown_quality_before_probe(self, sample_video, monkeypatch):
        from mcp_video import engine_hls
        from mcp_video.errors import MCPVideoError

        monkeypatch.setattr(
            engine_hls, "probe", lambda _path: (_ for _ in ()).throw(AssertionError("probe should not run"))
        )

        with pytest.raises(MCPVideoError, match="qualities"):
            engine_hls.hls_segment(sample_video, qualities=["high", "cinema"])

    def test_hls_rejects_non_positive_segment_duration_before_probe(self, sample_video, monkeypatch):
        from mcp_video import engine_hls
        from mcp_video.errors import MCPVideoError

        monkeypatch.setattr(
            engine_hls, "probe", lambda _path: (_ for _ in ()).throw(AssertionError("probe should not run"))
        )

        with pytest.raises(MCPVideoError, match="segment_duration"):
            engine_hls.hls_segment(sample_video, segment_duration=0)

    @pytest.mark.parametrize(
        "malicious_playlist",
        [
            "../../etc/cron.d/evil",
            "/etc/cron.d/evil",
            "../sibling/escape.m3u8",
        ],
    )
    def test_hls_rejects_playlist_name_escape_output_dir(self, sample_video, monkeypatch, tmp_path, malicious_playlist):
        from mcp_video import engine_hls
        from mcp_video.errors import MCPVideoError

        # The traversal check runs after probe; stub it so no ffprobe call is needed.
        monkeypatch.setattr(engine_hls, "probe", lambda _path: None)

        output_dir = tmp_path / "hls_out"
        with pytest.raises(MCPVideoError, match="escape output_dir") as exc:
            engine_hls.hls_segment(
                sample_video,
                output_dir=str(output_dir),
                playlist_name=malicious_playlist,
            )
        assert exc.value.code == "invalid_output_path"


class TestConvertValidation:
    def test_convert_rejects_invalid_quality_before_probe(self, sample_video, monkeypatch):
        from mcp_video import engine_convert
        from mcp_video.errors import MCPVideoError

        monkeypatch.setattr(
            engine_convert, "probe", lambda _path: (_ for _ in ()).throw(AssertionError("probe should not run"))
        )

        with pytest.raises(MCPVideoError, match="quality"):
            engine_convert.convert(sample_video, format="mp4", quality="medium-rare")

    def test_convert_rejects_invalid_format_before_probe(self, sample_video, monkeypatch):
        from mcp_video import engine_convert
        from mcp_video.errors import MCPVideoError

        monkeypatch.setattr(
            engine_convert, "probe", lambda _path: (_ for _ in ()).throw(AssertionError("probe should not run"))
        )

        with pytest.raises(MCPVideoError, match="format"):
            engine_convert.convert(sample_video, format="exe", quality="high")


class TestGifQualityScaling:
    def test_gif_low_quality_is_smaller(self, sample_video):
        low = convert(sample_video, format="gif", quality="low")
        high = convert(sample_video, format="gif", quality="high")
        # Low quality GIF should be smaller (320px wide vs 640px)
        assert low.success is True
        assert high.success is True
        if low.size_mb and high.size_mb:
            assert low.size_mb <= high.size_mb


class TestBatchOutputDirValidation:
    def test_batch_output_dir_file_path_returns_structured_failures(self, sample_video, tmp_path):
        from mcp_video.engine import video_batch

        output_file = tmp_path / "not_a_dir"
        output_file.write_text("not a directory")

        result = video_batch(
            [sample_video],
            operation="trim",
            params={"start": "0", "duration": "1"},
            output_dir=str(output_file),
        )

        assert result["success"] is False
        assert result["failed"] == 1
        assert result["results"][0]["success"] is False

    def test_batch_unknown_operation_rejected_before_input_validation(self):
        from mcp_video.engine import video_batch

        with pytest.raises(MCPVideoError, match="Unknown operation"):
            video_batch(["/tmp/missing.mp4"], operation="nonexistent")

    def test_batch_rejects_invalid_output_dir(self, sample_video):
        from mcp_video.engine import video_batch

        with pytest.raises(MCPVideoError, match="Output path contains null bytes"):
            video_batch(
                [sample_video], operation="trim", params={"start": "0", "duration": "1"}, output_dir="bad\x00dir"
            )


# ---------------------------------------------------------------------------
# Tests for extracted helpers (deepening candidates 2 & 3)
# ---------------------------------------------------------------------------


class TestBuildAudioFilters:
    def test_no_filters(self):
        from mcp_video.engine_audio_ops import _build_audio_filters

        assert _build_audio_filters(1.0, 0.0, 0.0, 10.0) == []

    def test_volume_only(self):
        from mcp_video.engine_audio_ops import _build_audio_filters

        filters = _build_audio_filters(0.5, 0.0, 0.0, 10.0)
        assert len(filters) == 1
        assert "volume=0.5" in filters[0]

    def test_fade_in_only(self):
        from mcp_video.engine_audio_ops import _build_audio_filters

        filters = _build_audio_filters(1.0, 2.0, 0.0, 10.0)
        assert len(filters) == 1
        assert "afade=t=in:st=0:d=2.0" in filters[0]

    def test_fade_out_only(self):
        from mcp_video.engine_audio_ops import _build_audio_filters

        filters = _build_audio_filters(1.0, 0.0, 3.0, 10.0)
        assert len(filters) == 1
        assert "afade=t=out:st=7.0:d=3.0" in filters[0]

    def test_fade_out_clamped_to_zero(self):
        from mcp_video.engine_audio_ops import _build_audio_filters

        filters = _build_audio_filters(1.0, 0.0, 5.0, 3.0)
        assert len(filters) == 1
        assert "afade=t=out:st=0.0:d=5.0" in filters[0]

    def test_all_filters(self):
        from mcp_video.engine_audio_ops import _build_audio_filters

        filters = _build_audio_filters(0.8, 1.0, 2.0, 10.0)
        assert len(filters) == 3
        assert any("volume" in f for f in filters)
        assert any("afade=t=in" in f for f in filters)
        assert any("afade=t=out" in f for f in filters)


class TestBuildAddAudioArgs:
    def test_replace_without_filters_or_start(self):
        from mcp_video.engine_audio_ops import _build_add_audio_args

        args = _build_add_audio_args("vid.mp4", "aud.wav", [], False, None, True, "out.mp4")
        assert "-i" in args
        assert "-map" in args
        assert "-shortest" in args
        assert "-af" not in args

    def test_replace_with_start_time(self):
        from mcp_video.engine_audio_ops import _build_add_audio_args

        args = _build_add_audio_args("vid.mp4", "aud.wav", [], False, 1.5, True, "out.mp4")
        assert "-filter_complex" in args
        fc_idx = args.index("-filter_complex")
        assert "adelay=1500|1500" in args[fc_idx + 1]

    def test_replace_with_filters(self):
        from mcp_video.engine_audio_ops import _build_add_audio_args

        args = _build_add_audio_args("vid.mp4", "aud.wav", ["volume=0.5"], False, None, True, "out.mp4")
        idx = args.index("-af")
        assert args[idx + 1] == "volume=0.5"

    def test_mix_with_source_audio(self):
        from mcp_video.engine_audio_ops import _build_add_audio_args

        args = _build_add_audio_args("vid.mp4", "aud.wav", ["volume=0.5"], True, None, True, "out.mp4")
        assert "-filter_complex" in args
        fc_idx = args.index("-filter_complex")
        fc = args[fc_idx + 1]
        assert "amix=inputs=2" in fc
        assert "[aout]" in fc
        assert "-map" in args

    def test_mix_without_source_audio_uses_replace_branch(self):
        from mcp_video.engine_audio_ops import _build_add_audio_args

        args = _build_add_audio_args("vid.mp4", "aud.wav", [], True, None, False, "out.mp4")
        # When mix=True but no source audio, _build_add_audio_args takes the replace branch
        assert "-filter_complex" not in args
        assert "-map" in args
        assert "-shortest" in args


class TestNormalizeClips:
    def test_normalize_calls_ffmpeg_with_correct_filter(self, monkeypatch, tmp_path):
        from mcp_video.engine_merge import _normalize_clips

        calls = []

        def fake_run_ffmpeg(cmd):
            calls.append(cmd)

        monkeypatch.setattr("mcp_video.engine_merge._run_ffmpeg", fake_run_ffmpeg)

        # Create a fake info object with required attributes
        class FakeInfo:
            rotation = 0

        infos = [FakeInfo()]
        clips = [str(tmp_path / "clip.mp4")]
        result = _normalize_clips(clips, infos, 640, 480, str(tmp_path))

        assert len(calls) == 1
        cmd = calls[0]
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        assert "scale=640:480" in vf
        assert "pad=640:480" in vf
        assert len(result) == 1

    def test_normalize_applies_transpose_for_rotation(self, monkeypatch, tmp_path):
        from mcp_video.engine_merge import _normalize_clips

        calls = []

        def fake_run_ffmpeg(cmd):
            calls.append(cmd)

        monkeypatch.setattr("mcp_video.engine_merge._run_ffmpeg", fake_run_ffmpeg)

        class FakeInfo90:
            rotation = 90

        class FakeInfo270:
            rotation = 270

        infos = [FakeInfo90(), FakeInfo270()]
        clips = [str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")]
        _normalize_clips(clips, infos, 640, 480, str(tmp_path))

        assert len(calls) == 2
        assert "transpose=2" in calls[0][calls[0].index("-vf") + 1]
        assert "transpose=1" in calls[1][calls[1].index("-vf") + 1]


class TestMergeSingleClip:
    def test_copy_same_extension(self, sample_video, tmp_path, monkeypatch):
        from mcp_video.engine_merge import _merge_single_clip

        copy_calls = []
        monkeypatch.setattr("mcp_video.engine_merge.shutil.copy2", lambda s, d: copy_calls.append((s, d)))
        monkeypatch.setattr("mcp_video.engine_merge._run_ffmpeg", lambda cmd: None)

        # Patch probe so it doesn't need the output file to exist
        class FakeInfo:
            duration = 1.0
            resolution = "640x480"
            size_mb = 0.1

        monkeypatch.setattr("mcp_video.engine_merge.probe", lambda p: FakeInfo())
        monkeypatch.setattr("mcp_video.engine_probe.probe", lambda p: FakeInfo())

        result = _merge_single_clip(sample_video, str(tmp_path / "out.mp4"))
        assert len(copy_calls) == 1
        assert result.operation == "merge"

    def test_remux_different_extension(self, sample_video, tmp_path, monkeypatch):
        from mcp_video.engine_merge import _merge_single_clip

        ffmpeg_calls = []
        monkeypatch.setattr("mcp_video.engine_merge.shutil.copy2", lambda s, d: None)
        monkeypatch.setattr("mcp_video.engine_merge._run_ffmpeg", lambda cmd: ffmpeg_calls.append(cmd))

        class FakeInfo:
            duration = 1.0
            resolution = "640x480"
            size_mb = 0.1

        monkeypatch.setattr("mcp_video.engine_merge.probe", lambda p: FakeInfo())
        monkeypatch.setattr("mcp_video.engine_probe.probe", lambda p: FakeInfo())

        _merge_single_clip(sample_video, str(tmp_path / "out.mkv"))
        assert len(ffmpeg_calls) == 1
        assert "-c" in ffmpeg_calls[0]
        assert "copy" in ffmpeg_calls[0]


class TestTrimEndSemantics:
    """``end`` is an absolute source timestamp, not a duration.

    ``sample_video`` is 3s. With ``start=1``, an absolute ``end=2`` yields a 1s
    clip, while treating ``end`` as a duration yields 2s -- so these cases
    distinguish the two readings without being clipped by the source length.
    The pre-existing ``test_trim_by_end`` uses ``start=0``, where both readings
    agree, which is why this regression went unnoticed.
    """

    def test_end_is_absolute_when_start_is_nonzero(self, sample_video, tmp_path):
        out = str(tmp_path / "by_end.mp4")
        trim(sample_video, start="1", end="2", output_path=out)
        assert abs(probe(out).duration - 1.0) < 0.25

    def test_end_matches_equivalent_duration(self, sample_video, tmp_path):
        by_end = str(tmp_path / "by_end.mp4")
        by_duration = str(tmp_path / "by_duration.mp4")
        trim(sample_video, start="1", end="2", output_path=by_end)
        trim(sample_video, start="1", duration="1", output_path=by_duration)
        assert abs(probe(by_end).duration - probe(by_duration).duration) < 0.25

    def test_end_is_absolute_in_accurate_mode(self, sample_video, tmp_path):
        out = str(tmp_path / "accurate.mp4")
        trim(sample_video, start="1", end="2", output_path=out, accurate=True)
        assert abs(probe(out).duration - 1.0) < 0.25

    def test_end_before_start_is_rejected(self, sample_video):
        with pytest.raises(MCPVideoError):
            trim(sample_video, start="2", end="1")


class TestTrimEndFFmpegArgs:
    """Argument-level contract for ``end``. Does not require FFmpeg."""

    @staticmethod
    def _capture_trim(monkeypatch, tmp_path, **kwargs):
        from kinocut import engine_edit

        source = tmp_path / "in.mp4"
        source.write_bytes(b"\x00")
        calls: list[list[str]] = []
        monkeypatch.setattr(engine_edit, "_run_ffmpeg", lambda cmd: calls.append(cmd))
        monkeypatch.setattr(engine_edit, "_build_edit_result", lambda *a, **k: None)
        engine_edit.trim(
            str(source), output_path=str(tmp_path / "out.mp4"), **kwargs
        )
        return calls[0]

    def test_input_seeking_converts_end_to_duration(self, monkeypatch, tmp_path):
        # -ss before -i rebases output timestamps to zero, so a trailing -to
        # would be measured from the seek point and act as a duration.
        cmd = self._capture_trim(monkeypatch, tmp_path, start="5", end="10")
        assert "-to" not in cmd
        assert "-t" in cmd
        assert float(cmd[cmd.index("-t") + 1]) == pytest.approx(5.0)

    def test_output_seeking_keeps_end_absolute(self, monkeypatch, tmp_path):
        # -ss after -i preserves source timestamps, so -to is already absolute.
        cmd = self._capture_trim(
            monkeypatch, tmp_path, start="5", end="10", accurate=True
        )
        assert "-to" in cmd
        assert cmd[cmd.index("-to") + 1] == "10"

    def test_explicit_duration_is_passed_through(self, monkeypatch, tmp_path):
        cmd = self._capture_trim(monkeypatch, tmp_path, start="5", duration="10")
        assert cmd[cmd.index("-t") + 1] == "10"
        assert "-to" not in cmd

    def test_end_without_start_still_equals_end(self, monkeypatch, tmp_path):
        cmd = self._capture_trim(monkeypatch, tmp_path, end="10")
        assert float(cmd[cmd.index("-t") + 1]) == pytest.approx(10.0)
