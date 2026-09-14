"""Tests for the ``kino release-checkpoint`` CLI passthrough (K3).

The command must be a pure passthrough of the MCP ``video_release_checkpoint``
tool: same implementation function, same validations, hard quality gate, and
review artifacts. The CLI layer only maps args, renders output, and fails
closed (nonzero exit) when the tool reports ``success: False``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from kinocut.cli.parser import build_parser


def _args(**overrides) -> SimpleNamespace:
    defaults = {
        "command": "release-checkpoint",
        "input": "clip.mp4",
        "output_dir": None,
        "min_score": 80.0,
        "frame_count": 6,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestReleaseCheckpointParser:
    def test_subcommand_exists_on_real_parser(self):
        parser = build_parser()
        args = parser.parse_args(["release-checkpoint", "clip.mp4"])
        assert args.command == "release-checkpoint"
        assert args.input == "clip.mp4"
        assert args.output_dir is None
        assert args.frame_count == 6

    def test_flags_map_to_mcp_tool_parameters(self):
        parser = build_parser()
        args = parser.parse_args(
            ["release-checkpoint", "clip.mp4", "-o", "review", "--min-score", "65.5", "--frame-count", "3"]
        )
        assert args.output_dir == "review"
        assert args.min_score == pytest.approx(65.5)
        assert args.frame_count == 3


class TestReleaseCheckpointPassthrough:
    def test_handler_delegates_to_the_mcp_implementation(self, monkeypatch, capsys):
        import kinocut.server_tools_ai as server_tools_ai
        from kinocut.cli.handlers_advanced import handle_advanced_commands

        calls: dict[str, object] = {}

        def fake_release_checkpoint(*args, **kwargs):
            calls["positional"] = args
            calls["keyword"] = kwargs
            return {"success": True, "video": args[0], "review_required": True}

        monkeypatch.setattr(server_tools_ai, "video_release_checkpoint", fake_release_checkpoint)

        handled = handle_advanced_commands(_args(output_dir="review", min_score=70.0, frame_count=4), use_json=True)

        assert handled is True
        assert calls["positional"] == ("clip.mp4",)
        assert calls["keyword"] == {"output_dir": "review", "min_score": 70.0, "frame_count": 4}
        payload = json.loads(capsys.readouterr().out)
        assert payload["success"] is True
        assert payload["review_required"] is True

    def test_handler_fails_closed_on_tool_error_result(self, monkeypatch):
        import kinocut.server_tools_ai as server_tools_ai
        from kinocut.cli.handlers_advanced import handle_advanced_commands

        def failing_release_checkpoint(*args, **kwargs):
            return {
                "success": False,
                "error": {"type": "quality_error", "code": "quality_gate_failed", "message": "Quality gate failed"},
            }

        monkeypatch.setattr(server_tools_ai, "video_release_checkpoint", failing_release_checkpoint)

        with pytest.raises(SystemExit) as excinfo:
            handle_advanced_commands(_args(), use_json=True)
        assert excinfo.value.code == 1

    def test_bad_min_score_rejected_by_the_shared_mcp_semantics(self):
        # The CLI calls the same tool function, so its fail-closed validation
        # (min_score 0-100, before any file access) applies unchanged.
        from kinocut.server_tools_ai import video_release_checkpoint

        result = video_release_checkpoint("clip.mp4", min_score=150)
        assert result["success"] is False
        assert result["error"]["type"] == "validation_error"
