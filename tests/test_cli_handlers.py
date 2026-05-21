"""Tests for CLI handler registration and dispatch.

These tests verify that each handler module registers the expected commands
and that dispatch routes to the correct handler.
"""

import json
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class FakeCommandRunner:
    """Records command registrations and simulates dispatch."""

    def __init__(self, args, use_json):
        self.args = args
        self.use_json = use_json
        self.handlers = {}

    def register(self, command, handler):
        self.handlers[command] = handler

    def dispatch(self):
        handler = self.handlers.get(self.args.command)
        if handler:
            handler(self.args, self.use_json)
            return True
        return False


def _make_args(**kwargs):
    """Build a SimpleNamespace with defaults for common args."""
    defaults = {
        "command": "info",
        "input": "test.mp4",
        "output": "out.mp4",
        "json": False,
        "start": None,
        "end": None,
        "duration": None,
        "width": None,
        "height": None,
        "scale": None,
        "factor": None,
        "fmt": None,
        "quality": None,
        "timestamp": None,
        "frames": None,
        "output_dir": None,
        "subtitle": None,
        "style": None,
        "image": None,
        "position": None,
        "opacity": None,
        "margin": None,
        "crf": None,
        "preset": None,
        "angle": None,
        "flip_h": False,
        "flip_v": False,
        "fade_in": None,
        "fade_out": None,
        "audio_format": None,
        "text": None,
        "font": None,
        "size": None,
        "color": None,
        "no_shadow": False,
        "start_time": None,
        "volume": None,
        "mix": False,
        "transition": None,
        "transitions": None,
        "transition_duration": None,
        "aspect_ratio": None,
        "filter_type": None,
        "params": None,
        "radius": None,
        "strength": None,
        "similarity": None,
        "blend": None,
        "color_key": None,
        "mask_path": None,
        "mask": None,
        "feather": None,
        "speed": None,
        "intensity": None,
        "mode": None,
        "animated": False,
        "preset_name": None,
        "pitch": None,
        "waveform": None,
        "frequency": None,
        "effects": None,
        "sequence": None,
        "tracks": None,
        "audio_config": None,
        "positions": None,
        "method": None,
        "background": None,
        "overlay": None,
        "pip": None,
        "main": None,
        "clips": None,
        "layout": None,
        "gap": None,
        "padding": None,
        "border": None,
        "border_color": None,
        "border_width": None,
        "rounded_corners": None,
        "size_pct": None,
        "margin_px": None,
        "left": None,
        "right": None,
        "top": None,
        "bottom": None,
        "left_path": None,
        "right_path": None,
        "clip1": None,
        "clip2": None,
        "duration1": None,
        "duration2": None,
        "pixel_size": None,
        "mesh_size": None,
        "template": None,
        "data": None,
        "metadata": None,
        "image_path": None,
        "subtitles_path": None,
        "burn": False,
        "entries": None,
        "original_path": None,
        "distorted_path": None,
        "operation": None,
        "inputs": None,
        "model": None,
        "language": None,
        "whisper_model": None,
        "include_transcript": True,
        "include_scenes": True,
        "include_audio": True,
        "include_quality": True,
        "include_chapters": True,
        "include_colors": True,
        "scene_threshold": None,
        "output_srt": None,
        "output_txt": None,
        "output_md": None,
        "output_json": None,
        "reference_path": None,
        "style_preset": None,
        "auto_fix": False,
        "strict": False,
        "project_path": None,
        "composition_id": None,
        "slug": None,
        "spec": None,
        "props": None,
        "frames_arg": None,
        "image_format": None,
        "fps": None,
        "start_frame": None,
        "end_frame": None,
        "zoom": None,
        "zooming": None,
        "smoothing": None,
        "target_lufs": None,
        "lufs": None,
        "stems": None,
        "threshold": None,
        "min_scene_duration": None,
        "use_ai": False,
        "n_colors": None,
        "harmony": None,
        "use_ai_analysis": False,
        "analysis": None,
        "loop": False,
        "track": None,
        "render_scale": None,
        "codec": None,
        "post_process": None,
        "remove_silence": False,
        "keep_margin": None,
        "min_silence_duration": None,
        "silence_threshold": None,
        "audio_path": None,
        "video": None,
        "audio": None,
        "tone": None,
        "at": None,
        "freq": None,
        "track_volume": None,
        "tracks_list": None,
        "original": None,
        "tags": None,
        "no_transcript": False,
        "no_scenes": False,
        "no_audio": False,
        "no_quality": False,
        "no_chapters": False,
        "no_colors": False,
        "smoothness": None,
        "static": False,
        "flicker": None,
        "line_height": None,
        "animation": None,
        "track_color": None,
        "timeline": None,
        "fail_on_warning": False,
        "reference": None,
        "block_name": None,
        "port": None,
        "workers": None,
        "output_format": "mp4",
        "caption": None,
        "lra": None,
        "metrics": None,
        "music": None,
        "outro": None,
        "title": None,
        "clip": None,
        "distorted": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Registration tests — calling with a non-matching command exercises all
# runner.register() calls without invoking any handler closures.
# ---------------------------------------------------------------------------


class TestHandlersCore:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_core import handle_initial_command

        monkeypatch.setattr("mcp_video.cli.handlers_core.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_initial_command(args, use_json=False)
        assert result is False


class TestHandlersMedia:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_media import handle_media_commands

        monkeypatch.setattr("mcp_video.cli.handlers_media.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_media_commands(args, use_json=False)
        assert result is False


class TestHandlersAdvanced:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_advanced import handle_advanced_commands

        monkeypatch.setattr("mcp_video.cli.handlers_advanced.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_advanced_commands(args, use_json=False)
        assert result is False


class TestHandlersAudio:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_audio import handle_audio_commands

        monkeypatch.setattr("mcp_video.cli.handlers_audio.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_audio_commands(args, use_json=False)
        assert result is False


class TestHandlersAI:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_ai import handle_ai_commands

        monkeypatch.setattr("mcp_video.cli.handlers_ai.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_ai_commands(args, use_json=False)
        assert result is False


class TestHandlersEffects:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_effects import handle_effect_command

        monkeypatch.setattr("mcp_video.cli.handlers_effects.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_effect_command(args, use_json=False)
        assert result is False


class TestHandlersComposition:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_composition import handle_composition_command

        monkeypatch.setattr("mcp_video.cli.handlers_composition.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_composition_command(args, use_json=False)
        assert result is False


class TestHandlersHyperframes:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_hyperframes import handle_hyperframes_commands

        monkeypatch.setattr("mcp_video.cli.handlers_hyperframes.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_hyperframes_commands(args, use_json=False)
        assert result is False

    def test_render_json_uses_output_format_without_clobbering_global_format(self, monkeypatch, capsys):
        from mcp_video.cli.handlers_hyperframes import handle_hyperframes_commands

        captured = {}

        def fake_render(project_path, **kwargs):
            captured["project_path"] = project_path
            captured["kwargs"] = kwargs
            return {"success": True, "output_path": "/tmp/render.webm"}

        monkeypatch.setattr("mcp_video.hyperframes_engine.render", fake_render)
        monkeypatch.setattr(
            "mcp_video.cli.handlers_hyperframes._with_spinner",
            lambda _label, fn, *args, **kwargs: fn(*args, **kwargs),
        )
        args = _make_args(
            command="hyperframes-render",
            project_path="/tmp/project",
            output="/tmp/render.webm",
            output_format="webm",
        )

        result = handle_hyperframes_commands(args, use_json=True)
        data = json.loads(capsys.readouterr().out)

        assert result is True
        assert data["success"] is True
        assert captured["project_path"] == "/tmp/project"
        assert captured["kwargs"]["format"] == "webm"

    def test_render_json_forwards_runtime_variables(self, monkeypatch, capsys):
        from mcp_video.cli.handlers_hyperframes import handle_hyperframes_commands

        captured = {}

        def fake_render(project_path, **kwargs):
            captured["project_path"] = project_path
            captured["kwargs"] = kwargs
            return {"success": True, "output_path": "/tmp/render.mp4"}

        monkeypatch.setattr("mcp_video.hyperframes_engine.render", fake_render)
        monkeypatch.setattr(
            "mcp_video.cli.handlers_hyperframes._with_spinner",
            lambda _label, fn, *args, **kwargs: fn(*args, **kwargs),
        )
        args = _make_args(
            command="hyperframes-render",
            project_path="/tmp/project",
            variables='{"title":"Launch"}',
            variables_file="/tmp/render-vars.json",
            output_format="mp4",
        )

        result = handle_hyperframes_commands(args, use_json=True)
        data = json.loads(capsys.readouterr().out)

        assert result is True
        assert data["success"] is True
        assert captured["kwargs"]["variables"] == {"title": "Launch"}
        assert captured["kwargs"]["variables_file"] == "/tmp/render-vars.json"

    def test_still_json_forwards_runtime_variables(self, monkeypatch, capsys):
        from mcp_video.cli.handlers_hyperframes import handle_hyperframes_commands

        captured = {}

        def fake_still(project_path, **kwargs):
            captured["project_path"] = project_path
            captured["kwargs"] = kwargs
            return {"success": True, "output_path": "/tmp/still.png"}

        monkeypatch.setattr("mcp_video.hyperframes_engine.still", fake_still)
        monkeypatch.setattr(
            "mcp_video.cli.handlers_hyperframes._with_spinner",
            lambda _label, fn, *args, **kwargs: fn(*args, **kwargs),
        )
        args = _make_args(
            command="hyperframes-still",
            project_path="/tmp/project",
            frame=10,
            variables='{"title":"Still"}',
            variables_file="/tmp/still-vars.json",
        )

        result = handle_hyperframes_commands(args, use_json=True)
        data = json.loads(capsys.readouterr().out)

        assert result is True
        assert data["success"] is True
        assert captured["kwargs"]["variables"] == {"title": "Still"}
        assert captured["kwargs"]["variables_file"] == "/tmp/still-vars.json"

    def test_snapshot_json_forwards_runtime_variables(self, monkeypatch, capsys):
        from mcp_video.cli.handlers_hyperframes import handle_hyperframes_commands

        captured = {}

        def fake_snapshot(project_path, **kwargs):
            captured["project_path"] = project_path
            captured["kwargs"] = kwargs
            return {"frame_paths": ["/tmp/snap.png"]}

        monkeypatch.setattr("mcp_video.hyperframes_engine.snapshot", fake_snapshot)
        monkeypatch.setattr(
            "mcp_video.cli.handlers_hyperframes._with_spinner",
            lambda _label, fn, *args, **kwargs: fn(*args, **kwargs),
        )
        args = _make_args(
            command="hyperframes-snapshot",
            project_path="/tmp/project",
            frames=1,
            at=None,
            variables='{"title":"Snapshot"}',
            variables_file="/tmp/snapshot-vars.json",
        )

        result = handle_hyperframes_commands(args, use_json=True)
        data = json.loads(capsys.readouterr().out)

        assert result is True
        assert data["frame_paths"] == ["/tmp/snap.png"]
        assert captured["kwargs"]["variables"] == {"title": "Snapshot"}
        assert captured["kwargs"]["variables_file"] == "/tmp/snapshot-vars.json"


class TestHandlersImage:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_image import handle_image_commands

        monkeypatch.setattr("mcp_video.cli.handlers_image.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_image_commands(args, use_json=False)
        assert result is False


class TestHandlersTransitions:
    def test_all_commands_register(self, monkeypatch):
        from mcp_video.cli.handlers_transitions import handle_transition_command

        monkeypatch.setattr("mcp_video.cli.handlers_transitions.CommandRunner", FakeCommandRunner)
        args = _make_args(command="__no_match__")
        result = handle_transition_command(args, use_json=False)
        assert result is False


# ---------------------------------------------------------------------------
# Dispatch tests — exercise the actual handler closures.
# We reload the handler module inside an active patch context so that
# locally-imported formatters / _out / _with_spinner resolve to mocks.
# ---------------------------------------------------------------------------


def _reload_and_dispatch(handler_module_name, command, args, monkeypatch):
    """Reload a handler module under mock patches and dispatch a command."""
    formatters = [
        "_format_edit_text",
        "_format_info_text",
        "_format_thumbnail_text",
        "_format_storyboard_text",
        "_format_extract_audio_text",
        "_format_doctor_text",
        "_format_detect_scenes",
        "_format_export_frames",
        "_format_read_metadata",
        "_format_compare_quality",
        "_format_batch_text",
        "_format_generate_subtitles",
        "_format_templates",
        "_format_audio_waveform",
        "_format_video_analyze",
        "_format_extract_colors",
        "_format_generate_palette",
        "_format_analyze_product",
        "_format_path_panel",
        "_format_auto_chapters",
        "_format_design_quality",
        "_format_fix_design_issues",
        "_format_ai_transcribe",
        "_format_ai_upscale",
        "_format_video_info_detailed",
        "_format_quality_check",
        "_format_ai_stem_separation",
        "_format_ai_scene_detect",
        "_format_ai_color_grade",
        "_format_ai_remove_silence",
        "_format_hyperframes_render",
        "_format_hyperframes_compositions",
        "_format_hyperframes_preview",
        "_format_hyperframes_still",
        "_format_hyperframes_init",
        "_format_hyperframes_add_block",
        "_format_hyperframes_validate",
        "_format_hyperframes_pipeline",
    ]
    with (
        patch("mcp_video.cli.runner._resolve_engine", return_value=lambda *a, **k: "ok"),
        patch("mcp_video.cli.common._with_spinner", return_value="ok"),
        patch("mcp_video.cli.runner._out"),
        patch.multiple("mcp_video.cli.formatting", **{name: MagicMock() for name in formatters}),
    ):
        mod = importlib.import_module(handler_module_name)
        importlib.reload(mod)
        monkeypatch.setattr(mod, "CommandRunner", FakeCommandRunner)
        fn_name = next(n for n in dir(mod) if n.startswith("handle_") and callable(getattr(mod, n)))
        return getattr(mod, fn_name)(args, use_json=False)


class TestDispatchEngineCmd:
    """Dispatch tests for engine_cmd / plain_cmd closures."""

    def test_trim(self, monkeypatch):
        args = _make_args(command="trim", input="test.mp4")
        result = _reload_and_dispatch("mcp_video.cli.handlers_core", "trim", args, monkeypatch)
        assert result is True

    def test_merge(self, monkeypatch):
        args = _make_args(command="merge", inputs=["a.mp4", "b.mp4"])
        result = _reload_and_dispatch("mcp_video.cli.handlers_core", "merge", args, monkeypatch)
        assert result is True

    def test_reverse(self, monkeypatch):
        args = _make_args(command="reverse", input="test.mp4")
        result = _reload_and_dispatch("mcp_video.cli.handlers_media", "reverse", args, monkeypatch)
        assert result is True

    def test_templates(self, monkeypatch):
        args = _make_args(command="templates")
        result = _reload_and_dispatch("mcp_video.cli.handlers_media", "templates", args, monkeypatch)
        assert result is True

    def test_video_extract_frame(self, monkeypatch):
        args = _make_args(command="video-extract-frame", input="test.mp4")
        result = _reload_and_dispatch("mcp_video.cli.handlers_advanced", "video-extract-frame", args, monkeypatch)
        assert result is True


class TestDispatchCustomLambdas:
    """Dispatch tests for custom lambda handlers."""

    def test_add_text(self, monkeypatch):
        args = _make_args(command="add-text", input="test.mp4", text="hello")
        result = _reload_and_dispatch("mcp_video.cli.handlers_core", "add-text", args, monkeypatch)
        assert result is True

    def test_subtitles(self, monkeypatch):
        args = _make_args(command="subtitles", input="test.mp4", subtitle="sub.srt")
        result = _reload_and_dispatch("mcp_video.cli.handlers_core", "subtitles", args, monkeypatch)
        assert result is True

    def test_doctor(self, monkeypatch):
        args = _make_args(command="doctor")
        result = _reload_and_dispatch("mcp_video.cli.handlers_core", "doctor", args, monkeypatch)
        assert result is True

    def test_video_analyze(self, monkeypatch):
        args = _make_args(command="video-analyze", input="test.mp4")
        result = _reload_and_dispatch("mcp_video.cli.handlers_ai", "video-analyze", args, monkeypatch)
        assert result is True

    def test_filter_custom(self, monkeypatch):
        args = _make_args(command="filter", input="test.mp4")
        result = _reload_and_dispatch("mcp_video.cli.handlers_media", "filter", args, monkeypatch)
        assert result is True

    def test_audio_synthesize(self, monkeypatch):
        args = _make_args(command="audio-synthesize")
        result = _reload_and_dispatch("mcp_video.cli.handlers_audio", "audio-synthesize", args, monkeypatch)
        assert result is True

    def test_effect_vignette(self, monkeypatch):
        args = _make_args(command="effect-vignette", input="test.mp4")
        result = _reload_and_dispatch("mcp_video.cli.handlers_effects", "effect-vignette", args, monkeypatch)
        assert result is True

    def test_transition_glitch(self, monkeypatch):
        args = _make_args(command="transition-glitch", clip1="a.mp4", clip2="b.mp4")
        result = _reload_and_dispatch("mcp_video.cli.handlers_transitions", "transition-glitch", args, monkeypatch)
        assert result is True
