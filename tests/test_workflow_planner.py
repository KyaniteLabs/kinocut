"""Tests for the workflow dry-run planner (video_workflow_plan)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import mcp_video
from mcp_video.client import Client
from mcp_video.errors import MCPVideoError
from mcp_video.server_tools_workflow import video_workflow_plan
from mcp_video.workflow import plan_workflow


def _flagship_spec() -> dict:
    return {
        "schema_version": 1,
        "name": "captioned-vertical-short",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {"id": "probe-hero", "op": "probe", "inputs": {"src": "@sources.hero"}},
            {
                "id": "trim-hero",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0, "duration": 2},
                "output": "@work/hero_trim.mp4",
            },
            {
                "id": "vertical",
                "op": "resize",
                "inputs": {"src": "@work/hero_trim.mp4"},
                "params": {"width": 1080, "height": 1920},
                "output": "@work/hero_vertical.mp4",
            },
            {
                "id": "caption",
                "op": "add_text",
                "inputs": {"src": "@work/hero_vertical.mp4"},
                "params": {"text": "Watch this"},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
        "variants": [{"id": "square", "overrides": {"steps.vertical.params": {"width": 1080, "height": 1080}}}],
    }


def _write_spec(tmp_path: Path, spec: dict) -> str:
    path = tmp_path / "job.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _spec_with_real_source(tmp_path: Path, sample_video: str) -> str:
    """Write the flagship spec plus a real source file inside the workspace."""
    (tmp_path / "input").mkdir()
    shutil.copy(sample_video, tmp_path / "input" / "hero.mp4")
    return _write_spec(tmp_path, _flagship_spec())


# --- Plan artifact structure -------------------------------------------------


def test_plan_top_level_fields_trace_to_receipt_schema(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))

    assert set(plan) == {
        "schema_version",
        "receipt_kind",
        "tool",
        "versions",
        "spec_hash",
        "workflow",
        "sources",
        "steps",
        "outputs",
        "variants",
        "warnings",
        "render_determinism_scope",
    }
    assert plan["schema_version"] == 1
    assert plan["receipt_kind"] == "workflow_plan"
    assert plan["tool"] == "video_workflow_plan"
    assert plan["workflow"] == {"name": "captioned-vertical-short", "variant": None}
    assert plan["spec_hash"].startswith("sha256:")
    assert "hashes are deterministic" in plan["render_determinism_scope"]


def test_plan_versions_report_live_package_and_ffmpeg(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))

    assert plan["versions"]["mcp_video"] == mcp_video.__version__
    assert isinstance(plan["versions"]["ffmpeg"], str)
    assert plan["versions"]["ffmpeg"]


def test_plan_ordered_operation_list_and_dry_run_step_state(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))

    assert [step["op"] for step in plan["steps"]] == ["probe", "trim", "resize", "add_text"]
    assert [step["id"] for step in plan["steps"]] == ["probe-hero", "trim-hero", "vertical", "caption"]
    for step in plan["steps"]:
        assert step["status"] == "pending"
        assert step["output_hash"] is None


def test_plan_probes_and_hashes_existing_source(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))

    (hero,) = plan["sources"]
    assert hero["id"] == "hero"
    assert hero["resolved"] == "input/hero.mp4"
    assert hero["source_hash"].startswith("sha256:")
    assert hero["probe"]["duration"] > 0
    assert hero["probe"]["resolution"] == "640x480"
    assert hero["probe"]["codec"]
    assert plan["warnings"] == []


def test_plan_step_input_hashes_present_for_sources_null_for_work(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))
    steps = {step["id"]: step for step in plan["steps"]}
    source_hash = plan["sources"][0]["source_hash"]

    assert steps["probe-hero"]["input_hashes"] == {"src": source_hash}
    assert steps["trim-hero"]["input_hashes"] == {"src": source_hash}
    # @work refs are intermediates that do not exist at plan time.
    assert steps["vertical"]["input_hashes"] == {"src": None}
    assert steps["caption"]["input_hashes"] == {"src": None}


def test_plan_output_intents_have_no_hash_until_render(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))

    assert plan["outputs"] == [{"id": "master", "path": "output/final.mp4", "output_hash": None}]


def test_plan_variant_expansion_summary(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))

    assert plan["variants"] == [{"id": "square"}]


# --- Missing / unprobeable sources → warnings, not errors --------------------


def test_plan_warns_for_missing_source(tmp_path):
    spec = {
        "schema_version": 1,
        "name": "ghost",
        "sources": {"ghost": {"path": "input/ghost.mp4"}},
        "steps": [{"id": "probe-ghost", "op": "probe", "inputs": {"src": "@sources.ghost"}}],
        "outputs": {},
    }
    plan = plan_workflow(_write_spec(tmp_path, spec))

    (ghost,) = plan["sources"]
    assert ghost["source_hash"] is None
    assert ghost["probe"] is None
    assert any(w["code"] == "source_missing" and w["source"] == "ghost" for w in plan["warnings"])


def test_plan_warns_for_existing_but_unprobeable_source(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "hero.mp4").write_bytes(b"not a real video")
    spec = {
        "schema_version": 1,
        "name": "junk",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [{"id": "probe-hero", "op": "probe", "inputs": {"src": "@sources.hero"}}],
        "outputs": {},
    }
    plan = plan_workflow(_write_spec(tmp_path, spec))

    (hero,) = plan["sources"]
    assert hero["source_hash"].startswith("sha256:")  # file exists → hashable
    assert hero["probe"] is None
    assert any(w["code"] == "source_unprobeable" for w in plan["warnings"])


# --- Fail-closed on invalid spec (planner validates first) -------------------


def test_plan_fails_closed_on_invalid_spec(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "speed", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        plan_workflow(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsupported_workflow_op"


# --- Dry-run purity: no media written ----------------------------------------


def test_plan_is_pure_dry_run_writes_no_media(tmp_path, sample_video):
    spec_path = _spec_with_real_source(tmp_path, sample_video)
    before = {str(p) for p in tmp_path.rglob("*")}

    plan_workflow(spec_path)

    after = {str(p) for p in tmp_path.rglob("*")}
    assert before == after
    assert not (tmp_path / "output" / "final.mp4").exists()


def test_plan_save_plan_roundtrip(tmp_path, sample_video):
    spec_path = _spec_with_real_source(tmp_path, sample_video)
    plan_path = tmp_path / "plan.json"

    returned = plan_workflow(spec_path, save_plan=str(plan_path))

    assert plan_path.is_file()
    on_disk = json.loads(plan_path.read_text(encoding="utf-8"))
    assert on_disk == returned
    # Written like the compositor receipt: pretty + stable ordering.
    text = plan_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text == json.dumps(returned, indent=2, sort_keys=True) + "\n"


# --- Privacy: workspace-relative only, no home/absolute paths -----------------


def test_plan_artifact_has_no_absolute_or_home_paths(tmp_path, sample_video):
    plan = plan_workflow(_spec_with_real_source(tmp_path, sample_video))
    text = json.dumps(plan)

    assert str(tmp_path) not in text
    assert "/Users/" not in text
    assert "/home/" not in text
    for source in plan["sources"]:
        assert not source["resolved"].startswith("/")
    for output in plan["outputs"]:
        assert not output["path"].startswith("/")


# --- MCP envelope + cross-surface parity -------------------------------------


def test_mcp_tool_returns_success_envelope_for_valid_spec(tmp_path, sample_video):
    result = video_workflow_plan(_spec_with_real_source(tmp_path, sample_video))

    assert result["success"] is True
    assert result["receipt_kind"] == "workflow_plan"


def test_mcp_tool_returns_structured_error_for_invalid_spec(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "explode", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    result = video_workflow_plan(_write_spec(tmp_path, spec))

    assert result["success"] is False
    assert result["error"]["code"] == "unsupported_workflow_op"
    assert "suggested_action" in result["error"]


def _cli_plan(spec_path: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_video", "--format", "json", "workflow-plan", "--spec", spec_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_cli_workflow_plan_text_mode(tmp_path, sample_video):
    result = subprocess.run(
        [sys.executable, "-m", "mcp_video", "workflow-plan", "--spec", _spec_with_real_source(tmp_path, sample_video)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Workflow Plan" in result.stdout
    assert "No media rendered" in result.stdout


def test_cli_workflow_plan_save_plan(tmp_path, sample_video):
    spec_path = _spec_with_real_source(tmp_path, sample_video)
    plan_path = tmp_path / "cli_plan.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_video",
            "workflow-plan",
            "--spec",
            spec_path,
            "--save-plan",
            str(plan_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert plan_path.is_file()
    assert json.loads(plan_path.read_text(encoding="utf-8"))["receipt_kind"] == "workflow_plan"


def test_client_workflow_plan_path_and_dict(tmp_path, sample_video):
    spec_path = _spec_with_real_source(tmp_path, sample_video)
    plan = Client().workflow_plan(spec_path)

    assert plan["receipt_kind"] == "workflow_plan"
    assert plan["workflow"]["name"] == "captioned-vertical-short"

    # dict spec resolves in an ephemeral workspace → source missing warning, no crash.
    dict_plan = Client().workflow_plan(_flagship_spec())
    assert dict_plan["receipt_kind"] == "workflow_plan"
    assert any(w["code"] == "source_missing" for w in dict_plan["warnings"])


def test_client_workflow_plan_is_introspectable():
    info = Client().inspect("workflow_plan")

    assert info["category"] == "workflow"
    assert "spec" in info["parameters"]


def test_mcp_cli_and_client_return_identical_plans(tmp_path, sample_video):
    spec_path = _spec_with_real_source(tmp_path, sample_video)

    mcp_result = video_workflow_plan(spec_path)
    mcp_plan = {key: value for key, value in mcp_result.items() if key != "success"}
    client_plan = Client().workflow_plan(spec_path)
    cli_plan = _cli_plan(spec_path)

    assert mcp_plan == client_plan
    assert cli_plan == client_plan
