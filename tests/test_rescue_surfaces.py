"""Cross-surface contract tests for the dedicated rescue pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mcp_video.client import Client
from mcp_video.cli.parser import build_parser
from mcp_video.rescue._errors import RESCUE_VERIFICATION_FAILED, rescue_error


ROOT = Path(__file__).resolve().parents[1]


def test_rescue_documentation_covers_surfaces_and_guardrails():
    guide = (ROOT / "docs" / "RESCUE.md").read_text(encoding="utf-8").lower()

    for name in (
        "video_rescue_plan",
        "video_rescue_render",
        "video_rescue_inspect",
        "rescue-plan",
        "rescue-render",
        "rescue-inspect",
        "rescue_plan",
        "rescue_render",
        "rescue_inspect",
    ):
        assert name in guide
    for contract in (
        "local-only",
        "source immutable",
        "timeline locked",
        "captions are not burned",
        "missing whisper is nonfatal",
        "plan approval is required",
        "no one-command rescue",
    ):
        assert contract in guide


def test_rescue_skill_requires_plan_inspection_before_render():
    skill = (ROOT / "skills" / "kinocut" / "SKILL.md").read_text(encoding="utf-8").lower()

    assert "inspect the plan before render" in skill
    assert "never add recommendation ids" in skill


def test_rescue_plan_parser_preserves_policy_defaults():
    args = build_parser().parse_args(
        ["rescue-plan", "--source", "clip.mov", "--output-dir", "rescue-output"]
    )

    assert args.source == "clip.mov"
    assert args.output_dir == "rescue-output"
    assert args.save_plan is None
    assert args.policy == "local_content_preserving"


def test_rescue_render_parser_preserves_explicit_approval_boundary():
    args = build_parser().parse_args(
        [
            "rescue-render",
            "--plan",
            "plan.json",
            "--approve",
            "rotation:metadata",
            "--approve",
            "audio_loudness:primary",
        ]
    )

    assert args.plan == "plan.json"
    assert args.approve == ["rotation:metadata", "audio_loudness:primary"]


def test_rescue_inspect_parser_requires_receipt():
    args = build_parser().parse_args(["rescue-inspect", "--receipt", "receipt.json"])

    assert args.receipt == "receipt.json"


def test_python_client_plan_and_inspect_delegate_exact_contract(monkeypatch):
    monkeypatch.setattr(
        "mcp_video.rescue.plan_rescue",
        lambda *args, **kwargs: {"args": args, "kwargs": kwargs},
    )
    monkeypatch.setattr(
        "mcp_video.rescue.inspect_rescue",
        lambda *args, **kwargs: {"args": args, "kwargs": kwargs},
    )

    plan = Client().rescue_plan("clip.mov", "out", save_plan="out/plan.json")
    inspection = Client().rescue_inspect("out/receipt.json")

    assert plan == {
        "args": ("clip.mov", "out"),
        "kwargs": {"save_plan": "out/plan.json", "policy_id": "local_content_preserving"},
    }
    assert inspection == {"args": ("out/receipt.json",), "kwargs": {}}


def test_python_client_delegates_exact_contract(monkeypatch):
    monkeypatch.setattr(
        "mcp_video.rescue.render_rescue",
        lambda *args, **kwargs: {"args": args, "kwargs": kwargs},
    )

    result = Client().rescue_render(
        "plan.json",
        approved_repair_ids=["rotation:metadata"],
        cancel_file="cancel",
    )

    assert result["args"] == ("plan.json",)
    assert result["kwargs"] == {
        "approved_repair_ids": ["rotation:metadata"],
        "save_receipt": None,
        "resume_receipt": None,
        "cancel_file": "cancel",
        "keep_intermediates": False,
    }


def test_mcp_plan_returns_standard_result(monkeypatch):
    from mcp_video import server_tools_rescue

    monkeypatch.setattr(
        server_tools_rescue,
        "plan_rescue",
        lambda *args, **kwargs: {"status": "planned", "args": args, "kwargs": kwargs},
    )

    result = server_tools_rescue.video_rescue_plan("clip.mp4", "out")

    assert result["success"] is True
    assert result["status"] == "planned"
    assert result["args"] == ("clip.mp4", "out")


def test_mcp_render_returns_structured_rescue_failure(monkeypatch):
    from mcp_video import server_tools_rescue

    def fail(*args, **kwargs):
        raise rescue_error("verification failed", RESCUE_VERIFICATION_FAILED)

    monkeypatch.setattr(server_tools_rescue, "render_rescue", fail)

    result = server_tools_rescue.video_rescue_render("plan.json")

    assert result["success"] is False
    assert result["error"]["code"] == "rescue_verification_failed"


def test_cli_plan_json_returns_underlying_dict_unchanged(monkeypatch, capsys):
    from mcp_video.__main__ import main

    expected = {"status": "planned", "source": {"path": "clip.mov"}}
    monkeypatch.setattr("mcp_video.rescue.plan_rescue", lambda *args, **kwargs: expected)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mcp-video",
            "--format",
            "json",
            "rescue-plan",
            "--source",
            "clip.mov",
            "--output-dir",
            "out",
        ],
    )

    main()

    assert json.loads(capsys.readouterr().out) == expected


def test_cli_plan_text_names_unavailable_capabilities(monkeypatch, capsys):
    from mcp_video.__main__ import main

    monkeypatch.setattr(
        "mcp_video.rescue.plan_rescue",
        lambda *args, **kwargs: {
            "source": {"path": "clip.mov"},
            "safe_repairs": [{"id": "rotation:metadata"}],
            "recommendations": [],
            "unavailable_repairs": [],
            "blocked_repairs": [],
            "preview_artifacts": [],
            "estimate": {"seconds": 2.5, "confidence": "medium"},
            "capabilities": {
                "ffmpeg": {"available": True},
                "whisper": {"available": False},
                "whisper_models": {"base": {"available": False}},
                "filters": {"loudnorm": True, "afftdn": False},
            },
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["mcp-video", "rescue-plan", "--source", "clip.mov", "--output-dir", "out"],
    )

    main()

    output = capsys.readouterr().out
    assert "rotation:metadata" in output
    assert "whisper" in output
    assert "whisper_models.base" in output
    assert "filters.afftdn" in output


def test_cli_verification_failure_exits_nonzero(monkeypatch, capsys):
    from mcp_video.__main__ import main

    def fail(*args, **kwargs):
        raise rescue_error("verification failed", RESCUE_VERIFICATION_FAILED)

    monkeypatch.setattr("mcp_video.rescue.render_rescue", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        ["mcp-video", "--format", "json", "rescue-render", "--plan", "plan.json"],
    )

    with pytest.raises(SystemExit) as caught:
        main()

    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "rescue_verification_failed"


def test_cli_inspect_text_shows_integrity_privacy_and_resume(monkeypatch, capsys):
    from mcp_video.__main__ import main

    monkeypatch.setattr(
        "mcp_video.rescue.inspect_rescue",
        lambda *args, **kwargs: {
            "status": "completed",
            "integrity": {"all_matching": True},
            "verification": [{"passed": False, "name": "duration"}],
            "privacy": {"local_only": True},
            "resume": {"resumable": False},
            "cleanup": {"intermediates_retained": False},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["mcp-video", "rescue-inspect", "--receipt", "receipt.json"],
    )

    main()

    output = capsys.readouterr().out
    assert "Integrity" in output
    assert "Verification failures" in output
    assert "Local only" in output
    assert "Resumable" in output
