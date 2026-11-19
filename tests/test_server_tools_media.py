"""Tests for mcp_video/server_tools_media.py — thumbnail, preview, crop, and related tools."""

from __future__ import annotations

import os

import pytest

from mcp_video.server_tools_media import (
    video_crop,
    video_edit,
    video_export,
    video_extract_audio,
    video_fade,
    video_preview,
    video_rotate,
    video_storyboard,
    video_subtitles,
    video_template_preview,
    video_thumbnail,
    video_watermark,
)


# ---------------------------------------------------------------------------
# video_thumbnail
# ---------------------------------------------------------------------------


class TestVideoThumbnail:
    def test_rejects_nonexistent_file(self):
        result = video_thumbnail("/nonexistent/video.mp4")
        assert result["success"] is False

    @pytest.mark.slow
    def test_extracts_frame(self, sample_video, tmp_path):
        out = str(tmp_path / "thumb.jpg")
        result = video_thumbnail(sample_video, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    @pytest.mark.slow
    def test_auto_output_path(self, sample_video):
        result = video_thumbnail(sample_video)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    @pytest.mark.slow
    def test_with_timestamp(self, sample_video, tmp_path):
        out = str(tmp_path / "thumb_ts.jpg")
        result = video_thumbnail(sample_video, timestamp=1.0, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


# ---------------------------------------------------------------------------
# video_preview
# ---------------------------------------------------------------------------


class TestVideoPreview:
    def test_rejects_nonexistent_file(self):
        result = video_preview("/nonexistent/video.mp4")
        assert result["success"] is False

    def test_rejects_scale_factor_one(self, sample_video):
        result = video_preview(sample_video, scale_factor=1)
        assert result["success"] is False

    def test_rejects_scale_factor_above_max(self, sample_video):
        result = video_preview(sample_video, scale_factor=17)
        assert result["success"] is False

    @pytest.mark.slow
    def test_produces_preview(self, sample_video, tmp_path):
        out = str(tmp_path / "preview.mp4")
        result = video_preview(sample_video, output_path=out, scale_factor=4)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    @pytest.mark.slow
    def test_preview_is_lower_resolution(self, sample_video, tmp_path):
        from mcp_video.engine_probe import probe

        out = str(tmp_path / "preview_res.mp4")
        result = video_preview(sample_video, output_path=out, scale_factor=4)
        assert result["success"] is True
        info = probe(result["output_path"])
        # The engine clamps previews to a 320x240 floor: 640/4=160 -> 320.
        assert info.width == 320
        assert info.height == 240


# ---------------------------------------------------------------------------
# video_storyboard
# ---------------------------------------------------------------------------


class TestVideoStoryboard:
    def test_rejects_nonexistent_file(self):
        result = video_storyboard("/nonexistent/video.mp4")
        assert result["success"] is False

    def test_rejects_frame_count_zero(self, sample_video):
        result = video_storyboard(sample_video, frame_count=0)
        assert result["success"] is False

    def test_rejects_frame_count_above_max(self, sample_video):
        result = video_storyboard(sample_video, frame_count=101)
        assert result["success"] is False

    @pytest.mark.slow
    def test_produces_frames(self, sample_video, tmp_path):
        out_dir = str(tmp_path / "storyboard")
        result = video_storyboard(sample_video, output_dir=out_dir, frame_count=4)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# video_subtitles
# ---------------------------------------------------------------------------


class TestVideoSubtitles:
    def test_rejects_nonexistent_video(self, sample_srt):
        result = video_subtitles("/nonexistent/video.mp4", subtitle_path=sample_srt)
        assert result["success"] is False

    def test_rejects_nonexistent_subtitle(self, sample_video):
        result = video_subtitles(sample_video, subtitle_path="/nonexistent/subs.srt")
        assert result["success"] is False

    @pytest.mark.slow
    def test_burns_srt_subtitles(self, sample_video, sample_srt, tmp_path):
        out = str(tmp_path / "subbed.mp4")
        result = video_subtitles(sample_video, subtitle_path=sample_srt, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


# ---------------------------------------------------------------------------
# video_watermark
# ---------------------------------------------------------------------------


class TestVideoWatermark:
    def test_rejects_nonexistent_video(self, sample_watermark_png):
        result = video_watermark("/nonexistent/video.mp4", image_path=sample_watermark_png)
        assert result["success"] is False

    def test_rejects_nonexistent_image(self, sample_video):
        result = video_watermark(sample_video, image_path="/nonexistent/logo.png")
        assert result["success"] is False

    def test_rejects_opacity_above_one(self, sample_video, sample_watermark_png):
        result = video_watermark(sample_video, image_path=sample_watermark_png, opacity=1.5)
        assert result["success"] is False

    def test_rejects_opacity_below_zero(self, sample_video, sample_watermark_png):
        result = video_watermark(sample_video, image_path=sample_watermark_png, opacity=-0.1)
        assert result["success"] is False

    def test_rejects_negative_margin(self, sample_video, sample_watermark_png):
        result = video_watermark(sample_video, image_path=sample_watermark_png, margin=-1)
        assert result["success"] is False

    def test_rejects_invalid_crf(self, sample_video, sample_watermark_png):
        result = video_watermark(sample_video, image_path=sample_watermark_png, crf=60)
        assert result["success"] is False

    def test_rejects_invalid_preset(self, sample_video, sample_watermark_png):
        result = video_watermark(sample_video, image_path=sample_watermark_png, preset="invalid_preset")
        assert result["success"] is False

    @pytest.mark.slow
    def test_success(self, sample_video, sample_watermark_png, tmp_path):
        out = str(tmp_path / "watermarked.mp4")
        result = video_watermark(sample_video, image_path=sample_watermark_png, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])

    @pytest.mark.slow
    def test_position_top_left(self, sample_video, sample_watermark_png, tmp_path):
        out = str(tmp_path / "wm_topleft.mp4")
        result = video_watermark(sample_video, image_path=sample_watermark_png, position="top-left", output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


# ---------------------------------------------------------------------------
# video_export
# ---------------------------------------------------------------------------


class TestVideoExport:
    def test_rejects_invalid_format(self, sample_video):
        result = video_export(sample_video, format="avi")
        assert result["success"] is False

    def test_rejects_nonexistent_file(self):
        result = video_export("/nonexistent/video.mp4", format="mp4")
        assert result["success"] is False

    def test_review_export_blocks_failed_checkpoint_until_explicit_override(self, sample_video, tmp_path, monkeypatch):
        from pathlib import Path

        from kinocut import engine_export, quality_guardrails
        from kinocut.errors import MCPVideoError
        from kinocut.models import EditResult
        from kinocut.review_card import final_export_path

        source = tmp_path / "cut.mp4"
        source.write_bytes(Path(sample_video).read_bytes())
        checked = []

        def fail_checkpoint(snapshot, **kwargs):
            assert kwargs["require_clean_audio"]
            assert Path(snapshot).read_bytes() == source.read_bytes()
            checked.append(snapshot)
            raise MCPVideoError("Clipped audio", error_type="quality_error", code="quality_gate_failed")

        def export(snapshot, *, output_path, **kwargs):
            assert snapshot == checked[-1]
            Path(output_path).write_bytes(Path(snapshot).read_bytes())
            return EditResult(output_path=output_path)

        monkeypatch.setattr(quality_guardrails, "assert_quality", fail_checkpoint)
        monkeypatch.setattr(engine_export, "export_video", export)
        final = final_export_path(str(source))
        failed = video_export(str(source), output_path=final)
        assert failed["error"]["code"] == "quality_gate_failed"
        assert not Path(final).exists()

        delivered = video_export(str(source), output_path=final, override_reason="Approved alternate reference copy")
        checkpoint = delivered["review_receipt"]["checkpoint"]
        assert delivered["success"]
        assert Path(final).is_file()
        assert checkpoint["passed"] is False
        assert checkpoint["failure"]["code"] == "quality_gate_failed"
        assert checkpoint["override_reason"] == "Approved alternate reference copy"

    def test_override_requires_the_review_delivery_path(self, sample_video, tmp_path):
        result = video_export(sample_video, output_path=str(tmp_path / "exported.mp4"), override_reason="review")
        assert result["success"] is False

    @pytest.mark.slow
    def test_exports_mp4(self, sample_video, tmp_path):
        out = str(tmp_path / "exported.mp4")
        result = video_export(sample_video, output_path=out, quality="high", format="mp4")
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


# ---------------------------------------------------------------------------
# video_crop
# ---------------------------------------------------------------------------


class TestVideoCrop:
    def test_rejects_nonexistent_file(self):
        result = video_crop("/nonexistent/video.mp4", width=320, height=240)
        assert result["success"] is False

    @pytest.mark.slow
    def test_crop_by_dimensions(self, sample_video, tmp_path):
        from mcp_video.engine_probe import probe

        out = str(tmp_path / "cropped.mp4")
        result = video_crop(sample_video, width=320, height=240, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])
        info = probe(result["output_path"])
        assert info.width == 320
        assert info.height == 240

    @pytest.mark.slow
    def test_crop_by_percent(self, sample_video, tmp_path):
        from mcp_video.engine_probe import probe

        out = str(tmp_path / "cropped_pct.mp4")
        result = video_crop(sample_video, crop_percent=50, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])
        info = probe(result["output_path"])
        assert info.width == 320
        assert info.height == 240


# ---------------------------------------------------------------------------
# video_rotate
# ---------------------------------------------------------------------------


class TestVideoRotate:
    def test_rejects_nonexistent_file(self):
        result = video_rotate("/nonexistent/video.mp4", angle=90)
        assert result["success"] is False

    @pytest.mark.slow
    def test_rotate_90(self, sample_video, tmp_path):
        from mcp_video.engine_probe import probe

        out = str(tmp_path / "rotated.mp4")
        result = video_rotate(sample_video, angle=90, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])
        info = probe(result["output_path"])
        # After 90-degree rotation: width and height are swapped
        assert info.width == 480
        assert info.height == 640

    @pytest.mark.slow
    def test_flip_horizontal(self, sample_video, tmp_path):
        out = str(tmp_path / "flipped.mp4")
        result = video_rotate(sample_video, angle=0, flip_horizontal=True, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


# ---------------------------------------------------------------------------
# video_fade
# ---------------------------------------------------------------------------


class TestVideoFade:
    def test_rejects_nonexistent_file(self):
        result = video_fade("/nonexistent/video.mp4", fade_in=0.5)
        assert result["success"] is False

    def test_rejects_negative_fade_in(self, sample_video):
        result = video_fade(sample_video, fade_in=-0.5)
        assert result["success"] is False

    def test_rejects_negative_fade_out(self, sample_video):
        result = video_fade(sample_video, fade_out=-0.5)
        assert result["success"] is False

    def test_rejects_invalid_crf(self, sample_video):
        result = video_fade(sample_video, fade_in=0.5, crf=60)
        assert result["success"] is False

    def test_rejects_invalid_preset(self, sample_video):
        result = video_fade(sample_video, fade_in=0.5, preset="turbo")
        assert result["success"] is False

    @pytest.mark.slow
    def test_fade_in_and_out(self, sample_video, tmp_path):
        out = str(tmp_path / "faded.mp4")
        result = video_fade(sample_video, fade_in=0.5, fade_out=0.5, output_path=out)
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])


# ---------------------------------------------------------------------------
# video_edit (timeline)
# ---------------------------------------------------------------------------


class TestVideoEdit:
    def test_rejects_invalid_type(self):
        result = video_edit(42)  # not a dict or str
        assert result["success"] is False

    def test_rejects_invalid_json_string(self):
        result = video_edit("{not valid json}")
        assert result["success"] is False

    def test_rejects_nonexistent_json_file(self):
        result = video_edit("/nonexistent/timeline.json")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# video_template_preview
# ---------------------------------------------------------------------------


class TestVideoTemplatePreview:
    def test_rejects_unknown_template(self):
        result = video_template_preview("nonexistent-template")
        assert result["success"] is False

    def test_valid_template_no_video(self):
        result = video_template_preview("tiktok")
        # Should return a dict with template info, not an error
        assert isinstance(result, dict)

    def test_valid_template_with_duration(self):
        result = video_template_preview("youtube-shorts", duration=30.0)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# video_extract_audio
# ---------------------------------------------------------------------------


class TestVideoExtractAudio:
    def test_rejects_nonexistent_file(self):
        result = video_extract_audio("/nonexistent/video.mp4")
        assert result["success"] is False

    def test_rejects_invalid_format(self, sample_video):
        result = video_extract_audio(sample_video, format="xyz")
        assert result["success"] is False

    @pytest.mark.slow
    def test_extracts_mp3(self, sample_video, tmp_path):
        out = str(tmp_path / "audio.mp3")
        result = video_extract_audio(sample_video, output_path=out, format="mp3")
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])
        assert result.get("format") == "mp3"

    @pytest.mark.slow
    def test_extracts_aac(self, sample_video, tmp_path):
        out = str(tmp_path / "audio.aac")
        result = video_extract_audio(sample_video, output_path=out, format="aac")
        assert result["success"] is True
        assert os.path.isfile(result["output_path"])
