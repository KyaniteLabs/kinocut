"""Tests for CLI formatting helpers.

These tests exercise formatting functions for coverage; output is sent to
Console which we do not capture.
"""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console


from mcp_video.cli import formatting
from mcp_video.cli.formatting import (
    _format_ai_color_grade,
    _format_ai_remove_silence,
    _format_ai_scene_detect,
    _format_ai_stem_separation,
    _format_ai_transcribe,
    _format_ai_upscale,
    _format_analyze_product,
    _format_audio_waveform,
    _format_auto_chapters,
    _format_batch_text,
    _format_compare_quality,
    _format_design_quality,
    _format_detect_scenes,
    _format_doctor_text,
    _format_edit_text,
    _format_error,
    _format_export_frames,
    _format_extract_audio_text,
    _format_extract_colors,
    _format_fix_design_issues,
    _format_generate_palette,
    _format_generate_subtitles,
    _format_hyperframes_add_block,
    _format_hyperframes_compositions,
    _format_hyperframes_init,
    _format_hyperframes_pipeline,
    _format_hyperframes_preview,
    _format_hyperframes_render,
    _format_hyperframes_still,
    _format_hyperframes_validate,
    _format_info_text,
    _format_path_panel,
    _format_quality_check,
    _format_read_metadata,
    _format_storyboard_text,
    _format_templates,
    _format_thumbnail_text,
    _format_video_analyze,
    _format_video_info_detailed,
)


class TestFormattersSimple:
    """Formatters that accept simple values."""

    def test_format_path_panel(self):
        _format_path_panel("Done", {"output_path": "/tmp/out.mp4"})
        _format_path_panel("Done", "/tmp/out.mp4")

    def test_format_extract_audio_text(self):
        _format_extract_audio_text("/tmp/audio.mp3")

    def test_format_fix_design_issues(self):
        _format_fix_design_issues("/tmp/fixed.mp4")

    def test_format_ai_upscale(self):
        _format_ai_upscale("/tmp/up.mp4", 2.0)

    def test_format_ai_color_grade(self):
        _format_ai_color_grade("/tmp/graded.mp4", "cinematic")

    def test_format_ai_remove_silence(self):
        _format_ai_remove_silence("/tmp/nosil.mp4")

    def test_format_templates(self):
        _format_templates()


class TestFormattersWithModelDump:
    """Formatters that call _model_dump on the result."""

    def test_format_info_text(self):
        info = SimpleNamespace(
            path="/tmp/v.mp4",
            duration=10.5,
            resolution="640x480",
            aspect_ratio="4:3",
            fps=30.0,
            codec="h264",
            audio_codec="aac",
            size_mb=2.5,
            format="mp4",
        )
        _format_info_text(info)

    def test_format_edit_text(self):
        result = SimpleNamespace(
            model_dump=lambda: {
                "operation": "trim",
                "output_path": "/tmp/out.mp4",
                "duration": 5.0,
                "resolution": "640x480",
                "size_mb": 1.2,
                "format": "mp4",
            }
        )
        _format_edit_text(result)
        _format_edit_text({"operation": "trim", "output_path": "/tmp/out.mp4"})

    def test_format_thumbnail_text(self):
        _format_thumbnail_text({"frame_path": "/tmp/frame.jpg", "timestamp": 1.5})
        _format_thumbnail_text(SimpleNamespace(model_dump=lambda: {"frame_path": "/tmp/f.jpg", "timestamp": 2.0}))

    def test_format_storyboard_text(self):
        _format_storyboard_text({"frames": ["/tmp/1.jpg", "/tmp/2.jpg"], "grid": "2x2", "count": 2})
        _format_storyboard_text(SimpleNamespace(model_dump=lambda: {"frames": [], "count": 0}))

    def test_format_detect_scenes(self):
        _format_detect_scenes(
            {
                "scenes": [
                    {"start": 0.0, "end": 5.0, "start_frame": 0, "end_frame": 150},
                    {"start": 5.0, "end": 10.0, "start_frame": 150, "end_frame": 300},
                ],
                "scene_count": 2,
                "duration": 10.0,
            }
        )

    def test_format_export_frames(self):
        _format_export_frames(
            {
                "frame_count": 10,
                "fps": 1.0,
                "frame_paths": ["/tmp/1.jpg"],
            },
            "jpg",
        )
        _format_export_frames(SimpleNamespace(model_dump=lambda: {"frame_count": 5, "fps": 30}), "png")

    def test_format_compare_quality(self):
        _format_compare_quality(
            {
                "metrics": {"psnr": 42.5, "ssim": 0.98},
                "overall_quality": "high",
            }
        )

    def test_format_read_metadata(self):
        _format_read_metadata(
            {
                "title": "Test",
                "artist": "Artist",
                "tags": {"genre": "pop"},
            }
        )
        _format_read_metadata({})

    def test_format_audio_waveform(self):
        _format_audio_waveform(
            {
                "duration": 60.0,
                "mean_level": -20.0,
                "max_level": -5.0,
                "min_level": -40.0,
                "silence_regions": [(1.0, 2.0)],
            }
        )

    def test_format_generate_subtitles(self):
        _format_generate_subtitles(
            {
                "entry_count": 5,
                "srt_path": "/tmp/sub.srt",
                "video_path": "/tmp/v.mp4",
            }
        )

    def test_format_auto_chapters(self):
        _format_auto_chapters(
            [
                {"timestamp": 0.0, "description": "Intro"},
                {"timestamp": 10.0, "description": "Main"},
            ]
        )
        _format_auto_chapters([(0.0, "Intro"), (10.0, "Main")])

    def test_format_video_info_detailed(self):
        _format_video_info_detailed(
            {
                "duration": 120.0,
                "fps": 30,
                "resolution": "1920x1080",
                "bitrate": 5000000,
                "has_audio": True,
                "scene_changes": [5.0, 10.0],
            }
        )

    def test_format_ai_transcribe(self):
        _format_ai_transcribe({"text": "hello world", "srt_path": "/tmp/sub.srt"}, "/tmp/out.srt")
        _format_ai_transcribe({}, None)

    def test_format_ai_stem_separation(self):
        _format_ai_stem_separation({"vocals": "/tmp/vocals.wav", "drums": "/tmp/drums.wav"})
        _format_ai_stem_separation([])

    def test_format_ai_scene_detect(self):
        _format_ai_scene_detect(
            [
                {"start": 0.0, "end": 5.0, "confidence": 0.95},
                {"start": 5.0, "end": 10.0, "confidence": 0.87},
            ]
        )
        _format_ai_scene_detect(["scene1", "scene2"])

    def test_format_hyperframes_render(self):
        _format_hyperframes_render(
            {
                "output_path": "/tmp/out.mp4",
                "resolution": "1920x1080",
                "codec": "h264",
                "size_mb": 5.0,
                "render_time": 12.5,
            },
            "/project",
        )

    def test_format_hyperframes_compositions(self):
        _format_hyperframes_compositions(
            {
                "compositions": [
                    {"id": "main", "width": 1920, "height": 1080, "fps": 30, "duration_in_frames": 900},
                ]
            },
            "/project",
        )

    def test_format_hyperframes_preview(self):
        _format_hyperframes_preview({"url": "http://localhost:3000", "port": 3000, "project_path": "/project"})
        _format_hyperframes_preview(SimpleNamespace(model_dump=lambda: {"url": "http://localhost:3000"}))

    def test_format_hyperframes_still(self):
        _format_hyperframes_still({"frame": 10, "output_path": "/tmp/still.png", "resolution": "1920x1080"}, "/project")

    def test_format_hyperframes_init(self):
        _format_hyperframes_init({"project_path": "/project", "template": "blank", "files": ["a.tsx"]})

    def test_format_hyperframes_add_block(self):
        _format_hyperframes_add_block({"project_path": "/project", "block_name": "Intro", "files_added": ["a.tsx"]})

    def test_format_hyperframes_validate(self):
        _format_hyperframes_validate({"project_path": "/project", "valid": True, "issues": [], "warnings": []})
        _format_hyperframes_validate(
            {"project_path": "/project", "valid": False, "issues": ["error"], "warnings": ["warn"]}
        )

    def test_format_hyperframes_pipeline(self):
        _format_hyperframes_pipeline(
            {
                "hyperframes_output": "/tmp/hf.mp4",
                "final_output": "/tmp/final.mp4",
                "operations": ["resize", "fade"],
            },
            "/project",
        )

    def test_format_extract_colors(self):
        _format_extract_colors(
            {
                "colors": [
                    {"hex": "#FF0000", "rgb": [255, 0, 0], "css_name": "red", "coverage_pct": 50.0},
                ]
            }
        )

    def test_format_generate_palette(self):
        _format_generate_palette(
            {
                "base_color": "#FF0000",
                "palette": {
                    "complementary": {"hex": "#00FF00"},
                    "analogous": "#FF00FF",
                },
            },
            "complementary",
        )

    def test_format_analyze_product(self):
        _format_analyze_product(
            {
                "colors": [{"hex": "#FF0000", "css_name": "red", "coverage_pct": 50.0}],
                "description": "A red ball",
            }
        )
        _format_analyze_product({})


class TestFormattersDictOrModel:
    """Formatters that accept dicts or objects with model_dump."""

    def test_format_design_quality(self):
        _format_design_quality(
            {
                "overall_score": 85,
                "issues": ["contrast low"],
                "warnings": ["font small"],
            }
        )
        _format_design_quality(SimpleNamespace(model_dump=lambda: {"overall_score": 90, "issues": [], "warnings": []}))

    def test_format_quality_check(self):
        _format_quality_check(
            {
                "checks": {"brightness": {"passed": True, "value": 128}, "contrast": {"passed": False, "value": 50}},
                "passed": False,
            }
        )
        _format_quality_check({})

    def test_format_quality_check_list_schema_prints_rows_and_all_passed(self):
        with patch.object(formatting.console, "print") as print_mock:
            _format_quality_check(
                {
                    "checks": [
                        {
                            "name": "audio_levels",
                            "passed": True,
                            "score": 100.0,
                            "message": "No audio stream detected in video",
                        },
                        {"name": "contrast", "passed": False, "score": 42.0, "message": "Low contrast"},
                    ],
                    "all_passed": False,
                }
            )

        table = print_mock.call_args_list[0].args[0]
        assert table.row_count == 2
        assert "FAIL" in print_mock.call_args_list[1].args[0]

    def test_format_video_analyze(self):
        _format_video_analyze(
            {
                "metadata": {
                    "duration": 60.0,
                    "width": 1920,
                    "height": 1080,
                    "fps": 30.0,
                    "codec": "h264",
                    "audio_codec": "aac",
                    "size_bytes": 1024000,
                },
                "transcript": {
                    "text": "hello world",
                    "language": "en",
                    "segments": [{"start": 0, "end": 1, "text": "hello"}],
                    "srt_path": "/tmp/s.srt",
                },
                "scenes": [{"start": 0.0, "end": 5.0}],
                "chapters": [{"title": "Intro", "timestamp": 0.0}],
                "audio": {"mean_level": -20, "max_level": -5, "silence_regions": [(1, 2)]},
                "quality": {"overall_score": 85},
                "errors": [{"section": "video", "error": "corrupt"}],
            },
            no_transcript=False,
        )
        _format_video_analyze({}, no_transcript=True)


class TestFormattersEdgeCases:
    """Edge cases and error paths."""

    def test_format_batch_success(self):
        _format_batch_text(
            {
                "success": True,
                "results": [
                    {"input": "a.mp4", "success": True, "output_path": "/tmp/a.mp4"},
                    {"input": "b.mp4", "success": False, "error": "fail"},
                ],
                "succeeded": 1,
                "total": 2,
                "failed": 1,
            }
        )

    def test_format_batch_failure(self):
        _format_batch_text(
            {
                "success": False,
                "error": {"message": "bad input"},
            }
        )
        _format_batch_text({"success": False, "error": "plain error"})

    def test_format_doctor_text(self):
        _format_doctor_text(
            {
                "summary": {"required_ok": True},
                "checks": [
                    {"name": "ffmpeg", "category": "core", "required": True, "ok": True, "version": "6.0"},
                    {
                        "name": "optional",
                        "category": "extra",
                        "required": False,
                        "ok": False,
                        "install_hint": "pip install x",
                    },
                ],
            }
        )

    def test_format_doctor_text_shows_version_and_hint_for_failed_check(self, monkeypatch):
        output = StringIO()
        monkeypatch.setattr(
            formatting,
            "console",
            Console(file=output, force_terminal=False, color_system=None, width=80),
        )

        _format_doctor_text(
            {
                "summary": {"required_ok": True},
                "checks": [
                    {
                        "name": "python",
                        "category": "core",
                        "required": False,
                        "ok": False,
                        "version": "Python 3.9.6",
                        "install_hint": "Python 3.11+ is required.",
                    }
                ],
            }
        )

        rendered = output.getvalue()
        assert "Python 3.9.6" in rendered
        assert "Python 3.11+ is" in rendered
        assert "required." in rendered

    def test_format_error_mcpvideo(self):
        from mcp_video.errors import MCPVideoError

        err = MCPVideoError("test error", error_type="validation_error")
        _format_error(err)

    def test_format_error_plain(self):
        _format_error(ValueError("plain error"))

    def test_format_error_mcpvideo_to_dict_fails(self):
        from mcp_video.errors import MCPVideoError

        err = MagicMock(spec=MCPVideoError)
        err.to_dict.side_effect = RuntimeError("boom")
        err.__str__ = lambda self: "mock error"
        _format_error(err)
