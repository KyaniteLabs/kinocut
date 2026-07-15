"""Recommended next action: typed advisory records (#55)."""

from __future__ import annotations

from kinocut.contracts.capability import NextAction
from kinocut.next_action import next_action, next_action_for_unavailable, recommended_next_actions


def _diagnostics(ffmpeg_ok: bool, whisper_ok: bool = False):
    return {
        "success": True,
        "checks": [
            {"name": "ffmpeg", "category": "core", "required": True, "ok": ffmpeg_ok},
            {"name": "ffprobe", "category": "core", "required": True, "ok": ffmpeg_ok},
            {"name": "openai-whisper", "category": "optional", "required": False, "ok": whisper_ok},
        ],
    }


def test_next_action_builds_a_validated_advisory_record():
    action = next_action("install_dependency", "install ffmpeg to enable video editing")
    assert isinstance(action, NextAction)
    assert action.action_code == "install_dependency"
    assert action.command_template is None  # never an execution hook


def test_next_action_rejects_a_concrete_runnable_command():
    import pytest

    with pytest.raises(Exception, match="template"):
        next_action("run", "run it", command_template="kino render video.mp4")


def test_next_action_for_unavailable_references_the_required_dependency():
    from kinocut.capability_report import capability_report

    reports = capability_report(diagnostics=_diagnostics(ffmpeg_ok=False))
    video = next(r for r in reports if r.capability_id == "video_edit")
    action = next_action_for_unavailable(video)
    assert action.action_code == "install_dependency"
    assert "ffmpeg" in action.summary
    assert "video_edit" in action.summary


def test_recommended_next_actions_one_per_unavailable_capability():
    # ffmpeg missing -> every ffmpeg-gated capability is unavailable; whisper
    # missing -> ai_transcribe unavailable too.
    actions = recommended_next_actions(diagnostics=_diagnostics(ffmpeg_ok=False))
    assert len(actions) >= 1
    assert all(a.action_code == "install_dependency" for a in actions)


def test_recommended_next_actions_empty_when_everything_available():
    actions = recommended_next_actions(diagnostics=_diagnostics(ffmpeg_ok=True, whisper_ok=True))
    assert actions == []
