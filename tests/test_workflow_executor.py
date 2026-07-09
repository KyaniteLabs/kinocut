"""Tests for the workflow render executor + receipt (video_workflow_render).

Real renders are marked ``@pytest.mark.slow`` (they shell out to FFmpeg).
Workspaces live under ``tmp_path`` so every path in a receipt stays
workspace-relative (privacy gate).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import mcp_video
from mcp_video.client import Client
from mcp_video.engine import probe
from mcp_video.errors import MCPVideoError
from mcp_video.server_tools_workflow import video_workflow_render
from mcp_video.workflow import plan_workflow, render_workflow

_RECEIPT_FIELDS = {
    "schema_version",
    "receipt_kind",
    "tool",
    "versions",
    "spec_hash",
    "workflow",
    "sources",
    "steps",
    "outputs",
    "work_dir",
    "cleanup_manifest",
    "resume_cursor",
    "feature_flags",
    "warnings",
    "status",
    "render_determinism_scope",
}

_STEP_FIELDS = {
    "id",
    "op",
    "status",
    "inputs",
    "input_hashes",
    "output",
    "output_hash",
    "started_at",
    "ended_at",
}


# --- Spec builders -----------------------------------------------------------


def _linear_spec() -> dict:
    """probe -> trim -> resize -> add_text, ending at a declared output."""
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
                "params": {"start": 0, "duration": 1},
                "output": "@work/hero_trim.mp4",
            },
            {
                "id": "small",
                "op": "resize",
                "inputs": {"src": "@work/hero_trim.mp4"},
                "params": {"width": 320, "height": 240},
                "output": "@work/hero_small.mp4",
            },
            {
                "id": "caption",
                "op": "add_text",
                "inputs": {"src": "@work/hero_small.mp4"},
                "params": {"text": "Watch this"},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }


def _merge_spec() -> dict:
    """Two trims of one source merged (multi-input hashing)."""
    return {
        "schema_version": 1,
        "name": "merged-pair",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {
                "id": "a",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0, "duration": 1},
                "output": "@work/a.mp4",
            },
            {
                "id": "b",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 1, "duration": 1},
                "output": "@work/b.mp4",
            },
            {
                "id": "join",
                "op": "merge",
                "inputs": {"srcs": ["@work/a.mp4", "@work/b.mp4"]},
                "output": "@outputs.out",
            },
        ],
        "outputs": {"out": {"path": "output/merged.mp4"}},
    }


def _probe_only_spec() -> dict:
    return {
        "schema_version": 1,
        "name": "inspect-only",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [{"id": "probe-hero", "op": "probe", "inputs": {"src": "@sources.hero"}}],
        "outputs": {},
    }


def _write_spec(tmp_path: Path, spec: dict, name: str = "job.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _workspace(tmp_path: Path, sample_video: str) -> Path:
    """Populate input/hero.mp4 inside the tmp workspace root."""
    (tmp_path / "input").mkdir(exist_ok=True)
    shutil.copy(sample_video, tmp_path / "input" / "hero.mp4")
    return tmp_path


# --- E2E real render ---------------------------------------------------------


@pytest.mark.slow
def test_real_render_produces_output_and_complete_receipt(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _linear_spec())

    receipt = render_workflow(spec_path, save_receipt=str(ws / "receipt.json"))

    # Output exists and is probe-able as a real video.
    final = ws / "output" / "final.mp4"
    assert final.is_file()
    info = probe(str(final))
    assert info.duration > 0
    assert info.width == 320 and info.height == 240

    # Top-level + per-step field sets exactly match the §5a schema.
    assert set(receipt) == _RECEIPT_FIELDS
    assert receipt["schema_version"] == 1
    assert receipt["receipt_kind"] == "workflow"
    assert receipt["tool"] == "video_workflow_render"
    assert receipt["status"] == "completed"
    assert receipt["workflow"] == {"name": "captioned-vertical-short", "variant": None}
    assert receipt["spec_hash"].startswith("sha256:")
    assert "hashes are deterministic" in receipt["render_determinism_scope"]
    for step in receipt["steps"]:
        assert set(step) == _STEP_FIELDS

    # Every consumed input carries a REAL sha256; render outputs are hashed.
    steps = {step["id"]: step for step in receipt["steps"]}
    for step in receipt["steps"]:
        for value in step["input_hashes"].values():
            assert value.startswith("sha256:")
    assert steps["trim-hero"]["output_hash"].startswith("sha256:")
    assert steps["small"]["output_hash"].startswith("sha256:")
    assert steps["caption"]["output_hash"].startswith("sha256:")
    assert receipt["outputs"] == [
        {"id": "master", "path": "output/final.mp4", "output_hash": steps["caption"]["output_hash"]}
    ]

    # ISO-8601 UTC timestamps on executed steps.
    assert steps["caption"]["started_at"].endswith("+00:00")
    assert steps["caption"]["ended_at"].endswith("+00:00")


@pytest.mark.slow
def test_probe_step_records_no_output(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    receipt = render_workflow(_write_spec(ws, _linear_spec()))

    probe_step = next(s for s in receipt["steps"] if s["op"] == "probe")
    assert probe_step["status"] == "completed"
    assert probe_step["output"] is None
    assert probe_step["output_hash"] is None
    assert probe_step["input_hashes"]["src"].startswith("sha256:")


@pytest.mark.slow
def test_render_versions_match_plan_versions(tmp_path, sample_video):
    """Plan + render report the identical shared versions object."""
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _linear_spec())

    render_versions = render_workflow(spec_path)["versions"]
    plan_versions = plan_workflow(spec_path)["versions"]

    assert render_versions == plan_versions
    assert render_versions["mcp_video"] == mcp_video.__version__
    assert render_versions["ffmpeg"]


# --- Cleanup + @work isolation ----------------------------------------------


@pytest.mark.slow
def test_cleanup_removes_only_manifest_files_inside_run_dir(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    receipt = render_workflow(_write_spec(ws, _linear_spec()))

    manifest = receipt["cleanup_manifest"]
    assert manifest["cleaned"] is True
    assert manifest["policy"] == "clean-on-success"
    assert len(manifest["intermediates"]) == 2
    for rel in manifest["intermediates"]:
        assert rel.startswith(receipt["work_dir"] + "/")
        assert not (ws / rel).exists()  # cleaned on success
    # Final output survives cleanup; only @work intermediates are removed.
    assert (ws / "output" / "final.mp4").is_file()


@pytest.mark.slow
def test_work_dir_is_unique_across_runs(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _probe_only_spec())

    first = render_workflow(spec_path)["work_dir"]
    second = render_workflow(spec_path)["work_dir"]

    assert first != second
    assert first.startswith("work/")
    assert second.startswith("work/")


# --- Multi-input (merge) hashing --------------------------------------------


@pytest.mark.slow
def test_merge_hashes_every_input_element(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    receipt = render_workflow(_write_spec(ws, _merge_spec()))

    assert receipt["status"] == "completed"
    assert (ws / "output" / "merged.mp4").is_file()
    join = next(s for s in receipt["steps"] if s["id"] == "join")
    assert set(join["input_hashes"]) == {"srcs[0]", "srcs[1]"}
    for value in join["input_hashes"].values():
        assert value.startswith("sha256:")


# --- Fail-closed mid-job -----------------------------------------------------


def _failing_spec() -> dict:
    return {
        "schema_version": 1,
        "name": "boom",
        "sources": {"good": {"path": "input/hero.mp4"}, "bad": {"path": "input/bad.mp4"}},
        "steps": [
            {
                "id": "ok",
                "op": "trim",
                "inputs": {"src": "@sources.good"},
                "params": {"start": 0, "duration": 1},
                "output": "@work/ok.mp4",
            },
            {
                "id": "boom",
                "op": "resize",
                "inputs": {"src": "@sources.bad"},
                "params": {"width": 100, "height": 100},
                "output": "@work/x.mp4",
            },
            {
                "id": "never",
                "op": "add_text",
                "inputs": {"src": "@work/x.mp4"},
                "params": {"text": "hi"},
                "output": "@outputs.out",
            },
        ],
        "outputs": {"out": {"path": "output/out.mp4"}},
    }


@pytest.mark.slow
def test_failed_step_raises_and_writes_consistent_receipt(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    (ws / "input" / "bad.mp4").write_bytes(b"not a real video at all")
    spec_path = _write_spec(ws, _failing_spec())
    receipt_path = ws / "receipt.json"

    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path, save_receipt=str(receipt_path))
    assert exc.value.code  # engine MCPVideoError surfaced

    # Receipt still written despite the raise.
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    statuses = {s["id"]: s["status"] for s in receipt["steps"]}
    assert statuses == {"ok": "completed", "boom": "failed", "never": "pending"}

    failed = next(s for s in receipt["steps"] if s["id"] == "boom")
    assert failed["error"]["code"] == exc.value.code
    assert "suggested_action" in failed["error"]

    # Intermediates KEPT on failure so a later resume can continue.
    manifest = receipt["cleanup_manifest"]
    assert manifest["cleaned"] is False
    assert manifest["intermediates"] == [f"{receipt['work_dir']}/mcp_video_ok.mp4"]
    assert (ws / manifest["intermediates"][0]).is_file()

    # Resume cursor points at the failed step (Story-4-ready).
    assert receipt["resume_cursor"] == {"last_completed_step": "ok", "next_step": "boom"}


def test_render_fails_closed_on_invalid_spec(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "explode", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsupported_workflow_op"


# --- Privacy: workspace-relative paths only ----------------------------------


@pytest.mark.slow
def test_receipt_paths_are_workspace_relative(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    receipt = render_workflow(_write_spec(ws, _linear_spec()))
    text = json.dumps(receipt)

    assert str(ws) not in text
    assert "/Users/" not in text
    assert "/home/" not in text
    for source in receipt["sources"]:
        assert not source["resolved"].startswith("/")
    for output in receipt["outputs"]:
        assert not output["path"].startswith("/")
    assert not receipt["work_dir"].startswith("/")
    for rel in receipt["cleanup_manifest"]["intermediates"]:
        assert not rel.startswith("/")


# --- MCP envelope ------------------------------------------------------------


@pytest.mark.slow
def test_mcp_tool_returns_success_envelope(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    result = video_workflow_render(_write_spec(ws, _probe_only_spec()))

    assert result["success"] is True
    assert result["receipt_kind"] == "workflow"


def test_mcp_tool_returns_structured_error_for_invalid_spec(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "explode", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    result = video_workflow_render(_write_spec(tmp_path, spec))

    assert result["success"] is False
    assert result["error"]["code"] == "unsupported_workflow_op"
    assert "suggested_action" in result["error"]


@pytest.mark.slow
def test_mcp_tool_error_envelope_for_failing_render(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    (ws / "input" / "bad.mp4").write_bytes(b"not a real video at all")
    result = video_workflow_render(_write_spec(ws, _failing_spec()))

    assert result["success"] is False
    assert result["error"]["code"]


# --- CLI ---------------------------------------------------------------------


@pytest.mark.slow
def test_cli_workflow_render_json_and_save_receipt(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _linear_spec())
    receipt_path = ws / "cli_receipt.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_video",
            "--format",
            "json",
            "workflow-render",
            "--spec",
            spec_path,
            "--save-receipt",
            str(receipt_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["receipt_kind"] == "workflow"
    assert payload["status"] == "completed"
    assert receipt_path.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == "completed"


@pytest.mark.slow
def test_cli_workflow_render_text_mode(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _linear_spec())

    completed = subprocess.run(
        [sys.executable, "-m", "mcp_video", "workflow-render", "--spec", spec_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Workflow Render" in completed.stdout


# --- Python client -----------------------------------------------------------


@pytest.mark.slow
def test_client_workflow_render_path(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    receipt = Client().workflow_render(_write_spec(ws, _linear_spec()))

    assert receipt["receipt_kind"] == "workflow"
    assert receipt["status"] == "completed"
    assert receipt["workflow"]["name"] == "captioned-vertical-short"


def test_client_workflow_render_dict_missing_source_fails_closed():
    """A dict spec resolves in an ephemeral workspace; a missing source fails closed."""
    with pytest.raises(MCPVideoError):
        Client().workflow_render(_linear_spec())


def test_client_workflow_render_is_introspectable():
    info = Client().inspect("workflow_render")

    assert info["category"] == "workflow"
    assert "spec" in info["parameters"]
