"""Tests for the MCP server tool layer — needs FFmpeg."""

import asyncio
import json
import os

import pytest

from mcp_video.engine import _check_filter_available
from mcp_video import server_resources
from mcp_video.server import (
    _error_result,
    _result,
    mcp,
    templates_resource,
    video_audio_resource,
    effect_noise,
    effect_glow,
    transition_glitch,
    transition_pixelate,
    video_add_audio,
    video_add_text,
    video_ai_scene_detect,
    search_tools,
    video_ai_transcribe,
    video_ai_upscale,
    video_apply_mask,
    video_batch,
    video_compare_quality,
    video_convert,
    video_chroma_key,
    video_create_from_images,
    video_crop,
    video_detect_scenes,
    video_edit,
    video_export,
    video_export_frames,
    video_extract_audio,
    video_fade,
    video_filter,
    video_generate_subtitles,
    video_hls_segment,
    video_info,
    video_layout_grid,
    video_layout_pip,
    video_info_resource,
    video_merge,
    video_mograph_progress,
    video_normalize_audio,
    video_overlay,
    video_preview,
    video_preview_resource,
    video_read_metadata,
    video_resize,
    video_rotate,
    video_speed,
    video_split_screen,
    video_stabilize,
    video_storyboard,
    video_template_preview,
    video_text_animated,
    video_thumbnail,
    video_trim,
    video_watermark,
    video_write_metadata,
    video_analyze,
    video_ai_color_grade,
)
from mcp_video.errors import InputFileError, MCPVideoError


def requires_filter(name: str, feature: str):
    return pytest.mark.skipif(
        not _check_filter_available(name),
        reason=f"FFmpeg filter '{name}' not available ({feature} requires it)",
    )


class TestServerInitialization:
    def test_mcp_instance(self):
        assert mcp is not None
        assert mcp.name == "kinocut"

    def test_tools_registered(self):
        # Check that the server has tools registered
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]
        assert "video_info" in tool_names
        assert "video_trim" in tool_names
        assert "video_merge" in tool_names
        assert "video_add_text" in tool_names
        assert "video_add_audio" in tool_names
        assert "video_resize" in tool_names
        assert "video_convert" in tool_names
        assert "video_speed" in tool_names
        assert "video_thumbnail" in tool_names
        assert "video_preview" in tool_names
        assert "video_storyboard" in tool_names
        assert "video_export" in tool_names
        assert "video_edit" in tool_names
        assert "video_extract_audio" in tool_names
        assert "video_crop" in tool_names
        assert "video_rotate" in tool_names
        assert "video_fade" in tool_names
        assert "video_filter" in tool_names
        assert "video_normalize_audio" in tool_names
        assert "video_overlay" in tool_names
        assert "video_split_screen" in tool_names
        assert "video_batch" in tool_names
        assert "video_detect_scenes" in tool_names
        assert "video_create_from_images" in tool_names
        assert "video_export_frames" in tool_names
        assert "video_compare_quality" in tool_names
        assert "video_read_metadata" in tool_names
        assert "video_write_metadata" in tool_names
        assert "video_stabilize" in tool_names
        assert "video_apply_mask" in tool_names

    def test_resources_registered(self):
        # Verify templates resource is defined (can't call async list_resources in sync test)
        assert templates_resource is not None
        result = templates_resource()
        assert len(result) > 0

    def test_resource_split_preserves_exports_without_duplicate_registration(self):
        assert video_info_resource is server_resources.video_info_resource
        assert video_preview_resource is server_resources.video_preview_resource
        assert video_audio_resource is server_resources.video_audio_resource
        assert templates_resource is server_resources.templates_resource

        resource_manager = mcp._resource_manager
        assert set(resource_manager._resources) == {"mcp-video://templates"}
        assert set(resource_manager._templates) == {
            "mcp-video://video/{path}/info",
            "mcp-video://video/{path}/preview",
            "mcp-video://video/{path}/audio",
        }


class TestVideoInfoTool:
    def test_returns_metadata(self, sample_video):
        result = video_info(sample_video)
        assert result["success"] is True
        info = result["info"]
        assert info["width"] == 640
        assert info["height"] == 480
        assert info["duration"] > 0

    def test_nonexistent_file(self):
        result = video_info("/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result


class TestVideoTrimTool:
    def test_returns_success(self, sample_video):
        result = video_trim(sample_video, start="0", duration="1")
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_error_result(self):
        result = video_trim("/nonexistent/video.mp4", start="0", duration="1")
        assert result["success"] is False
        assert "error" in result


class TestVideoMergeTool:
    def test_returns_success(self, sample_video):
        result = video_merge([sample_video, sample_video])
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_empty_clips_error(self):
        result = video_merge([])
        assert result["success"] is False
        assert "error" in result


class TestVideoAddTextTool:
    @requires_filter("drawtext", "Text overlay")
    def test_returns_success(self, sample_video):
        result = video_add_text(sample_video, text="Hello")
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_error_on_missing_filter(self, sample_video):
        if not _check_filter_available("drawtext"):
            result = video_add_text(sample_video, text="Hello")
            assert result["success"] is False
            assert "error" in result


class TestVideoLayoutToolValidation:
    def test_layout_grid_rejects_unknown_layout_before_input_validation(self):
        result = video_layout_grid(["/tmp/missing.mp4"], "9x9", "/tmp/out.mp4")

        assert result["success"] is False
        assert "layout" in result["error"]["message"]

    def test_layout_pip_rejects_unknown_position_before_input_validation(self):
        result = video_layout_pip("/tmp/main.mp4", "/tmp/pip.mp4", "/tmp/out.mp4", position="middle")

        assert result["success"] is False
        assert "position" in result["error"]["message"]


class TestVideoTextAnimatedTool:
    def test_rejects_unknown_animation_before_input_validation(self):
        result = video_text_animated("/tmp/missing.mp4", text="Hello", animation="spin")

        assert result["success"] is False
        assert "animation" in result["error"]["message"]

    def test_rejects_empty_text_before_input_validation(self):
        result = video_text_animated("/tmp/missing.mp4", text="   ")

        assert result["success"] is False
        assert "Text cannot be empty" in result["error"]["message"]

    def test_rejects_unknown_position_before_input_validation(self):
        result = video_text_animated("/tmp/missing.mp4", text="Hello", position="middle-ish")

        assert result["success"] is False
        assert "position" in result["error"]["message"]


class TestVideoAddAudioTool:
    def test_returns_success(self, sample_video, sample_audio):
        result = video_add_audio(sample_video, sample_audio)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


class TestVideoResizeTool:
    def test_returns_success(self, sample_video):
        result = video_resize(sample_video, width=320, height=240)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


class TestVideoConvertTool:
    def test_returns_success(self, sample_video):
        result = asyncio.run(video_convert(sample_video, format="webm"))
        assert result["success"] is True
        assert result["format"] == "webm"


class TestVideoSpeedTool:
    def test_returns_success(self, sample_video):
        result = video_speed(sample_video, factor=2.0)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


class TestVideoThumbnailTool:
    def test_returns_success(self, sample_video):
        result = video_thumbnail(sample_video, timestamp=1.0)
        assert result["success"] is True
        assert os.path.isfile(result["frame_path"])


class TestVideoPreviewTool:
    def test_returns_success(self, sample_video):
        result = video_preview(sample_video)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


class TestVideoStoryboardTool:
    def test_returns_success(self, sample_video):
        result = video_storyboard(sample_video, frame_count=4)
        assert result["success"] is True
        assert result["count"] == 4


class TestVideoExportTool:
    def test_returns_success(self, sample_video):
        result = video_export(sample_video)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


class TestVideoExtractAudioTool:
    def test_returns_success(self, sample_video):
        result = video_extract_audio(sample_video)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])
        assert result["operation"] == "extract_audio"


class TestVideoEditTool:
    def test_valid_timeline(self, sample_video):
        timeline = {
            "width": 640,
            "height": 480,
            "tracks": [
                {
                    "type": "video",
                    "clips": [{"source": sample_video}],
                }
            ],
            "export": {"format": "mp4", "quality": "low"},
        }
        result = video_edit(timeline)
        assert result["success"] is True

    def test_invalid_timeline_json(self):
        result = video_edit({"width": "not_a_number"})
        assert result["success"] is False
        assert "error" in result

    def test_empty_tracks(self):
        result = video_edit({"tracks": []})
        assert result["success"] is False
        assert "error" in result


class TestErrorHandling:
    def test_error_result_helper(self):
        err = InputFileError("/bad/path.mp4")
        result = _error_result(err)
        assert result["success"] is False
        assert result["error"]["type"] == "input_error"
        assert result["error"]["code"] == "invalid_input"

    def test_result_helper_with_model(self):
        from mcp_video.models import EditResult

        edit = EditResult(output_path="/tmp/out.mp4", operation="trim")
        result = _result(edit)
        assert result["success"] is True
        assert result["output_path"] == "/tmp/out.mp4"

    def test_result_helper_with_string(self):
        result = _result("/tmp/audio.mp3")
        assert result["success"] is True
        assert result["output_path"] == "/tmp/audio.mp3"


class TestVideoTemplatePreviewTool:
    def test_unknown_template(self):
        result = video_template_preview(template="unknown")
        assert result["success"] is False
        assert "error" in result
        assert "Unknown template" in result["error"]["message"]

    def test_tiktok_preview_without_input(self):
        result = video_template_preview(template="tiktok", caption="Hello")
        assert result["success"] is True
        assert result["template"] == "tiktok"
        assert result["estimated_resolution"] == "1080x1920"
        ops = result["operations"]
        assert any(op["op"] == "resize" for op in ops)
        text_ops = [op for op in ops if op["op"] == "add_text"]
        assert len(text_ops) == 1
        assert text_ops[0]["text"] == "Hello"
        assert "estimated_size_mb" in result

    def test_youtube_preview_with_outro(self):
        result = video_template_preview(
            template="youtube",
            title="Test Title",
            outro_path="/tmp/outro.mp4",
        )
        assert result["success"] is True
        assert result["template"] == "youtube"
        assert result["estimated_resolution"] == "1920x1080"
        concat_ops = [op for op in result["operations"] if op["op"] == "concat"]
        assert len(concat_ops) == 1
        assert concat_ops[0]["clip_count"] == 2

    def test_duration_override(self):
        result = video_template_preview(template="tiktok", duration=30.0)
        assert result["success"] is True
        assert result["estimated_duration"] == 30.0
        assert result["estimated_size_mb"] > 0

    def test_all_templates_previewable(self):
        templates = ["tiktok", "youtube-shorts", "instagram-reel", "youtube", "instagram-post"]
        for name in templates:
            result = video_template_preview(template=name)
            assert result["success"] is True, f"{name} preview failed"
            assert "operations" in result
            assert "estimated_duration" in result
            assert "estimated_resolution" in result
            assert "estimated_size_mb" in result


class TestTemplatesResource:
    def test_returns_json(self):
        result = templates_resource()
        data = json.loads(result)
        assert "aspect_ratios" in data
        assert "quality_presets" in data
        assert "transition_types" in data
        assert "export_formats" in data
        assert "text_positions" in data

    def test_aspect_ratios_content(self):
        result = templates_resource()
        data = json.loads(result)
        ratios = data["aspect_ratios"]
        assert "16:9" in ratios
        assert "9:16" in ratios

    def test_export_formats_content(self):
        result = templates_resource()
        data = json.loads(result)
        formats = data["export_formats"]
        assert "mp4" in formats
        assert "webm" in formats
        assert "gif" in formats
        assert "mov" in formats


class TestResourceErrorSerialization:
    def test_video_info_resource_returns_json_error(self):
        result = video_info_resource("/nonexistent/video.mp4")
        data = json.loads(result)
        assert data["success"] is False
        assert "error" in data

    def test_video_preview_resource_returns_json_error(self):
        result = video_preview_resource("/nonexistent/video.mp4")
        data = json.loads(result)
        assert data["success"] is False
        assert "error" in data

    def test_video_audio_resource_returns_json_error(self):
        result = video_audio_resource("/nonexistent/video.mp4")
        data = json.loads(result)
        assert data["success"] is False
        assert "error" in data


class TestVideoCropTool:
    def test_returns_success(self, sample_video):
        result = video_crop(sample_video, width=320, height=240)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_error_on_too_large(self, sample_video):
        result = video_crop(sample_video, width=9999, height=9999)
        assert result["success"] is False
        assert "error" in result


class TestVideoRotateTool:
    def test_rotate_90(self, sample_video):
        result = video_rotate(sample_video, angle=90)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


class TestVideoChromaKeyTool:
    def test_invalid_color_rejected(self, sample_video):
        result = video_chroma_key(sample_video, color="invalid_color_name")
        assert result["success"] is False
        assert result["error"]["code"] == "invalid_parameter"

    def test_flip_horizontal(self, sample_video):
        result = video_rotate(sample_video, flip_horizontal=True)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_error_on_invalid_angle(self, sample_video):
        result = video_rotate(sample_video, angle=45)
        assert result["success"] is False
        assert "error" in result


class TestVideoFadeTool:
    def test_fade_in_and_out(self, sample_video):
        result = video_fade(sample_video, fade_in=0.5, fade_out=0.5)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_error_on_no_fade(self, sample_video):
        result = video_fade(sample_video, fade_in=0, fade_out=0)
        assert result["success"] is False
        assert "error" in result


class TestVideoFilterTool:
    @requires_filter("boxblur", "Blur filter")
    def test_blur_filter(self, sample_video):
        result = video_filter(sample_video, filter_type="blur")
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    @requires_filter("eq", "Color preset filter")
    def test_color_preset_filter(self, sample_video):
        result = video_filter(sample_video, filter_type="color_preset", params={"preset": "warm"})
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_error_on_missing_filter(self, sample_video):
        if not _check_filter_available("boxblur"):
            result = video_filter(sample_video, filter_type="blur")
            assert result["success"] is False
            assert "error" in result


class TestVideoFilterBlur:
    @requires_filter("boxblur", "Blur filter")
    def test_blur_default(self, sample_video):
        result = video_filter(sample_video, filter_type="blur")
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    @requires_filter("boxblur", "Blur filter")
    def test_blur_custom_radius(self, sample_video):
        result = video_filter(sample_video, filter_type="blur", params={"radius": 10, "strength": 2})
        assert result["success"] is True


class TestVideoFilterColorGrade:
    @requires_filter("eq", "Color preset filter")
    def test_warm_preset(self, sample_video):
        result = video_filter(sample_video, filter_type="color_preset", params={"preset": "warm"})
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


class TestVideoNormalizeAudioTool:
    @requires_filter("loudnorm", "Audio normalization")
    def test_normalize_default(self, sample_video):
        result = video_normalize_audio(sample_video)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])
        assert result["operation"] == "normalize_audio"

    @requires_filter("loudnorm", "Audio normalization")
    def test_normalize_broadcast(self, sample_video):
        result = video_normalize_audio(sample_video, target_lufs=-23.0)
        assert result["success"] is True


class TestVideoOverlayTool:
    def test_overlay_default(self, sample_video, sample_video_2):
        result = video_overlay(sample_video, overlay_path=sample_video_2)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_overlay_with_scale(self, sample_video, sample_video_2):
        result = video_overlay(sample_video, overlay_path=sample_video_2, width=160, height=120)
        assert result["success"] is True

    def test_error_on_missing_file(self, sample_video):
        result = video_overlay(sample_video, overlay_path="/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result


class TestVideoSplitScreenTool:
    def test_side_by_side(self, sample_video, sample_video_2):
        result = video_split_screen(sample_video, right_path=sample_video_2)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_top_bottom(self, sample_video, sample_video_2):
        result = video_split_screen(sample_video, right_path=sample_video_2, layout="top-bottom")
        assert result["success"] is True


class TestVideoBatchTool:
    def test_batch_trim(self, sample_video):
        result = video_batch(
            [sample_video, sample_video],
            operation="trim",
            params={"start": "0", "duration": "1"},
        )
        assert result["success"] is True
        assert result["total"] == 2
        assert result["succeeded"] == 2
        assert result["failed"] == 0

    def test_batch_convert(self, sample_video):
        result = video_batch(
            [sample_video],
            operation="convert",
            params={"format": "webm"},
        )
        assert result["success"] is True
        assert result["succeeded"] == 1

    def test_batch_empty_inputs(self):
        result = video_batch([], operation="trim")
        assert result["success"] is False
        assert "error" in result

    def test_batch_unknown_operation(self, sample_video):
        result = video_batch([sample_video], operation="nonexistent")
        assert result["success"] is False
        assert "error" in result

    def test_batch_unknown_operation_rejected_before_input_validation(self):
        result = video_batch(["/tmp/missing.mp4"], operation="nonexistent")
        assert result["success"] is False
        assert result["error"]["code"] == "invalid_operation"

    def test_batch_partial_failure(self, sample_video):
        result = video_batch(
            [sample_video, "/nonexistent/video.mp4"],
            operation="trim",
            params={"start": "0", "duration": "1"},
        )
        assert result["success"] is False
        assert result["succeeded"] == 1
        assert result["failed"] == 1

    def test_batch_output_dir(self, sample_video, tmp_path):
        """Regression: output_dir must actually be used by batch operations."""
        out_dir = str(tmp_path / "batch_out")
        result = video_batch(
            [sample_video],
            operation="trim",
            params={"start": "0", "duration": "1"},
            output_dir=out_dir,
        )
        assert result["success"] is True
        assert result["succeeded"] == 1
        # Output file should be in the specified directory, not next to the input
        output_path = result["results"][0]["output_path"]
        assert os.path.dirname(output_path) == out_dir


class TestVideoDetectScenesTool:
    def test_returns_scenes(self, sample_video):
        result = video_detect_scenes(sample_video)
        assert result["success"] is True
        assert "scenes" in result

    def test_nonexistent_file(self):
        result = video_detect_scenes("/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result


class TestVideoCreateFromImagesTool:
    def test_single_image(self, sample_watermark_png):
        result = video_create_from_images([sample_watermark_png])
        if not result["success"]:
            # Single image may not be supported, check for expected error
            assert "error" in result
        else:
            assert os.path.isfile(result["output_path"])

    def test_empty_list(self):
        result = video_create_from_images([])
        assert result["success"] is False
        assert "error" in result


class TestVideoExportFramesTool:
    def test_exports_frames(self, sample_video):
        result = video_export_frames(sample_video, fps=1.0)
        assert result["success"] is True
        assert result["frame_count"] > 0

    def test_nonexistent_file(self):
        result = video_export_frames("/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result


class TestVideoCompareQualityTool:
    def test_same_file(self, sample_video):
        result = video_compare_quality(sample_video, sample_video)
        assert result["success"] is True
        assert "metrics" in result

    def test_nonexistent_original(self, sample_video):
        result = video_compare_quality("/nonexistent/original.mp4", sample_video)
        assert result["success"] is False
        assert "error" in result


class TestVideoReadMetadataTool:
    def test_reads_metadata(self, sample_video):
        result = video_read_metadata(sample_video)
        assert result["success"] is True
        assert "tags" in result

    def test_nonexistent_file(self):
        result = video_read_metadata("/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result


class TestVideoWriteMetadataTool:
    def test_write_and_read(self, sample_video):
        result = video_write_metadata(sample_video, {"title": "Test Video"})
        assert result["success"] is True
        # Note: output_path may be the same as input if metadata is written in-place

    def test_empty_metadata(self, sample_video):
        # Empty metadata is still valid - just writes nothing
        result = video_write_metadata(sample_video, {})
        # Should either succeed or give a validation error
        assert "success" in result


class TestVideoStabilizeTool:
    def test_stabilizes_video(self, sample_video):
        result = video_stabilize(sample_video)
        if _check_filter_available("vidstabdetect"):
            if not result["success"]:
                error_str = result.get("error", "")
                if isinstance(error_str, dict):
                    error_str = str(error_str.get("message", ""))
                pytest.fail(f"Stabilization failed unexpectedly: {error_str}")
            assert os.path.isfile(result["output_path"])
        else:
            # vidstab not compiled into this FFmpeg — verify we get a proper error
            assert result["success"] is False

    def test_nonexistent_file(self):
        result = video_stabilize("/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result


class TestVideoApplyMaskTool:
    def test_applies_mask(self, sample_video, sample_watermark_png):
        result = video_apply_mask(sample_video, mask_path=sample_watermark_png)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    def test_nonexistent_mask(self, sample_video):
        result = video_apply_mask(sample_video, mask_path="/nonexistent/mask.png")
        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# Server parameter validation tests
# ---------------------------------------------------------------------------


class TestServerValidationCRF:
    def test_add_text_rejects_bad_crf(self, sample_video):
        result = video_add_text(sample_video, "test", crf=100)
        assert result["success"] is False
        assert "crf" in result["error"]["message"].lower()

    def test_watermark_rejects_bad_crf(self, sample_video, sample_watermark_png):
        result = video_watermark(sample_video, sample_watermark_png, crf=-5)
        assert result["success"] is False
        assert "crf" in result["error"]["message"].lower()


class TestServerValidationPreset:
    def test_filter_rejects_bad_preset(self, sample_video):
        result = video_filter(sample_video, filter_type="blur", preset="invalid")
        assert result["success"] is False
        assert "preset" in result["error"]["message"].lower()


class TestServerValidationFormat:
    def test_convert_rejects_bad_format(self, sample_video):
        result = asyncio.run(video_convert(sample_video, format="exe"))
        assert result["success"] is False
        assert "format" in result["error"]["message"].lower()

    def test_convert_rejects_bad_quality(self, sample_video):
        result = asyncio.run(video_convert(sample_video, quality="medium-rare"))
        assert result["success"] is False
        assert "quality" in result["error"]["message"].lower()

    def test_extract_audio_rejects_bad_format(self, sample_video):
        result = video_extract_audio(sample_video, format="exe")
        assert result["success"] is False


class TestServerValidationTransitions:
    def test_glitch_rejects_negative_duration(self):
        result = transition_glitch("/tmp/a.mp4", "/tmp/b.mp4", "/tmp/out.mp4", duration=-1)
        assert result["success"] is False

    def test_pixelate_rejects_small_pixel_size(self):
        result = transition_pixelate("/tmp/a.mp4", "/tmp/b.mp4", "/tmp/out.mp4", pixel_size=1)
        assert result["success"] is False


class TestServerValidationAI:
    def test_transcribe_rejects_bad_model(self, sample_video):
        result = video_ai_transcribe(sample_video, model="nonexistent")
        assert result["success"] is False

    def test_upscale_rejects_bad_scale(self, sample_video):
        result = video_ai_upscale(sample_video, "/tmp/out.mp4", scale=3)
        assert result["success"] is False

    def test_scene_detect_rejects_bad_threshold(self, sample_video):
        result = video_ai_scene_detect(sample_video, threshold=5.0)
        assert result["success"] is False


class TestServerValidationSubtitles:
    def test_generate_subtitles_rejects_bad_entry_before_input_validation(self):
        result = video_generate_subtitles([{"start": 1.0, "text": "Missing end"}], "/tmp/missing.mp4")

        assert result["success"] is False
        assert "subtitle entry" in result["error"]["message"]

    def test_generate_subtitles_rejects_bad_range_before_input_validation(self):
        result = video_generate_subtitles([{"start": 2.0, "end": 1.0, "text": "Bad"}], "/tmp/missing.mp4")

        assert result["success"] is False
        assert "start" in result["error"]["message"]


class TestServerValidationTimelinePosition:
    def test_edit_rejects_invalid_image_position_before_input_validation(self):
        timeline = {
            "tracks": [
                {"type": "video", "clips": [{"source": "/tmp/missing.mp4"}]},
                {"type": "image", "images": [{"source": "/tmp/logo.png", "position": {"x_pct": 0.5}}]},
            ]
        }

        result = video_edit(timeline)

        assert result["success"] is False
        assert "Position dict" in result["error"]["message"]


class TestServerValidationCompareQuality:
    def test_compare_quality_rejects_bad_metric_before_input_validation(self):
        result = video_compare_quality("/tmp/missing-original.mp4", "/tmp/missing-distorted.mp4", metrics=["vmaf"])

        assert result["success"] is False
        assert "metrics" in result["error"]["message"]


class TestServerValidationOverlayPosition:
    def test_watermark_rejects_bad_position_before_input_validation(self):
        result = video_watermark("/tmp/missing.mp4", "/tmp/logo.png", position="middle-ish")

        assert result["success"] is False
        assert "position" in result["error"]["message"]

    def test_overlay_rejects_bad_position_before_input_validation(self):
        result = video_overlay("/tmp/missing.mp4", "/tmp/overlay.mp4", position="middle-ish")

        assert result["success"] is False
        assert "position" in result["error"]["message"]


class TestServerValidationHls:
    def test_rejects_bad_hls_quality_before_input_validation(self):
        result = video_hls_segment("/tmp/missing.mp4", qualities=["high", "cinema"])

        assert result["success"] is False
        assert "qualities" in result["error"]["message"]

    def test_rejects_bad_segment_duration_before_input_validation(self):
        result = video_hls_segment("/tmp/missing.mp4", segment_duration=0)

        assert result["success"] is False
        assert "segment_duration" in result["error"]["message"]


class TestServerValidationSplitScreen:
    def test_rejects_bad_layout(self, sample_video):
        result = video_split_screen(sample_video, sample_video, layout="diagonal")
        assert result["success"] is False


class TestServerValidationMograph:
    def test_progress_rejects_bad_style(self):
        result = video_mograph_progress(duration=2, output_path="/tmp/out.mp4", style="invalid")
        assert result["success"] is False


class TestServerToolPathValidation:
    def test_filter_blur_rejects_nonexistent_file(self):
        result = video_filter("/nonexistent/video.mp4", filter_type="blur")
        assert result["success"] is False
        assert "error" in result

    def test_export_rejects_nonexistent_file(self):
        result = video_export("/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result

    def test_rotate_rejects_nonexistent_file(self):
        result = video_rotate("/nonexistent/video.mp4")
        assert result["success"] is False
        assert "error" in result

    def test_noise_rejects_nonexistent_file(self):
        result = effect_noise("/nonexistent/video.mp4", "/tmp/out.mp4")
        assert result["success"] is False
        assert "error" in result

    def test_glow_rejects_nonexistent_file(self):
        result = effect_glow("/nonexistent/video.mp4", "/tmp/out.mp4")
        assert result["success"] is False
        assert "error" in result


class TestServerReleaseGuardrails:
    def test_audio_synthesize_rejects_unknown_effect_key_before_render(self, tmp_path):
        from mcp_video import server_tools_audio

        result = server_tools_audio.audio_synthesize(str(tmp_path / "out.wav"), effects={"bitcrush": 0.5})

        assert result["success"] is False
        assert "effects" in result["error"]["message"].lower()
        assert not (tmp_path / "out.wav").exists()

    def test_audio_preset_warns_for_long_procedural_music_bed(self, monkeypatch, tmp_path):
        from mcp_video import server_tools_audio

        output = tmp_path / "drone.wav"

        def fake_preset(**kwargs):
            output.write_bytes(b"wav")
            return str(output)

        monkeypatch.setattr("mcp_video.audio_engine.audio_preset", fake_preset)

        result = server_tools_audio.audio_preset("drone-tech", str(output), duration=30)

        assert result["success"] is True
        assert result["output_path"] == str(output)
        assert result["warnings"]
        assert "not a polished music bed" in result["warnings"][0]

    def test_add_audio_replacement_warning_surfaces_in_mcp_result(self, monkeypatch, tmp_path):
        from mcp_video import server_tools_basic
        from mcp_video.models import EditResult

        video = tmp_path / "video.mp4"
        audio = tmp_path / "audio.wav"
        output = tmp_path / "out.mp4"
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")

        monkeypatch.setattr(server_tools_basic, "_validate_input_path", lambda path: path)
        monkeypatch.setattr(
            server_tools_basic,
            "add_audio",
            lambda *args, **kwargs: EditResult(
                output_path=str(output),
                operation="add_audio",
                warnings=["This operation will replace existing audio; listen before publishing."],
            ),
        )

        result = server_tools_basic.video_add_audio(str(video), str(audio), mix=False)

        assert result["success"] is True
        assert result["warnings"]
        assert "replace existing audio" in result["warnings"][0]

    def test_video_quality_check_fail_on_warning_returns_tool_failure(self, monkeypatch, tmp_path):
        from mcp_video import server_tools_ai

        video = tmp_path / "video.mp4"
        video.write_bytes(b"placeholder")

        monkeypatch.setattr(server_tools_ai, "_validate_input_path", lambda path: path)
        monkeypatch.setattr(
            "mcp_video.quality_guardrails.quality_check",
            lambda _path, fail_on_warning=False: {
                "video": _path,
                "overall_score": 25.0,
                "all_passed": False,
                "checks": [],
                "recommendations": ["Color cast detected"],
            },
        )

        result = server_tools_ai.video_quality_check(str(video), fail_on_warning=True)

        assert result["success"] is False
        assert result["error"]["code"] == "quality_gate_failed"

    def test_release_checkpoint_fails_before_preview_artifacts_on_bad_quality(self, monkeypatch, tmp_path):
        from mcp_video import server_tools_ai

        video = tmp_path / "video.mp4"
        video.write_bytes(b"placeholder")
        monkeypatch.setattr(server_tools_ai, "_validate_input_path", lambda path: path)
        monkeypatch.setattr(
            "mcp_video.quality_guardrails.assert_quality",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                MCPVideoError("Quality gate failed: score 25.0 < 80.0", error_type="quality_error")
            ),
        )

        result = server_tools_ai.video_release_checkpoint(str(video), output_dir=str(tmp_path / "review"))

        assert result["success"] is False
        assert "quality" in result["error"]["message"].lower()


class TestServerAIEdgeCases:
    def test_analyze_url_skips_path_validation(self, monkeypatch):
        def fake_is_url(url):
            return True

        call_log = []

        def fake_analyze(*args, **kwargs):
            call_log.append(args[0])
            return {"summary": "test"}

        monkeypatch.setattr("mcp_video.ai_engine.download._is_url", fake_is_url)
        monkeypatch.setattr("mcp_video.ai_engine.analyze_video", fake_analyze)
        # Should not raise InputFileError for a URL
        result = video_analyze("https://example.com/video.mp4")
        assert call_log == ["https://example.com/video.mp4"]
        assert "error" not in result

    def test_color_grade_none_reference_does_not_crash(self, sample_video):
        result = video_ai_color_grade(sample_video, output_path="/tmp/out.mp4", reference_path=None)
        assert result["success"] is True


class TestSearchTools:
    def test_search_by_name(self):
        result = search_tools("trim")
        assert result["success"] is True
        assert result["count"] >= 1
        names = [t["name"] for t in result["tools"]]
        assert "video_trim" in names

    def test_search_by_description(self):
        result = search_tools("resize")
        assert result["success"] is True
        assert result["count"] >= 1
        names = [t["name"] for t in result["tools"]]
        assert "video_resize" in names

    def test_search_excludes_itself(self):
        result = search_tools("search")
        assert result["success"] is True
        names = [t["name"] for t in result["tools"]]
        assert "search_tools" not in names

    def test_search_returns_required_params(self):
        result = search_tools("merge")
        assert result["success"] is True
        merge_tool = next(t for t in result["tools"] if t["name"] == "video_merge")
        assert "clips" in merge_tool["required_params"]

    def test_search_includes_creation_tools(self):
        result = search_tools("style")
        assert result["success"] is True
        names = [t["name"] for t in result["tools"]]
        assert "video_project_create" in names
        assert "style_pack_read" in names
        assert "shot_prompt_render" in names
