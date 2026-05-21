"""Tests for the Python client — needs FFmpeg."""

import os
import inspect

import pytest

from mcp_video import Client
from mcp_video.client.contracts import CLIENT_METHOD_CONTRACTS
from mcp_video.engine import _check_filter_available
from mcp_video.errors import MCPVideoError
from mcp_video.models import EditResult, StoryboardResult, ThumbnailResult, VideoInfo


def requires_filter(name: str, feature: str):
    return pytest.mark.skipif(
        not _check_filter_available(name),
        reason=f"FFmpeg filter '{name}' not available ({feature} requires it)",
    )


@pytest.fixture
def editor():
    return Client()


class TestClientInstantiation:
    def test_create_client(self):
        client = Client()
        assert client is not None


class TestClientInfo:
    def test_info_returns_video_info(self, editor, sample_video):
        info = editor.info(sample_video)
        assert isinstance(info, VideoInfo)
        assert info.duration > 0
        assert info.width == 640
        assert info.height == 480

    def test_info_nonexistent_file(self, editor):
        from mcp_video.errors import InputFileError

        with pytest.raises(InputFileError):
            editor.info("/nonexistent/video.mp4")


class TestClientTrim:
    def test_trim_returns_edit_result(self, editor, sample_video):
        result = editor.trim(sample_video, start="0", duration="1")
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)
        assert result.operation == "trim"

    def test_trim_passes_params(self, editor, sample_video):
        result = editor.trim(sample_video, start="0.5", end="2")
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    def test_trim_custom_output(self, editor, sample_video, tmp_path):
        out = str(tmp_path / "custom.mp4")
        result = editor.trim(sample_video, start="0", duration="1", output=out)
        assert result.output_path == out


class TestClientMerge:
    def test_merge_returns_edit_result(self, editor, sample_video):
        result = editor.merge([sample_video, sample_video])
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)
        assert result.operation == "merge"

    def test_merge_with_transitions(self, editor, sample_video):
        result = editor.merge(
            [sample_video, sample_video],
            transitions=["fade"],
        )
        assert isinstance(result, EditResult)


class TestClientAddText:
    def test_add_text_rejects_empty_text(self, editor):
        with pytest.raises(MCPVideoError, match=r"[Tt]ext"):
            editor.add_text("/tmp/nonexistent.mp4", text="   ")

    @requires_filter("drawtext", "Text overlay")
    def test_add_text_returns_edit_result(self, editor, sample_video):
        result = editor.add_text(sample_video, text="Hello")
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @requires_filter("drawtext", "Text overlay")
    def test_add_text_passes_params(self, editor, sample_video):
        result = editor.add_text(
            sample_video,
            text="Test",
            position="bottom-center",
            font=None,
            size=36,
            color="yellow",
            shadow=False,
        )
        assert isinstance(result, EditResult)


class TestClientAddAudio:
    def test_add_audio_returns_edit_result(self, editor, sample_video, sample_audio):
        result = editor.add_audio(sample_video, sample_audio)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    def test_add_audio_with_mix(self, editor, sample_video, sample_audio):
        result = editor.add_audio(sample_video, sample_audio, mix=True)
        assert isinstance(result, EditResult)

    def test_add_audio_replacement_warns_when_source_has_audio(self, editor, sample_video, sample_audio):
        result = editor.add_audio(sample_video, sample_audio, mix=False)

        assert any("replace existing audio" in warning.lower() for warning in result.warnings)

    def test_add_audio_with_fade(self, editor, sample_video, sample_audio):
        result = editor.add_audio(
            sample_video,
            sample_audio,
            volume=0.8,
            fade_in=0.5,
            fade_out=0.5,
        )
        assert isinstance(result, EditResult)


class TestClientResize:
    def test_resize_returns_edit_result(self, editor, sample_video):
        result = editor.resize(sample_video, width=320, height=240)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    def test_resize_by_aspect_ratio(self, editor, sample_video):
        result = editor.resize(sample_video, aspect_ratio="1:1")
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientConvert:
    def test_convert_returns_edit_result(self, editor, sample_video):
        result = editor.convert(sample_video, format="webm")
        assert isinstance(result, EditResult)
        assert result.format == "webm"

    def test_convert_gif(self, editor, sample_video):
        result = editor.convert(sample_video, format="gif")
        assert isinstance(result, EditResult)
        assert result.format == "gif"


class TestClientSpeed:
    def test_speed_returns_edit_result(self, editor, sample_video):
        result = editor.speed(sample_video, factor=2.0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientThumbnail:
    def test_thumbnail_returns_thumbnail_result(self, editor, sample_video):
        result = editor.thumbnail(sample_video, timestamp=1.0)
        assert isinstance(result, ThumbnailResult)
        assert os.path.isfile(result.frame_path)
        assert result.timestamp == 1.0


class TestClientPreview:
    def test_preview_returns_edit_result(self, editor, sample_video):
        result = editor.preview(sample_video)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)
        assert result.operation == "preview"


class TestClientStoryboard:
    def test_storyboard_returns_storyboard_result(self, editor, sample_video):
        result = editor.storyboard(sample_video, frame_count=4)
        assert isinstance(result, StoryboardResult)
        assert result.count == 4
        for frame in result.frames:
            assert os.path.isfile(frame)


class TestClientSubtitles:
    @requires_filter("subtitles", "Subtitle burn-in")
    def test_subtitles_returns_edit_result(self, editor, sample_video, sample_srt):
        result = editor.subtitles(sample_video, sample_srt)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientWatermark:
    def test_watermark_returns_edit_result(self, editor, sample_video, sample_watermark_png):
        result = editor.watermark(sample_video, sample_watermark_png)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientExport:
    def test_export_returns_edit_result(self, editor, sample_video):
        result = editor.export(sample_video)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientEdit:
    @requires_filter("drawtext", "Text overlay")
    def test_edit_validates_timeline(self, editor, sample_video):
        timeline = {
            "width": 640,
            "height": 480,
            "tracks": [
                {
                    "type": "video",
                    "clips": [{"source": sample_video, "start": 0}],
                }
            ],
            "export": {"format": "mp4", "quality": "medium"},
        }
        result = editor.edit(timeline)
        assert isinstance(result, EditResult)

    def test_edit_invalid_timeline_raises(self, editor):
        with pytest.raises(Exception):
            editor.edit({"width": "not_an_int"})

    def test_edit_rejects_invalid_image_position_before_input_validation(self, editor):
        timeline = {
            "tracks": [
                {"type": "video", "clips": [{"source": "/tmp/missing.mp4"}]},
                {"type": "image", "images": [{"source": "/tmp/logo.png", "position": {"x_pct": 0.5}}]},
            ]
        }

        with pytest.raises(MCPVideoError, match="Position dict"):
            editor.edit(timeline)


class TestClientExtractAudio:
    def test_extract_audio_returns_edit_result(self, editor, sample_video):
        result = editor.extract_audio(sample_video)
        assert isinstance(result, EditResult)
        assert result.operation == "extract_audio"
        assert os.path.isfile(result.output_path)


class TestClientCrop:
    def test_crop_returns_edit_result(self, editor, sample_video):
        result = editor.crop(sample_video, width=320, height=240)
        assert isinstance(result, EditResult)
        assert result.operation == "crop"
        assert os.path.isfile(result.output_path)


class TestClientRotate:
    def test_rotate_returns_edit_result(self, editor, sample_video):
        result = editor.rotate(sample_video, angle=90)
        assert isinstance(result, EditResult)
        assert result.operation == "rotate"
        assert os.path.isfile(result.output_path)

    def test_flip_returns_edit_result(self, editor, sample_video):
        result = editor.rotate(sample_video, flip_horizontal=True)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientFade:
    def test_fade_returns_edit_result(self, editor, sample_video):
        result = editor.fade(sample_video, fade_in=0.5, fade_out=0.5)
        assert isinstance(result, EditResult)
        assert result.operation == "fade"
        assert os.path.isfile(result.output_path)


class TestClientFilter:
    @requires_filter("boxblur", "Blur filter")
    def test_blur_returns_edit_result(self, editor, sample_video):
        result = editor.filter(sample_video, filter_type="blur")
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @requires_filter("eq", "Color preset filter")
    def test_color_preset_returns_edit_result(self, editor, sample_video):
        result = editor.filter(sample_video, filter_type="color_preset", params={"preset": "warm"})
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientBlur:
    @requires_filter("boxblur", "Blur filter")
    def test_blur_returns_edit_result(self, editor, sample_video):
        result = editor.blur(sample_video)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @requires_filter("boxblur", "Blur filter")
    def test_blur_with_params(self, editor, sample_video):
        result = editor.blur(sample_video, radius=10, strength=2)
        assert isinstance(result, EditResult)


class TestClientColorGrade:
    @requires_filter("eq", "Color preset filter")
    def test_color_grade_returns_edit_result(self, editor, sample_video):
        result = editor.color_grade(sample_video, preset="cinematic")
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestClientNormalizeAudio:
    @requires_filter("loudnorm", "Audio normalization")
    def test_normalize_audio_returns_edit_result(self, editor, sample_video):
        result = editor.normalize_audio(sample_video)
        assert isinstance(result, EditResult)
        assert result.operation == "normalize_audio"
        assert os.path.isfile(result.output_path)


class TestClientOverlayVideo:
    def test_overlay_returns_edit_result(self, editor, sample_video, sample_video_2):
        result = editor.overlay_video(sample_video, sample_video_2)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    def test_overlay_with_scale(self, editor, sample_video, sample_video_2):
        result = editor.overlay_video(sample_video, sample_video_2, width=160, height=120)
        assert isinstance(result, EditResult)


class TestClientSplitScreen:
    def test_split_screen_returns_edit_result(self, editor, sample_video, sample_video_2):
        result = editor.split_screen(sample_video, sample_video_2)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    def test_split_screen_top_bottom(self, editor, sample_video, sample_video_2):
        result = editor.split_screen(sample_video, sample_video_2, layout="top-bottom")
        assert isinstance(result, EditResult)


class TestClientBatch:
    def test_batch_returns_dict(self, editor, sample_video):
        result = editor.batch([sample_video], operation="trim", params={"start": "0", "duration": "1"})
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["succeeded"] == 1

    def test_batch_unknown_operation_rejected_before_input_validation(self, editor):
        with pytest.raises(MCPVideoError, match="Unknown operation"):
            editor.batch(["/tmp/missing.mp4"], operation="nonexistent")


class TestClientValidators:
    """Tests for parameter validation in the Python client."""

    def test_layout_grid_invalid_layout(self, editor):
        with pytest.raises(MCPVideoError, match="layout must be one of"):
            editor.layout_grid(["a.mp4", "b.mp4"], "invalid-layout", "out.mp4")

    def test_layout_grid_valid_layouts(self, editor):
        for layout in ("2x2", "3x1", "1x3", "2x3"):
            # Should not raise validation error (will fail at FFmpeg/input level but validation passes)
            with pytest.raises(Exception) as exc_info:
                editor.layout_grid(["/nonexistent/a.mp4"], layout, "/nonexistent/out.mp4")
            assert exc_info.value.error_type != "validation_error"

    def test_layout_pip_invalid_position(self, editor):
        with pytest.raises(MCPVideoError, match="position must be one of"):
            editor.layout_pip("a.mp4", "b.mp4", "out.mp4", position="middle")

    def test_layout_pip_valid_positions(self, editor):
        for pos in ("top-left", "top-right", "bottom-left", "bottom-right"):
            # Should not raise validation error (will fail at FFmpeg/input level but validation passes)
            with pytest.raises(Exception) as exc_info:
                editor.layout_pip("/nonexistent/a.mp4", "/nonexistent/b.mp4", "/nonexistent/out.mp4", position=pos)
            assert exc_info.value.error_type != "validation_error"

    def test_export_invalid_quality(self, editor):
        with pytest.raises(MCPVideoError, match="quality must be one of"):
            editor.export("video.mp4", quality="superb")

    def test_mograph_count_rejects_non_positive_duration(self, editor):
        with pytest.raises(MCPVideoError, match="duration"):
            editor.mograph_count(start=0, end=10, duration=0, output="/tmp/out.mp4")

    def test_mograph_progress_rejects_unknown_style(self, editor):
        with pytest.raises(MCPVideoError, match="style"):
            editor.mograph_progress(duration=1.0, output="/tmp/out.mp4", style="spiral")

    def test_hls_segment_rejects_unknown_quality(self, editor):
        with pytest.raises(MCPVideoError, match="qualities"):
            editor.hls_segment("/tmp/video.mp4", qualities=["high", "cinema"])

    def test_watermark_rejects_unknown_position(self, editor):
        with pytest.raises(MCPVideoError, match="position must be one of"):
            editor.watermark("/tmp/video.mp4", "/tmp/logo.png", position="middle-ish")

    def test_overlay_video_rejects_unknown_position(self, editor):
        with pytest.raises(MCPVideoError, match="position must be one of"):
            editor.overlay_video("/tmp/video.mp4", "/tmp/overlay.mp4", position="middle-ish")

    def test_compare_quality_rejects_unknown_metric(self, editor):
        with pytest.raises(MCPVideoError, match="metrics must be one of"):
            editor.compare_quality("/tmp/a.mp4", "/tmp/b.mp4", metrics=["vmaf"])

    def test_convert_invalid_format(self, editor):
        with pytest.raises(MCPVideoError, match="format must be one of"):
            editor.convert("video.mp4", format="avi")

    def test_convert_invalid_quality(self, editor):
        with pytest.raises(MCPVideoError, match="quality must be one of"):
            editor.convert("video.mp4", quality="medium-rare")

    def test_convert_valid_combos_no_value_error(self, editor):
        for fmt in ("mp4", "webm", "gif", "mov"):
            for q in ("low", "medium", "high", "ultra"):
                # Should not raise ValueError (will fail at file-not-found or FFmpeg)
                with pytest.raises(Exception) as exc_info:
                    editor.convert("/nonexistent/video.mp4", format=fmt, quality=q)
                assert not isinstance(exc_info.value, ValueError)

    def test_audio_synthesize_rejects_unknown_effect_key(self, editor):
        with pytest.raises(MCPVideoError, match="effects"):
            editor.audio_synthesize(output="/tmp/out.wav", effects={"bitcrush": 0.5})


class TestClientAudioEffectsValidation:
    def test_audio_effects_rejects_unknown_effect_type(self, editor):
        with pytest.raises(MCPVideoError, match="type"):
            editor.audio_effects("/tmp/in.wav", "/tmp/out.wav", [{"type": "bitcrush"}])

    def test_audio_effects_rejects_missing_effect_type(self, editor):
        with pytest.raises(MCPVideoError, match="type"):
            editor.audio_effects("/tmp/in.wav", "/tmp/out.wav", [{"frequency": 1000}])


class TestClientAudioSequenceValidation:
    def test_audio_sequence_rejects_empty_sequence(self, editor):
        with pytest.raises(MCPVideoError, match="sequence"):
            editor.audio_sequence([], output="/tmp/out.wav")

    def test_audio_sequence_rejects_unknown_event_type(self, editor):
        with pytest.raises(MCPVideoError, match="type"):
            editor.audio_sequence([{"type": "unknown", "at": 0.0, "duration": 0.1}], output="/tmp/out.wav")

    def test_audio_sequence_rejects_unknown_waveform(self, editor):
        with pytest.raises(MCPVideoError, match="waveform"):
            editor.audio_sequence(
                [{"type": "tone", "at": 0.0, "duration": 0.1, "waveform": "pulse"}],
                output="/tmp/out.wav",
            )


class TestClientAudioComposeValidation:
    def test_audio_compose_rejects_empty_tracks(self, editor):
        with pytest.raises(MCPVideoError, match="tracks"):
            editor.audio_compose([], duration=1.0, output="/tmp/out.wav")

    def test_audio_compose_rejects_non_positive_duration(self, editor):
        with pytest.raises(MCPVideoError, match="duration"):
            editor.audio_compose([{"file": "/tmp/a.wav"}], duration=0, output="/tmp/out.wav")

    def test_audio_compose_rejects_track_without_file(self, editor):
        with pytest.raises(MCPVideoError, match="file"):
            editor.audio_compose([{"volume": 0.5}], duration=1.0, output="/tmp/out.wav")

    def test_audio_compose_rejects_invalid_volume(self, editor):
        with pytest.raises(MCPVideoError, match="volume"):
            editor.audio_compose([{"file": "/tmp/a.wav", "volume": 2.0}], duration=1.0, output="/tmp/out.wav")


class TestClientTextAnimatedValidation:
    def test_text_animated_rejects_empty_text(self, editor):
        with pytest.raises(MCPVideoError, match=r"[Tt]ext"):
            editor.text_animated("/tmp/video.mp4", "", "/tmp/out.mp4")

    def test_text_animated_rejects_unknown_animation(self, editor):
        with pytest.raises(MCPVideoError, match="animation"):
            editor.text_animated("/tmp/video.mp4", "Hello", "/tmp/out.mp4", animation="spin")

    def test_text_animated_rejects_unknown_position(self, editor):
        with pytest.raises(MCPVideoError, match="position"):
            editor.text_animated("/tmp/video.mp4", "Hello", "/tmp/out.mp4", position="middle-ish")


class TestClientAgentApiConsistency:
    def test_every_public_client_method_has_contract(self, editor):
        public_methods = {
            name for name, value in inspect.getmembers(editor, predicate=callable) if not name.startswith("_")
        }

        assert public_methods == set(CLIENT_METHOD_CONTRACTS)

    def test_media_contracts_advertise_edit_result(self):
        for name, contract in CLIENT_METHOD_CONTRACTS.items():
            if contract["category"] == "media":
                assert contract["return_type"] == "EditResult", name

    def test_unexpected_keyword_errors_are_agent_helpful(self, editor):
        with pytest.raises(MCPVideoError, match="Valid parameters"):
            editor.effect_noise(bogus=True)

    def test_primary_output_path_alias_maps_to_legacy_effect_signature(self, editor, monkeypatch):
        monkeypatch.setattr("mcp_video.effects_engine.effect_noise", lambda **kwargs: kwargs["output"])

        result = editor.effect_noise(input_path="/tmp/in.mp4", output_path="/tmp/out.mp4")

        assert result.output_path == "/tmp/out.mp4"

    def test_public_methods_are_wrapped_without_getattribute_override(self, editor):
        assert "__getattribute__" not in Client.__dict__
        assert getattr(editor.effect_noise, "_mcp_video_guarded", False) is True

    def test_effect_methods_return_edit_result(self, editor, monkeypatch):
        monkeypatch.setattr("mcp_video.effects_engine.effect_glow", lambda **kwargs: kwargs["output"])

        result = editor.effect_glow(input_path="/tmp/in.mp4", output_path="/tmp/out.mp4")

        assert result.output_path == "/tmp/out.mp4"
        assert result.operation == "effect_glow"

    def test_audio_preset_returns_edit_result(self, editor, monkeypatch):
        monkeypatch.setattr("mcp_video.audio_engine.audio_preset", lambda **kwargs: kwargs["output"])

        result = editor.audio_preset("drone-tech", output_path="/tmp/drone.wav")

        assert result.output_path == "/tmp/drone.wav"
        assert result.operation == "audio_preset"

    def test_audio_preset_requires_output_path(self, editor):
        with pytest.raises(MCPVideoError, match="audio_preset\\(\\) requires output_path"):
            editor.audio_preset("ui-blip")

    def test_audio_preset_rejects_unknown_pitch(self, editor):
        with pytest.raises(MCPVideoError, match="pitch"):
            editor.audio_preset("ui-blip", output_path="/tmp/out.wav", pitch="bass")

    def test_audio_preset_rejects_invalid_intensity(self, editor):
        with pytest.raises(MCPVideoError, match="intensity"):
            editor.audio_preset("typing", output_path="/tmp/out.wav", intensity=2.0)

    def test_scanlines_accepts_intensity_alias_with_warning(self, editor, monkeypatch):
        monkeypatch.setattr("mcp_video.effects_engine.effect_scanlines", lambda **kwargs: kwargs["output"])

        with pytest.warns(DeprecationWarning, match="opacity"):
            result = editor.effect_scanlines(input_path="/tmp/in.mp4", output_path="/tmp/out.mp4", intensity=0.2)

        assert result.output_path == "/tmp/out.mp4"
        assert result.operation == "effect_scanlines"

    def test_create_from_images_rejects_inputs_alias_with_helpful_message(self, editor):
        with pytest.raises(MCPVideoError, match="Use 'images=' not 'inputs='"):
            editor.create_from_images(inputs=["frame1.png"], output_path="/tmp/out.mp4")

    def test_inspect_returns_real_signature(self, editor):
        info = editor.inspect("create_from_images")

        assert info["name"] == "create_from_images"
        assert "images" in info["parameters"]
        assert info["return_type"] == "EditResult"

    def test_hyperframes_runtime_data_is_in_client_signatures(self, editor):
        render = editor.inspect("hyperframes_render")
        still = editor.inspect("hyperframes_still")
        snapshot = editor.inspect("hyperframes_snapshot")

        for info in (render, still, snapshot):
            assert "variables" in info["parameters"]
            assert "variables_file" in info["parameters"]

    def test_pipeline_chains_edit_results(self, editor, monkeypatch):
        calls = []

        def fake_create_from_images(*, images, output_path=None, **kwargs):
            calls.append(("create_from_images", images, output_path))
            return editor._to_edit_result(output_path or "/tmp/scene.mp4", operation="create_from_images")

        def fake_effect_glow(*, input_path, output_path=None, **kwargs):
            calls.append(("effect_glow", input_path, output_path))
            return editor._to_edit_result(output_path or "/tmp/glow.mp4", operation="effect_glow")

        monkeypatch.setattr(editor, "create_from_images", fake_create_from_images)
        monkeypatch.setattr(editor, "effect_glow", fake_effect_glow)

        result = editor.pipeline(
            [
                {"op": "create_from_images", "images": ["a.png"], "output_path": "/tmp/scene.mp4"},
                {"op": "effect_glow", "intensity": 0.2},
            ],
            output_path="/tmp/final.mp4",
        )

        assert result.output_path == "/tmp/final.mp4"
        assert calls == [
            ("create_from_images", ["a.png"], "/tmp/scene.mp4"),
            ("effect_glow", "/tmp/scene.mp4", "/tmp/final.mp4"),
        ]

    def test_pipeline_warns_on_stacked_polish_without_checkpoint(self, editor, monkeypatch):
        monkeypatch.setattr(
            editor,
            "effect_noise",
            lambda **kwargs: editor._to_edit_result(kwargs["output_path"], operation="effect_noise"),
        )
        monkeypatch.setattr(
            editor,
            "effect_glow",
            lambda **kwargs: editor._to_edit_result(kwargs["output_path"], operation="effect_glow"),
        )

        result = editor.pipeline(
            [
                {"op": "effect_noise", "input_path": "/tmp/in.mp4", "output_path": "/tmp/noise.mp4"},
                {"op": "effect_glow", "output_path": "/tmp/glow.mp4"},
            ]
        )

        assert any("Stacked visual polish effects" in warning for warning in result.warnings)
        assert any("release checkpoint" in warning for warning in result.warnings)

    def test_pipeline_cleanup_failure_surfaces_warning(self, editor, monkeypatch, tmp_path):
        intermediate = tmp_path / "scene.mp4"
        final = tmp_path / "final.mp4"

        monkeypatch.setattr(
            editor,
            "create_from_images",
            lambda **kwargs: editor._to_edit_result(str(intermediate), operation="create_from_images"),
        )
        monkeypatch.setattr(
            editor,
            "effect_glow",
            lambda **kwargs: editor._to_edit_result(str(final), operation="effect_glow"),
        )
        monkeypatch.setattr(os.path, "exists", lambda path: path == str(intermediate))

        def fail_remove(path):
            if path == str(intermediate):
                raise OSError("permission denied")
            os.remove(path)

        monkeypatch.setattr(os, "remove", fail_remove)

        result = editor.pipeline(
            [
                {"op": "create_from_images", "images": ["a.png"], "output_path": str(intermediate)},
                {"op": "effect_glow"},
            ],
            output_path=str(final),
            cleanup=True,
        )

        assert result.intermediates == [str(intermediate)]
        assert any("Could not remove pipeline intermediate" in warning for warning in result.warnings)
        assert any("permission denied" in warning for warning in result.warnings)

    def test_release_checkpoint_runs_quality_then_preview_artifacts(self, editor, monkeypatch, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"placeholder")
        monkeypatch.setattr(editor, "assert_quality", lambda input_path, min_score=80.0: {"overall_score": 99.0})
        monkeypatch.setattr(
            editor,
            "thumbnail",
            lambda input_path, output=None, **kwargs: editor._to_edit_result(
                output or "/tmp/thumb.jpg", operation="thumbnail"
            ),
        )
        monkeypatch.setattr(
            editor,
            "storyboard",
            lambda input_path, output_path=None, **kwargs: editor._to_edit_result(
                output_path or "/tmp/storyboard.jpg", operation="storyboard"
            ),
        )

        result = editor.release_checkpoint(str(video), output_dir=str(tmp_path / "review"))

        assert result["quality"]["overall_score"] == 99.0
        assert result["thumbnail"].endswith("thumbnail.jpg")
        assert result["review_required"] is True
