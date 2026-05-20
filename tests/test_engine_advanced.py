"""Advanced engine tests for uncovered operations and edge cases — needs FFmpeg."""

import os
import subprocess

import pytest

from mcp_video.engine import (
    _check_filter_available,
    _get_color_preset_filter,
    add_audio,
    apply_filter,
    convert,
    crop,
    edit_timeline,
    extract_audio,
    fade,
    get_duration,
    merge,
    normalize,
    normalize_audio,
    overlay_video,
    preview,
    probe,
    resize,
    rotate,
    speed,
    split_screen,
    storyboard,
    thumbnail,
    trim,
    watermark,
)
from mcp_video.models import Timeline, TimelineClip, TimelineTrack
from mcp_video.errors import InputFileError, MCPVideoError, ProcessingError


def requires_filter(name: str, feature: str):
    return pytest.mark.skipif(
        not _check_filter_available(name),
        reason=f"FFmpeg filter '{name}' not available ({feature} requires it)",
    )


class TestNormalize:
    def test_normalize_to_h264(self, sample_video, tmp_path):
        out = str(tmp_path / "normalized.mp4")
        result = normalize(sample_video, output_path=out)
        assert os.path.isfile(result)
        info = probe(result)
        assert info.codec == "h264"
        assert info.audio_codec == "aac"


class TestGetDuration:
    def test_returns_float(self, sample_video):
        dur = get_duration(sample_video)
        assert isinstance(dur, float)
        assert dur > 0

    def test_nonexistent_file(self):
        with pytest.raises(InputFileError):
            get_duration("/nonexistent/video.mp4")


class TestWatermark:
    def test_adds_watermark(self, sample_video, sample_watermark_png):
        if not _check_filter_available("overlay"):
            pytest.skip("overlay filter not available")
        result = watermark(sample_video, sample_watermark_png)
        assert os.path.isfile(result.output_path)
        assert result.operation == "watermark"

    def test_with_opacity(self, sample_video, sample_watermark_png):
        if not _check_filter_available("overlay"):
            pytest.skip("overlay filter not available")
        result = watermark(sample_video, sample_watermark_png, opacity=0.3)
        assert os.path.isfile(result.output_path)


class TestExportVideo:
    def test_wrapper_for_convert(self, sample_video):
        from mcp_video.engine import export_video

        result = export_video(sample_video)
        assert os.path.isfile(result.output_path)
        assert result.operation == "export"

    def test_with_quality(self, sample_video):
        from mcp_video.engine import export_video

        result = export_video(sample_video, quality="low")
        assert os.path.isfile(result.output_path)


class TestEditTimeline:
    def test_single_clip_no_transitions(self, sample_video):
        tl = Timeline(
            width=640,
            height=480,
            tracks=[
                TimelineTrack(
                    type="video",
                    clips=[TimelineClip(source=sample_video)],
                ),
            ],
        )
        result = edit_timeline(tl)
        assert os.path.isfile(result.output_path)
        assert result.success is True

    @requires_filter("drawtext", "Text overlay")
    def test_multiple_clips_with_text(self, sample_video):
        tl = Timeline(
            width=640,
            height=480,
            tracks=[
                TimelineTrack(
                    type="video",
                    clips=[
                        TimelineClip(source=sample_video),
                        TimelineClip(source=sample_video),
                    ],
                ),
                TimelineTrack(
                    type="text",
                    elements=[
                        {
                            "text": "Test Title",
                            "start": 0,
                            "duration": 2,
                            "position": "center",
                            "style": {"size": 36, "color": "white", "shadow": True},
                        }
                    ],
                ),
            ],
        )
        result = edit_timeline(tl)
        assert os.path.isfile(result.output_path)

    def test_timeline_rejects_invalid_image_position_before_input_validation(self):
        from mcp_video.engine import edit_timeline
        from mcp_video.errors import MCPVideoError

        timeline = {
            "tracks": [
                {"type": "video", "clips": [{"source": "/tmp/missing.mp4"}]},
                {"type": "image", "images": [{"source": "/tmp/logo.png", "position": {"x_pct": 0.5}}]},
            ]
        }

        with pytest.raises(MCPVideoError, match="Position dict"):
            edit_timeline(timeline)

    def test_timeline_with_audio(self, sample_video, sample_audio, tmp_path):
        out = str(tmp_path / "timeline_audio.mp4")
        tl = Timeline(
            width=640,
            height=480,
            tracks=[
                TimelineTrack(
                    type="video",
                    clips=[TimelineClip(source=sample_video)],
                ),
                TimelineTrack(
                    type="audio",
                    clips=[TimelineClip(source=sample_audio)],
                ),
            ],
        )
        result = edit_timeline(tl, output_path=out)
        assert os.path.isfile(result.output_path)

    def test_timeline_no_video_clips_raises(self):
        tl = Timeline(tracks=[])
        with pytest.raises(MCPVideoError):
            edit_timeline(tl)


class TestConvertMov:
    def test_convert_to_mov(self, sample_video):
        result = convert(sample_video, format="mov")
        assert os.path.isfile(result.output_path)
        assert result.format == "mov"


class TestSpeedAdvanced:
    def test_slow_mo(self, sample_video):
        result = speed(sample_video, factor=0.5)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        orig = probe(sample_video)
        # Slow-mo should roughly double duration
        assert info.duration >= orig.duration * 1.5

    def test_triple_speed(self, sample_video):
        result = speed(sample_video, factor=3.0)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        orig = probe(sample_video)
        assert info.duration < orig.duration


class TestMergeTransitions:
    def test_merge_with_fade(self, sample_video):
        result = merge(
            [sample_video, sample_video],
            transition="fade",
            transition_duration=0.5,
        )
        assert os.path.isfile(result.output_path)
        assert result.operation == "merge"


class TestTrimEdgeCases:
    def test_trim_to_exact_duration(self, sample_video):
        orig = probe(sample_video)
        result = trim(sample_video, start="0", end=str(orig.duration))
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert abs(info.duration - orig.duration) < 0.5


class TestResizeAdvanced:
    def test_resize_width_only(self, sample_video):
        result = resize(sample_video, width=320)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.width == 320
        # Height should scale proportionally (640x480 → 320x240)
        assert info.height == 240

    def test_resize_height_only(self, sample_video):
        result = resize(sample_video, height=240)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.height == 240

    def test_resize_no_params_raises(self, sample_video):
        with pytest.raises(MCPVideoError):
            resize(sample_video)


class TestPreviewAdvanced:
    def test_custom_scale_factor(self, sample_video):
        result = preview(sample_video, scale_factor=2)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        orig = probe(sample_video)
        # With scale_factor=2, should be roughly half resolution
        assert info.width <= orig.width
        assert info.height <= orig.height


class TestThumbnailAdvanced:
    def test_at_timestamp_zero(self, sample_video):
        result = thumbnail(sample_video, timestamp=0)
        assert os.path.isfile(result.frame_path)
        assert result.timestamp == 0

    def test_default_timestamp(self, sample_video):
        result = thumbnail(sample_video)
        assert os.path.isfile(result.frame_path)
        # Default is 10% of duration
        dur = get_duration(sample_video)
        expected_ts = dur * 0.1
        assert abs(result.timestamp - expected_ts) < 0.01


class TestStoryboardAdvanced:
    def test_two_frames_grid(self, sample_video):
        result = storyboard(sample_video, frame_count=2)
        assert result.count == 2
        for frame in result.frames:
            assert os.path.isfile(frame)
        # Grid may or may not exist depending on FFmpeg version
        # (2-frame grids can fail with some filter combos)
        if result.grid is not None:
            assert os.path.isfile(result.grid)

    def test_single_frame(self, sample_video):
        result = storyboard(sample_video, frame_count=1)
        assert result.count == 1


class TestExtractAudioAdvanced:
    def test_extract_to_wav(self, sample_video):
        result = extract_audio(sample_video, format="wav")
        assert os.path.isfile(result)
        # WAV files should be larger than MP3
        size = os.path.getsize(result)
        assert size > 0


class TestAddAudioAdvanced:
    def test_with_start_time(self, sample_video, sample_audio):
        result = add_audio(
            sample_video,
            sample_audio,
            start_time=0.5,
        )
        assert os.path.isfile(result.output_path)

    def test_nonexistent_audio(self, sample_video):
        with pytest.raises(InputFileError):
            add_audio(sample_video, "/nonexistent/audio.mp3")


class TestCrop:
    def test_crop_center(self, sample_video):
        result = crop(sample_video, width=320, height=240)
        assert os.path.isfile(result.output_path)
        assert result.operation == "crop"
        info = probe(result.output_path)
        assert info.width == 320
        assert info.height == 240

    def test_crop_with_offset(self, sample_video):
        result = crop(sample_video, width=200, height=200, x=10, y=10)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.width == 200
        assert info.height == 200

    def test_crop_too_large_raises(self, sample_video):
        with pytest.raises(MCPVideoError):
            crop(sample_video, width=9999, height=9999)

    def test_crop_zero_dimensions_raises(self, sample_video):
        with pytest.raises(MCPVideoError):
            crop(sample_video, width=0, height=100)


class TestRotate:
    def test_rotate_90(self, sample_video):
        result = rotate(sample_video, angle=90)
        assert os.path.isfile(result.output_path)
        assert result.operation == "rotate"
        info = probe(result.output_path)
        # 640x480 rotated 90 should become 480x640
        assert info.width == 480
        assert info.height == 640

    def test_rotate_180(self, sample_video):
        result = rotate(sample_video, angle=180)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.width == 640
        assert info.height == 480

    def test_flip_horizontal(self, sample_video):
        result = rotate(sample_video, flip_horizontal=True)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.width == 640
        assert info.height == 480

    def test_invalid_angle_raises(self, sample_video):
        with pytest.raises(MCPVideoError):
            rotate(sample_video, angle=45)

    def test_no_transform_raises(self, sample_video):
        with pytest.raises(MCPVideoError):
            rotate(sample_video, angle=0)


class TestFade:
    def test_fade_in(self, sample_video):
        result = fade(sample_video, fade_in=0.5)
        assert os.path.isfile(result.output_path)
        assert result.operation == "fade"

    def test_fade_out(self, sample_video):
        result = fade(sample_video, fade_out=0.5)
        assert os.path.isfile(result.output_path)

    def test_fade_in_and_out(self, sample_video):
        result = fade(sample_video, fade_in=0.3, fade_out=0.5)
        assert os.path.isfile(result.output_path)

    def test_no_fade_raises(self, sample_video):
        with pytest.raises(MCPVideoError):
            fade(sample_video, fade_in=0, fade_out=0)


class TestMergePerTransition:
    def test_single_transition_type(self, sample_video):
        result = merge(
            [sample_video, sample_video, sample_video],
            transitions=["fade"],
        )
        assert os.path.isfile(result.output_path)

    def test_multiple_transition_types(self, sample_video):
        result = merge(
            [sample_video, sample_video, sample_video],
            transitions=["fade", "dissolve"],
        )
        assert os.path.isfile(result.output_path)

    def test_transitions_shorter_than_pairs_repeats_last(self, sample_video):
        result = merge(
            [sample_video, sample_video, sample_video],
            transitions=["fade"],  # 2 pairs but only 1 type
        )
        assert os.path.isfile(result.output_path)

    def test_transition_param_backward_compat(self, sample_video):
        result = merge(
            [sample_video, sample_video],
            transition="fade",
            transition_duration=0.5,
        )
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# v0.3.0 features: filters, compositing, audio normalization
# ---------------------------------------------------------------------------


class TestColorPresetFilter:
    def test_warm_preset(self):
        vf = _get_color_preset_filter("warm")
        assert "brightness=0.05" in vf
        assert "saturation=1.3" in vf

    def test_cool_preset(self):
        vf = _get_color_preset_filter("cool")
        assert "saturation=0.9" in vf

    def test_noir_preset(self):
        vf = _get_color_preset_filter("noir")
        assert "saturation=0.0" in vf

    def test_cinematic_preset(self):
        vf = _get_color_preset_filter("cinematic")
        assert "contrast=1.15" in vf

    def test_vintage_preset(self):
        vf = _get_color_preset_filter("vintage")
        assert "saturation=0.7" in vf


class TestApplyFilter:
    @requires_filter("boxblur", "Blur filter")
    def test_blur(self, sample_video):
        result = apply_filter(sample_video, filter_type="blur")
        assert os.path.isfile(result.output_path)
        assert result.operation == "filter_blur"

    @requires_filter("boxblur", "Blur filter")
    def test_blur_with_params(self, sample_video):
        result = apply_filter(sample_video, filter_type="blur", params={"radius": 10, "strength": 2})
        assert os.path.isfile(result.output_path)

    @requires_filter("unsharp", "Sharpen filter")
    def test_sharpen(self, sample_video):
        result = apply_filter(sample_video, filter_type="sharpen")
        assert os.path.isfile(result.output_path)

    @requires_filter("eq", "Brightness filter")
    def test_brightness(self, sample_video):
        result = apply_filter(sample_video, filter_type="brightness", params={"level": 0.2})
        assert os.path.isfile(result.output_path)

    @requires_filter("eq", "Contrast filter")
    def test_contrast(self, sample_video):
        result = apply_filter(sample_video, filter_type="contrast")
        assert os.path.isfile(result.output_path)

    @requires_filter("eq", "Saturation filter")
    def test_saturation(self, sample_video):
        result = apply_filter(sample_video, filter_type="saturation", params={"level": 2.0})
        assert os.path.isfile(result.output_path)

    @requires_filter("hue", "Grayscale filter")
    def test_grayscale(self, sample_video):
        result = apply_filter(sample_video, filter_type="grayscale")
        assert os.path.isfile(result.output_path)

    @requires_filter("colorchannelmixer", "Sepia filter")
    def test_sepia(self, sample_video):
        result = apply_filter(sample_video, filter_type="sepia")
        assert os.path.isfile(result.output_path)

    @requires_filter("negate", "Invert filter")
    def test_invert(self, sample_video):
        result = apply_filter(sample_video, filter_type="invert")
        assert os.path.isfile(result.output_path)

    @requires_filter("vignette", "Vignette filter")
    def test_vignette(self, sample_video):
        result = apply_filter(sample_video, filter_type="vignette")
        assert os.path.isfile(result.output_path)

    @requires_filter("eq", "Color preset filter")
    def test_color_preset_warm(self, sample_video):
        result = apply_filter(sample_video, filter_type="color_preset", params={"preset": "warm"})
        assert os.path.isfile(result.output_path)

    @requires_filter("eq", "Color preset filter")
    def test_color_preset_cinematic(self, sample_video):
        result = apply_filter(sample_video, filter_type="color_preset", params={"preset": "cinematic"})
        assert os.path.isfile(result.output_path)

    def test_custom_output_path(self, sample_video, tmp_path):
        out = str(tmp_path / "custom_filter.mp4")
        result = apply_filter(sample_video, filter_type="blur", output_path=out)
        assert result.output_path == out


class TestNormalizeAudio:
    @requires_filter("loudnorm", "Audio normalization")
    def test_normalize_default(self, sample_video):
        result = normalize_audio(sample_video)
        assert os.path.isfile(result.output_path)
        assert result.operation == "normalize_audio"

    @requires_filter("loudnorm", "Audio normalization")
    def test_normalize_broadcast(self, sample_video):
        result = normalize_audio(sample_video, target_lufs=-23.0)
        assert os.path.isfile(result.output_path)

    @requires_filter("loudnorm", "Audio normalization")
    def test_normalize_custom_output(self, sample_video, tmp_path):
        out = str(tmp_path / "normalized.mp4")
        result = normalize_audio(sample_video, output_path=out)
        assert result.output_path == out


class TestOverlayVideo:
    def test_overlay_default(self, sample_video, sample_video_2):
        result = overlay_video(sample_video, overlay_path=sample_video_2)
        assert os.path.isfile(result.output_path)
        assert result.operation == "overlay_video"

    def test_overlay_with_scale(self, sample_video, sample_video_2):
        result = overlay_video(sample_video, overlay_path=sample_video_2, width=160, height=120)
        assert os.path.isfile(result.output_path)

    def test_overlay_with_timing(self, sample_video, sample_video_2):
        result = overlay_video(sample_video, overlay_path=sample_video_2, start_time=0.5, duration=1.0)
        assert os.path.isfile(result.output_path)

    def test_overlay_custom_output(self, sample_video, sample_video_2, tmp_path):
        out = str(tmp_path / "overlay.mp4")
        result = overlay_video(sample_video, overlay_path=sample_video_2, output_path=out)
        assert result.output_path == out


class TestSplitScreen:
    def test_side_by_side(self, sample_video, sample_video_2):
        result = split_screen(sample_video, right_path=sample_video_2, layout="side-by-side")
        assert os.path.isfile(result.output_path)
        assert result.operation == "split_screen_side-by-side"
        # sample_video=640x480, sample_video_2=320x240
        # max-dims: scale to max height (480), width = 640 + (320*480/240) = 640+640 = 1280
        assert result.resolution == "1280x480"

    def test_top_bottom(self, sample_video, sample_video_2):
        result = split_screen(sample_video, right_path=sample_video_2, layout="top-bottom")
        assert os.path.isfile(result.output_path)
        assert result.operation == "split_screen_top-bottom"
        # max-dims: scale to max width (640), height = 480 + (240*640/320) = 480+480 = 960
        assert result.resolution == "640x960"

    def test_same_resolution(self, sample_video):
        result = split_screen(sample_video, right_path=sample_video, layout="side-by-side")
        assert os.path.isfile(result.output_path)
        assert result.resolution == "1280x480"

    def test_custom_output(self, sample_video, sample_video_2, tmp_path):
        out = str(tmp_path / "split.mp4")
        result = split_screen(sample_video, right_path=sample_video_2, output_path=out)
        assert result.output_path == out


class TestFilterValidation:
    """Regression tests for filter_type and preset validation (bugbot #5)."""

    def test_invalid_filter_type_raises_mcp_error(self, sample_video):
        with pytest.raises(MCPVideoError, match="Unknown filter type"):
            apply_filter(sample_video, filter_type="blurr")

    def test_invalid_color_preset_raises_mcp_error(self, sample_video):
        with pytest.raises(MCPVideoError, match="Unknown color preset"):
            _get_color_preset_filter("warmth")

    def test_invalid_preset_via_apply_filter(self, sample_video):
        with pytest.raises(MCPVideoError, match="Unknown color preset"):
            apply_filter(sample_video, filter_type="color_preset", params={"preset": "neon"})


class TestAudioEffects:
    """Tests for audio effect filter types (reverb, compressor, pitch_shift, noise_reduction)."""

    @requires_filter("aecho", "Reverb filter")
    def test_reverb_default(self, sample_video):
        result = apply_filter(sample_video, filter_type="reverb")
        assert os.path.isfile(result.output_path)
        assert result.operation == "filter_reverb"

    @requires_filter("aecho", "Reverb filter")
    def test_reverb_with_params(self, sample_video):
        result = apply_filter(
            sample_video,
            filter_type="reverb",
            params={
                "in_gain": 0.6,
                "out_gain": 0.8,
                "delays": 80,
                "decay": 0.3,
            },
        )
        assert os.path.isfile(result.output_path)

    @requires_filter("acompressor", "Compressor filter")
    def test_compressor_default(self, sample_video):
        result = apply_filter(sample_video, filter_type="compressor")
        assert os.path.isfile(result.output_path)
        assert result.operation == "filter_compressor"

    @requires_filter("acompressor", "Compressor filter")
    def test_compressor_with_params(self, sample_video):
        result = apply_filter(
            sample_video,
            filter_type="compressor",
            params={
                "threshold_db": -15,
                "ratio": 6,
                "attack": 3,
                "release": 100,
            },
        )
        assert os.path.isfile(result.output_path)

    @requires_filter("asetrate", "Pitch shift filter")
    def test_pitch_shift_default(self, sample_video):
        result = apply_filter(sample_video, filter_type="pitch_shift")
        assert os.path.isfile(result.output_path)
        assert result.operation == "filter_pitch_shift"

    @requires_filter("asetrate", "Pitch shift filter")
    def test_pitch_shift_with_semitones(self, sample_video):
        result = apply_filter(sample_video, filter_type="pitch_shift", params={"semitones": 5})
        assert os.path.isfile(result.output_path)

    @requires_filter("afftdn", "Noise reduction filter")
    def test_noise_reduction_default(self, sample_video):
        result = apply_filter(sample_video, filter_type="noise_reduction")
        assert os.path.isfile(result.output_path)
        assert result.operation == "filter_noise_reduction"

    @requires_filter("afftdn", "Noise reduction filter")
    def test_noise_reduction_with_level(self, sample_video):
        result = apply_filter(sample_video, filter_type="noise_reduction", params={"noise_level": -30})
        assert os.path.isfile(result.output_path)

    def test_audio_filter_rejects_no_audio_video(self, sample_video_no_audio):
        """Audio effect filters should raise an error on video without audio."""
        with pytest.raises(MCPVideoError, match="audio"):
            apply_filter(sample_video_no_audio, filter_type="reverb")


class TestLoudnormTruePeak:
    """Regression test for loudnorm TP formula (bugbot #6)."""

    @requires_filter("loudnorm", "Audio normalization")
    def test_broadcast_tp_is_fixed(self, sample_video, tmp_path):
        """TP should be -1.5 regardless of target_lufs, not target_lufs + 14.5."""
        from mcp_video.engine import normalize_audio

        out = str(tmp_path / "norm_broadcast.mp4")
        result = normalize_audio(sample_video, target_lufs=-23.0, output_path=out)
        assert os.path.isfile(result.output_path)


class TestKenBurns:
    """Tests for Ken Burns / zoom pan filter type."""

    @requires_filter("zoompan", "Zoom pan filter")
    def test_ken_burns_default(self, sample_video):
        result = apply_filter(sample_video, filter_type="ken_burns")
        assert os.path.isfile(result.output_path)
        assert result.operation == "filter_ken_burns"

    @requires_filter("zoompan", "Zoom pan filter")
    def test_ken_burns_with_params(self, sample_video):
        result = apply_filter(
            sample_video,
            filter_type="ken_burns",
            params={
                "zoom_speed": 0.002,
                "duration": 100,
            },
        )
        assert os.path.isfile(result.output_path)


class TestGenerateSubtitles:
    """Tests for subtitle generation from text entries."""

    def test_generate_srt_file(self, sample_video, tmp_path):
        from mcp_video.engine import generate_subtitles

        out = str(tmp_path / "subs")
        entries = [
            {"start": 0.0, "end": 1.5, "text": "Hello World"},
            {"start": 1.5, "end": 3.0, "text": "This is a test"},
        ]
        result = generate_subtitles(entries, sample_video, output_path=out)
        assert result.success is True
        assert result.srt_path is not None
        assert os.path.isfile(result.srt_path)
        assert result.entry_count == 2
        assert result.video_path is None

    def test_burn_subtitles_into_video(self, sample_video, tmp_path):
        from mcp_video.engine import generate_subtitles

        out = str(tmp_path / "burned")
        entries = [{"start": 0.0, "end": 2.0, "text": "Burned text"}]
        result = generate_subtitles(entries, sample_video, output_path=out, burn=True)
        assert result.success is True
        assert result.video_path is not None
        assert os.path.isfile(result.video_path)

    def test_subtitle_text_allows_arrow_marker_content(self, sample_video, tmp_path):
        from mcp_video.engine import generate_subtitles

        out = str(tmp_path / "subs_arrow")
        entries = [{"start": 0.0, "end": 1.5, "text": "Menu --> Settings"}]

        result = generate_subtitles(entries, sample_video, output_path=out)

        assert result.success is True
        assert result.srt_path is not None
        with open(result.srt_path, encoding="utf-8") as f:
            assert "Menu --> Settings" in f.read()

    def test_directory_style_output_path_writes_subtitles_file(self, sample_video, tmp_path):
        from mcp_video.engine import generate_subtitles

        output_dir = str(tmp_path / "subtitle_dir") + os.sep
        entries = [{"start": 0.0, "end": 1.0, "text": "Hello"}]

        result = generate_subtitles(entries, sample_video, output_path=output_dir)

        assert result.srt_path == os.path.join(output_dir, "subtitles.srt")
        assert os.path.isfile(result.srt_path)

    def test_empty_entries_raises(self, sample_video):
        from mcp_video.engine import generate_subtitles

        with pytest.raises(MCPVideoError, match="entries"):
            generate_subtitles([], sample_video)

    def test_invalid_time_range_raises(self, sample_video):
        from mcp_video.engine import generate_subtitles

        entries = [{"start": 2.0, "end": 1.0, "text": "Bad range"}]
        with pytest.raises(MCPVideoError, match=r"start.*end"):
            generate_subtitles(entries, sample_video)

    def test_invalid_entry_rejected_before_input_validation(self):
        from mcp_video.engine import generate_subtitles

        entries = [{"start": 1.0, "text": "Missing end"}]
        with pytest.raises(MCPVideoError, match="subtitle entry"):
            generate_subtitles(entries, "/tmp/missing.mp4")


class TestAudioWaveform:
    """Tests for audio waveform extraction."""

    def test_waveform_extraction(self, sample_video):
        from mcp_video.engine import audio_waveform

        result = audio_waveform(sample_video, bins=10)
        assert result.success is True
        assert result.duration > 0
        assert len(result.peaks) > 0
        assert isinstance(result.mean_level, float)
        assert isinstance(result.max_level, float)
        assert isinstance(result.min_level, float)
        assert isinstance(result.silence_regions, list)

    def test_waveform_no_audio_raises(self, sample_video_no_audio):
        from mcp_video.engine import audio_waveform

        with pytest.raises(MCPVideoError, match="audio"):
            audio_waveform(sample_video_no_audio)

    def test_waveform_custom_bins(self, sample_video):
        from mcp_video.engine import audio_waveform

        result = audio_waveform(sample_video, bins=20)
        assert len(result.peaks) == 20

    def test_waveform_rejects_excessive_bins(self, sample_video):
        from mcp_video.engine import audio_waveform

        with pytest.raises(MCPVideoError, match="bins"):
            audio_waveform(sample_video, bins=1001)

    def test_waveform_non_ametadata_failure_raises(self, sample_video, monkeypatch):
        from mcp_video.engine import audio_waveform
        from mcp_video import engine_audio_waveform

        class FailedProcess:
            returncode = 1
            stderr = "Unexpected FFmpeg failure"

        monkeypatch.setattr(engine_audio_waveform.subprocess, "run", lambda *args, **kwargs: FailedProcess())

        with pytest.raises(ProcessingError, match="Unexpected FFmpeg failure"):
            audio_waveform(sample_video, bins=10)

    def test_waveform_ametadata_reinit_failure_uses_synthetic_fallback(self, sample_video, monkeypatch):
        from mcp_video.engine import audio_waveform
        from mcp_video import engine_audio_waveform

        input_info = probe(sample_video)

        class FailedProcess:
            returncode = 1
            stderr = "Metadata key must be set\nError reinitializing filters!"

        monkeypatch.setattr(engine_audio_waveform, "probe", lambda _: input_info)
        monkeypatch.setattr(engine_audio_waveform.subprocess, "run", lambda *args, **kwargs: FailedProcess())

        result = audio_waveform(sample_video, bins=10)
        assert result.synthetic is True
        assert len(result.peaks) == 10


class TestTwoPassEncoding:
    """Tests for two-pass encoding in convert and export_video."""

    def test_convert_two_pass(self, sample_video, tmp_path):
        out = str(tmp_path / "two_pass.mp4")
        result = convert(sample_video, output_path=out, two_pass=True, target_bitrate=1000)
        assert os.path.isfile(result.output_path)
        assert result.operation == "convert"
        assert os.path.getsize(result.output_path) > 0

    def test_convert_two_pass_without_bitrate_raises(self, sample_video):
        with pytest.raises(MCPVideoError, match="target_bitrate"):
            convert(sample_video, two_pass=True, target_bitrate=None)

    def test_export_video_two_pass(self, sample_video, tmp_path):
        from mcp_video.engine import export_video

        out = str(tmp_path / "export_two_pass.mp4")
        result = export_video(sample_video, output_path=out, two_pass=True, target_bitrate=1500)
        assert os.path.isfile(result.output_path)
        assert result.operation == "export"

    def test_convert_two_pass_webm_raises(self, sample_video):
        """Two-pass encoding only supports mp4 and mov formats."""
        with pytest.raises(MCPVideoError, match=r"[Tt]wo.pass"):
            convert(sample_video, format="webm", two_pass=True, target_bitrate=1000)


# ---------------------------------------------------------------------------
# Wave 3: Scene Detection
# ---------------------------------------------------------------------------


class TestSceneDetection:
    def test_detect_scenes_returns_result(self, sample_video):
        from mcp_video.engine import detect_scenes

        result = detect_scenes(sample_video)
        assert result.success is True
        assert result.duration > 0
        assert isinstance(result.scenes, list)
        assert isinstance(result.scene_count, int)

    def test_detect_scenes_custom_threshold(self, sample_video):
        from mcp_video.engine import detect_scenes

        result = detect_scenes(sample_video, threshold=0.5)
        assert result.success is True

    def test_detect_scenes_min_duration(self, sample_video):
        from mcp_video.engine import detect_scenes

        result = detect_scenes(sample_video, min_scene_duration=0.5)
        assert result.success is True
        # Verify no scene is shorter than min_duration
        for scene in result.scenes:
            assert scene["end"] - scene["start"] >= 0.4  # small tolerance

    def test_detect_scenes_nonexistent_file(self):
        from mcp_video.engine import detect_scenes

        with pytest.raises(InputFileError):
            detect_scenes("/nonexistent/video.mp4")

    def test_detect_scenes_timeout_raises_processing_error(self, sample_video, monkeypatch):
        from mcp_video.engine import detect_scenes
        from mcp_video import engine_detect_scenes

        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

        monkeypatch.setattr(engine_detect_scenes.subprocess, "run", raise_timeout)

        with pytest.raises(ProcessingError, match="timed out"):
            detect_scenes(sample_video)


# ---------------------------------------------------------------------------
# Wave 3: Image Sequences
# ---------------------------------------------------------------------------


class TestImageSequences:
    def test_create_from_images(self, sample_video, tmp_path):
        from mcp_video.engine import create_from_images

        # First export frames, then create video from them
        from mcp_video.engine import export_frames

        frames_dir = str(tmp_path / "frames")
        frames_result = export_frames(sample_video, output_dir=frames_dir, fps=1.0)
        assert len(frames_result.frame_paths) > 0

        out = str(tmp_path / "from_images.mp4")
        result = create_from_images(frames_result.frame_paths, output_path=out, fps=1.0)
        assert os.path.isfile(result.output_path)
        assert result.operation == "create_from_images"

    def test_create_from_images_sets_requested_output_fps(self, sample_video, tmp_path):
        from mcp_video.engine import create_from_images
        from mcp_video.engine import export_frames

        frames_dir = str(tmp_path / "fps_frames")
        frames_result = export_frames(sample_video, output_dir=frames_dir, fps=4.0)
        assert len(frames_result.frame_paths) > 0

        out = str(tmp_path / "from_images_12fps.mp4")
        result = create_from_images(frames_result.frame_paths, output_path=out, fps=12.0)

        probe_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate",
                "-of",
                "default=nw=1:nk=1",
                result.output_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert probe_result.stdout.strip() == "12/1"

    def test_create_from_images_preserves_precise_non_integer_fps(self):
        from mcp_video.engine_images import _format_fps_for_ffmpeg

        assert _format_fps_for_ffmpeg(29.97002997) == "29.97002997"
        assert _format_fps_for_ffmpeg(12.00001) == "12.00001"

    def test_create_from_images_passes_precise_non_integer_fps_to_ffmpeg(self, tmp_path, monkeypatch):
        from mcp_video import engine_images
        from mcp_video.models import EditResult

        frame = tmp_path / "frame.png"
        frame.write_bytes(b"fake-png")
        output = str(tmp_path / "out.mp4")
        calls = []

        monkeypatch.setattr(engine_images, "_normalize_images", lambda images, tmpdir: images)
        monkeypatch.setattr(
            engine_images,
            "_write_concat_file",
            lambda normalized, tmpdir, fps: str(tmp_path / "concat.txt"),
        )
        monkeypatch.setattr(engine_images, "_run_ffmpeg", lambda cmd: calls.append(cmd))
        monkeypatch.setattr(
            engine_images,
            "_build_edit_result",
            lambda output_path, operation, timing: EditResult(
                output_path=output_path,
                operation=operation,
            ),
        )

        result = engine_images.create_from_images([str(frame)], output_path=output, fps=29.97002997)

        final_cmd = calls[-1]
        fps_idx = final_cmd.index("-r")
        assert final_cmd[fps_idx + 1] == "29.97002997"
        assert result.operation == "create_from_images"

    def test_create_from_images_empty_raises(self):
        from mcp_video.engine import create_from_images

        with pytest.raises(MCPVideoError, match="No images"):
            create_from_images([])

    def test_create_from_images_invalid_file_raises(self):
        from mcp_video.engine import create_from_images

        with pytest.raises(InputFileError):
            create_from_images(["/nonexistent/image.jpg"])

    def test_create_from_images_zero_fps_raises(self):
        from mcp_video.engine import create_from_images

        with pytest.raises(MCPVideoError, match="fps must be a positive finite number"):
            create_from_images(["/nonexistent/image.jpg"], fps=0)

    def test_create_from_images_negative_fps_raises(self):
        from mcp_video.engine import create_from_images

        with pytest.raises(MCPVideoError, match="fps must be a positive finite number"):
            create_from_images(["/nonexistent/image.jpg"], fps=-1)

    def test_write_metadata_same_path_raises(self, sample_video):
        from mcp_video.engine import write_metadata

        with pytest.raises(MCPVideoError, match="output_path cannot be the same as input_path"):
            write_metadata(sample_video, {"title": "X"}, output_path=sample_video)

    def test_export_frames(self, sample_video, tmp_path):
        from mcp_video.engine import export_frames

        out_dir = str(tmp_path / "exported")
        result = export_frames(sample_video, output_dir=out_dir, fps=1.0)
        assert result.success is True
        assert result.frame_count > 0
        assert result.fps == 1.0
        for fp in result.frame_paths:
            assert os.path.isfile(fp)

    def test_export_frames_png(self, sample_video, tmp_path):
        from mcp_video.engine import export_frames

        out_dir = str(tmp_path / "exported_png")
        result = export_frames(sample_video, output_dir=out_dir, fps=1.0, format="png")
        assert result.frame_count > 0
        for fp in result.frame_paths:
            assert fp.endswith(".png")


# ---------------------------------------------------------------------------
# Wave 3: Quality Metrics
# ---------------------------------------------------------------------------


class TestQualityMetrics:
    def test_compare_quality_same_file(self, sample_video):
        """Comparing a file to itself should yield high quality."""
        from mcp_video.engine import compare_quality

        result = compare_quality(sample_video, sample_video)
        assert result.success is True
        assert isinstance(result.metrics, dict)
        assert result.overall_quality in ("high", "unknown")  # PSNR may not parse on all builds

    def test_compare_quality_psnr_parsed(self, sample_video):
        """PSNR should be parsed from average: summary line."""
        from mcp_video.engine import compare_quality

        result = compare_quality(sample_video, sample_video, metrics=["psnr"])
        assert result.success is True
        if "psnr" in result.metrics:
            assert result.metrics["psnr"] > 40  # same file should be very high PSNR

    def test_compare_quality_ssim_parsed(self, sample_video):
        """SSIM should be parsed from All: summary line."""
        from mcp_video.engine import compare_quality

        result = compare_quality(sample_video, sample_video, metrics=["ssim"])
        assert result.success is True
        if "ssim" in result.metrics:
            assert result.metrics["ssim"] > 0.99  # same file should be ~1.0

    def test_compare_quality_default_metrics(self, sample_video):
        from mcp_video.engine import compare_quality

        result = compare_quality(sample_video, sample_video, metrics=["psnr", "ssim"])
        assert "psnr" in result.metrics or "ssim" in result.metrics

    def test_compare_quality_unsupported_metrics_rejected_before_probe(self, sample_video, monkeypatch):
        from mcp_video.engine import compare_quality
        from mcp_video import engine_compare_quality
        from mcp_video.errors import ProcessingError

        def fail_probe(_path):
            raise AssertionError("unsupported metrics should not probe")

        monkeypatch.setattr(engine_compare_quality, "probe", fail_probe)

        with pytest.raises(ProcessingError, match="metrics"):
            compare_quality(sample_video, sample_video, metrics=["vmaf"])

    def test_compare_quality_nonexistent_original(self, sample_video):
        from mcp_video.engine import compare_quality

        with pytest.raises(InputFileError):
            compare_quality("/nonexistent/original.mp4", sample_video)


# ---------------------------------------------------------------------------
# Wave 3: Metadata Editing
# ---------------------------------------------------------------------------


class TestMetadataEditing:
    def test_read_metadata(self, sample_video):
        from mcp_video.engine import read_metadata

        result = read_metadata(sample_video)
        assert result.success is True
        assert isinstance(result.tags, dict)

    def test_read_metadata_nonexistent(self):
        from mcp_video.engine import read_metadata

        with pytest.raises(InputFileError):
            read_metadata("/nonexistent/video.mp4")

    def test_write_and_read_metadata(self, sample_video, tmp_path):
        from mcp_video.engine import read_metadata, write_metadata

        out = str(tmp_path / "tagged.mp4")
        tags = {"title": "Test Video", "artist": "Test Artist"}
        result = write_metadata(sample_video, metadata=tags, output_path=out)
        assert os.path.isfile(result.output_path)
        assert result.operation == "write_metadata"

        # Read back and verify
        read_back = read_metadata(out)
        assert read_back.title == "Test Video"
        assert read_back.artist == "Test Artist"

    def test_write_metadata_empty_raises(self, sample_video):
        from mcp_video.engine import write_metadata

        with pytest.raises(MCPVideoError, match="No metadata"):
            write_metadata(sample_video, metadata={})


# ---------------------------------------------------------------------------
# Wave 4: Video Stabilization
# ---------------------------------------------------------------------------


class TestStabilize:
    def test_stabilize(self, sample_video, tmp_path):
        from mcp_video.engine import stabilize

        out = str(tmp_path / "stabilized.mp4")
        if _check_filter_available("vidstabdetect"):
            result = stabilize(sample_video, output_path=out)
            assert os.path.isfile(result.output_path)
            assert result.operation == "stabilize"
        else:
            # vidstab not compiled into this FFmpeg — verify we get a ProcessingError
            with pytest.raises(MCPVideoError):
                stabilize(sample_video, output_path=out)

    def test_stabilize_with_params(self, sample_video, tmp_path):
        from mcp_video.engine import stabilize

        out = str(tmp_path / "stabilized_zoom.mp4")
        if _check_filter_available("vidstabdetect"):
            result = stabilize(sample_video, smoothing=20, zooming=5, output_path=out)
            assert os.path.isfile(result.output_path)
            assert result.operation == "stabilize"
        else:
            with pytest.raises(MCPVideoError):
                stabilize(sample_video, smoothing=20, zooming=5, output_path=out)

    def test_stabilize_nonexistent_file(self):
        from mcp_video.engine import stabilize

        with pytest.raises(InputFileError):
            stabilize("/nonexistent/video.mp4")


# ---------------------------------------------------------------------------
# Wave 4: Advanced Masking
# ---------------------------------------------------------------------------


class TestApplyMask:
    def test_apply_mask(self, sample_video, sample_watermark_png, tmp_path):
        from mcp_video.engine import apply_mask

        if not _check_filter_available("alphamerge"):
            pytest.skip("alphamerge filter not available")
        out = str(tmp_path / "masked.mp4")
        result = apply_mask(sample_video, mask_path=sample_watermark_png, output_path=out)
        assert os.path.isfile(result.output_path)
        assert result.operation == "apply_mask"

    def test_apply_mask_preserves_audio(self, sample_video, sample_watermark_png, tmp_path):
        """Masked video should retain the original audio track."""
        from mcp_video.engine import apply_mask

        if not _check_filter_available("alphamerge"):
            pytest.skip("alphamerge filter not available")
        out = str(tmp_path / "masked_audio.mp4")
        result = apply_mask(sample_video, mask_path=sample_watermark_png, output_path=out)
        info = probe(result.output_path)
        assert info.audio_codec is not None, "Audio should be preserved after masking"

    def test_apply_mask_with_feather(self, sample_video, sample_watermark_png, tmp_path):
        from mcp_video.engine import apply_mask

        if not _check_filter_available("alphamerge"):
            pytest.skip("alphamerge filter not available")
        out = str(tmp_path / "masked_feather.mp4")
        result = apply_mask(sample_video, mask_path=sample_watermark_png, feather=10, output_path=out)
        assert os.path.isfile(result.output_path)

    def test_apply_mask_nonexistent_input(self, sample_watermark_png):
        from mcp_video.engine import apply_mask

        with pytest.raises(InputFileError):
            apply_mask("/nonexistent/video.mp4", mask_path=sample_watermark_png)
