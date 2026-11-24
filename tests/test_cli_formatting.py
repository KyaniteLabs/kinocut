"""Tests for CLI formatting helpers.

These tests exercise formatting functions for coverage; output is sent to
Console which we do not capture.
"""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
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

    def test_format_path_panel(self, capsys):
        _format_path_panel("Done", {"output_path": "/tmp/out.mp4"})
        _format_path_panel("Done", "/tmp/out.mp4")
        output = capsys.readouterr().out
        assert "Output: /tmp/out.mp4" in output

    def test_format_extract_audio_text(self, capsys):
        _format_extract_audio_text("/tmp/audio.mp3")
        output = capsys.readouterr().out
        assert "Audio extracted: /tmp/audio.mp3" in output

    def test_format_fix_design_issues(self, capsys):
        _format_fix_design_issues("/tmp/fixed.mp4")
        output = capsys.readouterr().out
        assert "Design fixed: /tmp/fixed.mp4" in output

    def test_format_ai_upscale(self, capsys):
        _format_ai_upscale("/tmp/up.mp4", 2.0)
        output = capsys.readouterr().out
        assert "Upscaled (2.0x): /tmp/up.mp4" in output

    def test_format_ai_color_grade(self, capsys):
        _format_ai_color_grade("/tmp/graded.mp4", "cinematic")
        output = capsys.readouterr().out
        assert "Color graded (cinematic): /tmp/graded.mp4" in output

    def test_format_ai_remove_silence(self, capsys):
        _format_ai_remove_silence("/tmp/nosil.mp4")
        output = capsys.readouterr().out
        assert "Silence removed: /tmp/nosil.mp4" in output

    def test_format_templates(self, capsys):
        _format_templates()
        output = capsys.readouterr().out
        assert "youtube-shorts" in output


class TestFormattersWithModelDump:
    """Formatters that call _model_dump on the result."""

    def test_format_info_text(self, capsys):
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
        output = capsys.readouterr().out
        assert "10.50s" in output
        assert "640x480" in output

    def test_format_edit_text(self, capsys):
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
        output = capsys.readouterr().out
        assert "Operation: trim" in output
        assert "Duration: 5.00s" in output

    def test_format_thumbnail_text(self, capsys):
        _format_thumbnail_text({"frame_path": "/tmp/frame.jpg", "timestamp": 1.5})
        _format_thumbnail_text(SimpleNamespace(model_dump=lambda: {"frame_path": "/tmp/f.jpg", "timestamp": 2.0}))
        output = capsys.readouterr().out
        assert "Timestamp: 1.50s" in output
        assert "Timestamp: 2.00s" in output

    def test_format_storyboard_text(self, capsys):
        _format_storyboard_text({"frames": ["/tmp/1.jpg", "/tmp/2.jpg"], "grid": "2x2", "count": 2})
        _format_storyboard_text(SimpleNamespace(model_dump=lambda: {"frames": [], "count": 0}))
        output = capsys.readouterr().out
        assert "Grid: 2x2" in output
        assert "Frames: 0" in output

    def test_format_detect_scenes(self, capsys):
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
        output = capsys.readouterr().out
        assert "2 scenes detected in 10.00s" in output

    def test_format_export_frames(self, capsys):
        _format_export_frames(
            {
                "frame_count": 10,
                "fps": 1.0,
                "frame_paths": ["/tmp/1.jpg"],
            },
            "jpg",
        )
        _format_export_frames(SimpleNamespace(model_dump=lambda: {"frame_count": 5, "fps": 30}), "png")
        output = capsys.readouterr().out
        assert "Format: jpg" in output
        assert "Format: png" in output

    def test_format_compare_quality(self, capsys):
        _format_compare_quality(
            {
                "metrics": {"psnr": 42.5, "ssim": 0.98},
                "overall_quality": "high",
            }
        )
        output = capsys.readouterr().out
        assert "42.5000" in output
        assert "0.9800" in output

    def test_format_read_metadata(self, capsys):
        _format_read_metadata(
            {
                "title": "Test",
                "artist": "Artist",
                "tags": {"genre": "pop"},
            }
        )
        _format_read_metadata({})
        output = capsys.readouterr().out
        assert "genre" in output
        assert "pop" in output
        assert "No metadata found." in output

    def test_format_audio_waveform(self, capsys):
        _format_audio_waveform(
            {
                "duration": 60.0,
                "mean_level": -20.0,
                "max_level": -5.0,
                "min_level": -40.0,
                "silence_regions": [(1.0, 2.0)],
            }
        )
        output = capsys.readouterr().out
        assert "-20.0 dB" in output
        assert "-5.0 dB" in output

    def test_format_generate_subtitles(self, capsys):
        _format_generate_subtitles(
            {
                "entry_count": 5,
                "srt_path": "/tmp/sub.srt",
                "video_path": "/tmp/v.mp4",
            }
        )
        output = capsys.readouterr().out
        assert "Entries: 5" in output
        assert "SRT Path: /tmp/sub.srt" in output

    def test_format_auto_chapters(self, capsys):
        _format_auto_chapters(
            [
                {"timestamp": 0.0, "description": "Intro"},
                {"timestamp": 10.0, "description": "Main"},
            ]
        )
        _format_auto_chapters([(0.0, "Intro"), (10.0, "Main")])
        output = capsys.readouterr().out
        assert "Intro" in output
        assert "Main" in output
        assert "2 chapters detected" in output

    def test_format_video_info_detailed(self, capsys):
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
        output = capsys.readouterr().out
        assert "5000 kbps" in output
        assert "1920x1080" in output

    def test_format_ai_transcribe(self, capsys):
        _format_ai_transcribe({"text": "hello world", "srt_path": "/tmp/sub.srt"}, "/tmp/out.srt")
        _format_ai_transcribe({}, None)
        output = capsys.readouterr().out
        assert "hello world" in output
        assert "SRT: N/A" in output

    def test_format_ai_stem_separation(self, capsys):
        _format_ai_stem_separation({"vocals": "/tmp/vocals.wav", "drums": "/tmp/drums.wav"})
        _format_ai_stem_separation([])
        output = capsys.readouterr().out
        assert "vocals: /tmp/vocals.wav" in output
        assert "No stems found" in output

    def test_format_ai_scene_detect(self, capsys):
        _format_ai_scene_detect(
            [
                {"start": 0.0, "end": 5.0, "confidence": 0.95},
                {"start": 5.0, "end": 10.0, "confidence": 0.87},
            ]
        )
        _format_ai_scene_detect(["scene1", "scene2"])
        output = capsys.readouterr().out
        assert "0.95" in output
        assert "scene2" in output

    def test_format_hyperframes_render(self, capsys):
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
        output = capsys.readouterr().out
        assert "Output: /tmp/out.mp4" in output
        assert "Render time: 12.5s" in output

    def test_format_hyperframes_compositions(self, capsys):
        _format_hyperframes_compositions(
            {
                "compositions": [
                    {"id": "main", "width": 1920, "height": 1080, "fps": 30, "duration_in_frames": 900},
                ]
            },
            "/project",
        )
        output = capsys.readouterr().out
        assert "main" in output
        assert "900" in output

    def test_format_hyperframes_preview(self, capsys):
        _format_hyperframes_preview({"url": "http://localhost:3000", "port": 3000, "project_path": "/project"})
        _format_hyperframes_preview(SimpleNamespace(model_dump=lambda: {"url": "http://localhost:3000"}))
        output = capsys.readouterr().out
        assert "Preview running: http://localhost:3000" in output
        assert "Port: N/A" in output

    def test_format_hyperframes_still(self, capsys):
        _format_hyperframes_still({"frame": 10, "output_path": "/tmp/still.png", "resolution": "1920x1080"}, "/project")
        output = capsys.readouterr().out
        assert "Frame: 10" in output
        assert "Output: /tmp/still.png" in output

    def test_format_hyperframes_init(self, capsys):
        _format_hyperframes_init({"project_path": "/project", "template": "blank", "files": ["a.tsx"]})
        output = capsys.readouterr().out
        assert "Template: blank" in output
        assert "Files created: 1" in output

    def test_format_hyperframes_add_block(self, capsys):
        _format_hyperframes_add_block({"project_path": "/project", "block_name": "Intro", "files_added": ["a.tsx"]})
        output = capsys.readouterr().out
        assert "Block: Intro" in output
        assert "Files added: 1" in output

    def test_format_hyperframes_validate(self, capsys):
        _format_hyperframes_validate({"project_path": "/project", "valid": True, "issues": [], "warnings": []})
        _format_hyperframes_validate(
            {"project_path": "/project", "valid": False, "issues": ["error"], "warnings": ["warn"]}
        )
        output = capsys.readouterr().out
        assert "Status: Valid" in output
        assert "Status: Invalid" in output
        assert "Warnings (1):" in output

    def test_format_hyperframes_pipeline(self, capsys):
        _format_hyperframes_pipeline(
            {
                "hyperframes_output": "/tmp/hf.mp4",
                "final_output": "/tmp/final.mp4",
                "operations": ["resize", "fade"],
            },
            "/project",
        )
        output = capsys.readouterr().out
        assert "Final output: /tmp/final.mp4" in output
        assert "Post-process ops: resize, fade" in output

    def test_format_extract_colors(self, capsys):
        _format_extract_colors(
            {
                "colors": [
                    {"hex": "#FF0000", "rgb": [255, 0, 0], "css_name": "red", "coverage_pct": 50.0},
                ]
            }
        )
        output = capsys.readouterr().out
        assert "#FF0000" in output
        assert "50.0%" in output

    def test_format_generate_palette(self, capsys):
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
        output = capsys.readouterr().out
        assert "#00FF00" in output
        assert "#FF00FF" in output

    def test_format_analyze_product(self, capsys):
        _format_analyze_product(
            {
                "colors": [{"hex": "#FF0000", "css_name": "red", "coverage_pct": 50.0}],
                "description": "A red ball",
            }
        )
        _format_analyze_product({})
        output = capsys.readouterr().out
        assert "AI Description: A red ball" in output


class TestFormattersDictOrModel:
    """Formatters that accept dicts or objects with model_dump."""

    def test_format_design_quality(self, capsys):
        _format_design_quality(
            {
                "overall_score": 85,
                "issues": ["contrast low"],
                "warnings": ["font small"],
            }
        )
        _format_design_quality(SimpleNamespace(model_dump=lambda: {"overall_score": 90, "issues": [], "warnings": []}))
        output = capsys.readouterr().out
        assert "Score: 90" in output
        assert "contrast low" in output

    def test_format_quality_check(self, capsys):
        _format_quality_check(
            {
                "checks": {"brightness": {"passed": True, "value": 128}, "contrast": {"passed": False, "value": 50}},
                "passed": False,
            }
        )
        _format_quality_check({})
        output = capsys.readouterr().out
        assert "brightness" in output
        assert "contrast" in output
        assert "Overall: FAIL" in output

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

    def test_format_video_analyze(self, capsys):
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
        output = capsys.readouterr().out
        assert "Overall score: 85/100" in output
        assert "video: corrupt" in output
        assert "No metadata" in output


class TestFormattersEdgeCases:
    """Edge cases and error paths."""

    def test_format_batch_success(self, capsys):
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
        output = capsys.readouterr().out
        assert "1/2 succeeded, 1 failed" in output

    def test_format_batch_failure(self, capsys):
        _format_batch_text(
            {
                "success": False,
                "error": {"message": "bad input"},
            }
        )
        _format_batch_text({"success": False, "error": "plain error"})
        output = capsys.readouterr().out
        assert "Batch failed: bad input" in output
        assert "Batch failed: plain error" in output

    def test_format_doctor_text(self, capsys):
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
        output = capsys.readouterr().out
        assert "Kinocut doctor - OK" in output
        assert "pip install x" in output

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

    def test_format_error_mcpvideo(self, capsys):
        from mcp_video.errors import MCPVideoError

        err = MCPVideoError("test error", error_type="validation_error")
        _format_error(err)
        output = capsys.readouterr().err
        assert "test error; retry" in output
        assert "Code: unknown" in output

    def test_format_error_plain(self, capsys):
        _format_error(ValueError("plain error"))
        output = capsys.readouterr().err
        assert "plain error; retry" in output

    def test_format_error_mcpvideo_to_dict_fails(self, capsys):
        from mcp_video.errors import MCPVideoError

        err = MagicMock(spec=MCPVideoError)
        err.to_dict.side_effect = RuntimeError("boom")
        err.__str__ = lambda self: "mock error"
        _format_error(err)
        output = capsys.readouterr().err
        assert "mock error; retry" in output


class TestFormatErrorMarkupSafety:
    """Exception text is data, not Rich markup: the panel renders it literally."""

    @staticmethod
    def _render_error(err, command=None, arguments=None):
        output = StringIO()
        captured = Console(file=output, force_terminal=False, color_system=None, width=400)
        with patch.object(formatting, "err_console", captured):
            _format_error(err, command=command, arguments=arguments)
        return output.getvalue()

    def test_missing_whisper_hint_renders_the_transcribe_extra(self, monkeypatch):
        """Regression for issue #9: the visible hint must name the transcribe extra.

        The exception object already carried ``kinocut[transcribe]``, but the
        CLI fed the message to Rich as markup, so ``[transcribe]`` was parsed
        as a style tag and the panel told users to install the bare package.
        Assert the rendered panel, not the exception text.
        """
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "whisper":
                raise ImportError("No module named 'whisper'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from mcp_video.ai_engine import ai_transcribe
        from mcp_video.errors import MCPVideoError

        with pytest.raises(MCPVideoError) as exc_info:
            ai_transcribe("video.mp4")

        rendered = self._render_error(
            exc_info.value,
            command="video-ai-transcribe",
            arguments={"input": "video.mp4"},
        )

        assert "kinocut[transcribe]" in rendered
        assert 'pip install "kinocut"' not in rendered
        assert "kino kino" not in rendered
        assert "run kino video-ai-transcribe" in rendered

    def test_plain_exception_markup_is_escaped(self):
        rendered = self._render_error(ValueError('install "pkg[extra]" to continue'))
        assert 'install "pkg[extra]" to continue' in rendered
