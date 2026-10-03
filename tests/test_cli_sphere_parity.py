"""Operator journeys retain source identity and explicit 360 review gates."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kinocut.cli.handlers_intent import handle_intent_commands
from kinocut.cli.parser import build_parser
from kinocut.client.estimates import ClientEstimatesMixin
from kinocut.errors import MCPVideoError
from kinocut.te import estimate_operation, propose_sphere_plan


def _dispatch(argv: list[str], capsys: pytest.CaptureFixture) -> dict:
    args = build_parser().parse_args(argv)
    assert handle_intent_commands(args, use_json=True)
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def sphere_source(tmp_path: Path) -> Path:
    source = tmp_path / "sphere.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x160:d=0.2", "-pix_fmt", "yuv420p", str(source)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return source


def test_cli_goal_proposes_source_bound_sphere_without_render(sphere_source, tmp_path, capsys):
    payload = _dispatch(
        ["intent", "reformat_vertical", "--goal", "desk 360 split 9:16", "--source", str(sphere_source)], capsys
    )
    assert payload["next_action"] == "review_then_sphere_render"
    assert payload["cutfile"]
    plan = payload["sphere_plan"]
    assert plan["status"] == "proposed"
    assert plan["source"]["sha256"] == "sha256:" + hashlib.sha256(sphere_source.read_bytes()).hexdigest()
    assert plan["output"]["aspect"] == "9:16"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sphere.mp4"]


def test_non_sphere_goal_and_existing_intent_routing(capsys):
    normal = _dispatch(["intent", "reformat_vertical"], capsys)
    goal = _dispatch(["intent", "reformat_vertical", "--goal", "vertical short"], capsys)
    assert "cutfile" not in normal
    assert goal["next_action"] == "review_then_cutfile_render"
    assert "sphere_plan" not in goal
    catalog = _dispatch(["intent", "--list", "--goal", "desk 360 split 9:16"], capsys)
    assert catalog["artifact_kind"] == "intent_catalog"
    with pytest.raises(MCPVideoError):
        _dispatch(["intent", "unknown_verb", "--goal", "vertical short"], capsys)


def test_invalid_source_preserves_cutfile_and_reports_sphere_error(tmp_path, capsys):
    payload = _dispatch(
        ["intent", "reformat_vertical", "--goal", "desk 360 split 9:16", "--source", str(tmp_path / "raw.insv")],
        capsys,
    )
    assert payload["next_action"] == "review_then_cutfile_render"
    assert payload["sphere_plan_error"]["code"] == "not_insv_export"
    assert "sphere_plan" not in payload


def test_review_requires_explicit_accept_and_preserves_rejected_plan(sphere_source, tmp_path, capsys):
    plan = propose_sphere_plan(str(sphere_source))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    rejected = _dispatch(["review-decide", str(path), "reject", "--output", str(tmp_path / "out.mp4")], capsys)
    assert rejected["status"] == "rejected"
    assert not (tmp_path / "out.mp4").exists()
    approved = _dispatch(["review-decide", str(path), "accept"], capsys)
    assert approved["status"] == "approved"
    assert "sphere_render" not in approved
    assert json.loads(path.read_text())["status"] == "proposed"
    with pytest.raises(MCPVideoError) as error:
        _dispatch(["review-decide", str(path), "revise"], capsys)
    assert error.value.code == "invalid_sphere_decision"


def test_review_render_detects_source_change_before_writing(sphere_source, tmp_path, capsys):
    plan = propose_sphere_plan(str(sphere_source))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    sphere_source.write_bytes(sphere_source.read_bytes() + b"changed")
    output = tmp_path / "out.mp4"
    with pytest.raises(MCPVideoError) as error:
        _dispatch(["review-decide", str(path), "accept", "--output", str(output)], capsys)
    assert error.value.code == "source_identity_changed"
    assert not output.exists()


def test_review_render_forwards_only_explicitly_accepted_plan(sphere_source, tmp_path, capsys, monkeypatch):
    from kinocut import te

    plan = propose_sphere_plan(str(sphere_source))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    output = tmp_path / "out.mp4"
    calls = []

    def render(approved, destination):
        calls.append((approved, destination))
        assert approved["status"] == "approved"
        assert approved["source"] == plan["source"]
        return {"output_path": destination, "quality_gate": {"passed": True}}

    monkeypatch.setattr(te, "render_sphere_plan", render)
    _dispatch(["review-decide", str(path), "reject", "--output", str(output)], capsys)
    assert not calls
    result = _dispatch(["review-decide", str(path), "accept", "--output", str(output)], capsys)
    assert len(calls) == 1
    assert calls[0][1] == str(output)
    assert result["sphere_render"]["output_path"] == str(output)
    assert plan["status"] == "proposed"


def test_client_estimates_use_shared_local_oracle():
    result = ClientEstimatesMixin().estimate_operation("trim", 10, complexity=2)
    assert result == estimate_operation("trim", duration_seconds=10, complexity=2)
    assert result["currency"] is None
    assert result["dry_run"] is True
    with pytest.raises(MCPVideoError):
        ClientEstimatesMixin().estimate_operation("trim", -1)
