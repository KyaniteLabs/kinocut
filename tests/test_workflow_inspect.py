"""Tests for the legacy-tolerant receipt inspector (``video_workflow_inspect``).

Covers all four receipt kinds this project emits — workflow render receipt,
dry-run ``workflow_plan`` artifact, ``layer_plan`` v2 (with ``receipt_kind``),
and a handcrafted legacy ``layer_plan`` v1 (NO ``receipt_kind``, kind inferred
from ``tool``) — plus the read-only integrity re-check, fail-closed handling of
malformed receipts, and MCP/CLI/Python parity. Real renders are ``@slow``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_video.client import Client
from mcp_video.server_tools_workflow import video_workflow_inspect
from mcp_video.workflow import inspect_receipt, plan_workflow, render_workflow


# --- Spec + workspace --------------------------------------------------------


def _linear_spec() -> dict:
    return {
        "schema_version": 1,
        "name": "captioned",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {"id": "probe", "op": "probe", "inputs": {"src": "@sources.hero"}},
            {
                "id": "trim",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0, "duration": 1},
                "output": "@work/trim.mp4",
            },
            {
                "id": "caption",
                "op": "add_text",
                "inputs": {"src": "@work/trim.mp4"},
                "params": {"text": "hi"},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }


def _write_spec(tmp_path: Path, spec: dict, name: str = "job.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _workspace(tmp_path: Path, sample_video: str) -> Path:
    (tmp_path / "input").mkdir(exist_ok=True)
    shutil.copy(sample_video, tmp_path / "input" / "hero.mp4")
    return tmp_path


def _legacy_layer_plan() -> dict:
    """A pre-bump v1 layer_plan receipt with NO ``receipt_kind`` (kind inferred)."""
    return {
        "schema_version": 1,
        "tool": "video_composite_layers",
        "spec_hash": "sha256:" + "0" * 64,
        "canvas": {"width": 1920, "height": 1080},
        "layers": [
            {
                "id": "bg",
                "type": "video",
                "resolved_src": "input/bg.mp4",
                "source_hash": "sha256:" + "a" * 64,
                "opacity": 1.0,
                "position": {"x": 0, "y": 0},
                "transform": {},
                "timing": {},
                "mask": None,
                "mask_hash": None,
                "blend": "normal",
                "color": None,
                "input_index": 0,
                "mask_input_index": None,
            }
        ],
        "filtergraph_summary": ["canvas normalized to rgba"],
        "filtergraph_hash": "sha256:" + "b" * 64,
        "output_path": "output/composite.mp4",
        "output_hash": None,
        "features": {
            "layer_types": ["video"],
            "transforms": False,
            "timing_windows": False,
            "masks": False,
            "blend_modes": ["normal"],
        },
        "render_determinism_scope": "input/spec/filtergraph/output hashes are deterministic",
    }


def _v2_layer_plan() -> dict:
    """A forward-looking v2 layer_plan with the ``receipt_kind`` discriminator."""
    plan = _legacy_layer_plan()
    plan["schema_version"] = 2
    plan["receipt_kind"] = "layer_plan"
    return plan


def _write_json(tmp_path: Path, data: dict, name: str) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# --- Kind coverage: all four receipt kinds -----------------------------------


@pytest.mark.slow
def test_inspect_workflow_render_receipt(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    render_workflow(_write_spec(ws, _linear_spec()), save_receipt=str(ws / "receipt.json"))

    report = inspect_receipt(str(ws / "receipt.json"))

    assert report["kind"] == "workflow"
    assert report["schema_version"] == 1
    assert report["tool"] == "video_workflow_render"
    assert report["versions"]["mcp_video"]
    assert report["status"]["overall"] == "completed"
    assert report["status"]["failed_step"] is None
    summary = report["integrity"]["summary"]
    # Source + final output re-hash and MATCH; the two @work intermediates read as CLEANED, not missing.
    assert summary["mismatched"] == 0
    assert summary["missing"] == 0
    assert summary["matched"] >= 2
    assert summary["cleaned"] >= 1
    assert report["outputs"][0]["path"] == "output/final.mp4"
    assert report["human_review"] == []  # a clean, complete run raises no flags


def test_inspect_workflow_plan_artifact(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    plan_workflow(_write_spec(ws, _linear_spec()), save_plan=str(ws / "plan.json"))

    report = inspect_receipt(str(ws / "plan.json"))

    assert report["kind"] == "workflow_plan"
    assert report["status"]["overall"] == "planned"
    assert all(out["output_hash"] is None for out in report["outputs"])
    assert any("dry-run plan" in limit for limit in report["known_limitations"])


def test_inspect_layer_plan_v2_with_receipt_kind(tmp_path):
    report = inspect_receipt(_write_json(tmp_path, _v2_layer_plan(), "v2.json"))

    assert report["kind"] == "layer_plan"
    assert report["schema_version"] == 2  # inferred from the field, NOT hardcoded to v1
    assert report["tool"] == "video_composite_layers"
    assert report["outputs"][0]["path"] == "output/composite.mp4"


def test_inspect_legacy_layer_plan_without_receipt_kind(tmp_path):
    report = inspect_receipt(_write_json(tmp_path, _legacy_layer_plan(), "legacy.json"))

    assert report["kind"] == "layer_plan"  # inferred from tool == video_composite_layers (§5d)
    assert report["schema_version"] == 1
    assert any("inferred" in note for note in report["human_review"])
    assert any("layer_plan receipts carry no per-step" in limit for limit in report["known_limitations"])


def test_inspect_receipt_kind_less_and_tool_less_defaults_to_layer_plan(tmp_path):
    report = inspect_receipt(_write_json(tmp_path, {"schema_version": 9, "layers": []}, "bare.json"))

    assert report["kind"] == "layer_plan"  # §5d default when neither receipt_kind nor a known tool is present


# --- Integrity re-check ------------------------------------------------------


@pytest.mark.slow
def test_inspect_detects_tampered_output(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    render_workflow(_write_spec(ws, _linear_spec()), save_receipt=str(ws / "receipt.json"))
    (ws / "output" / "final.mp4").write_bytes(b"tampered final output")

    report = inspect_receipt(str(ws / "receipt.json"))

    assert report["integrity"]["summary"]["mismatched"] >= 1
    assert any("no longer match" in note for note in report["human_review"])


# --- Fail-closed -------------------------------------------------------------


def test_inspect_malformed_receipt_fails_closed(tmp_path):
    from mcp_video.errors import MCPVideoError

    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(MCPVideoError) as exc:
        inspect_receipt(str(bad))
    assert exc.value.code == "invalid_workflow_receipt"


def test_inspect_non_object_receipt_fails_closed(tmp_path):
    from mcp_video.errors import MCPVideoError

    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(MCPVideoError) as exc:
        inspect_receipt(str(arr))
    assert exc.value.code == "invalid_workflow_receipt"


# --- Privacy -----------------------------------------------------------------


@pytest.mark.slow
def test_inspect_output_is_workspace_relative(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    render_workflow(_write_spec(ws, _linear_spec()), save_receipt=str(ws / "receipt.json"))

    text = json.dumps(inspect_receipt(str(ws / "receipt.json")))

    assert str(ws) not in text
    assert "/Users/" not in text
    assert "/home/" not in text


# --- MCP / CLI / Python parity -----------------------------------------------


def test_inspect_mcp_envelope(tmp_path):
    result = video_workflow_inspect(_write_json(tmp_path, _v2_layer_plan(), "v2.json"))

    assert result["success"] is True
    assert result["kind"] == "layer_plan"


def test_inspect_mcp_error_envelope(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("nope", encoding="utf-8")
    result = video_workflow_inspect(str(bad))

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_workflow_receipt"


def test_inspect_cli(tmp_path):
    receipt_path = _write_json(tmp_path, _v2_layer_plan(), "v2.json")
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_video", "--format", "json", "workflow-inspect", "--receipt", receipt_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["kind"] == "layer_plan"


def test_inspect_cli_text_mode(tmp_path):
    receipt_path = _write_json(tmp_path, _legacy_layer_plan(), "legacy.json")
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_video", "workflow-inspect", "--receipt", receipt_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Workflow Inspect" in completed.stdout


def test_inspect_client(tmp_path):
    report = Client().workflow_inspect(_write_json(tmp_path, _v2_layer_plan(), "v2.json"))

    assert report["kind"] == "layer_plan"
    assert report["schema_version"] == 2


def test_inspect_parity_across_surfaces(tmp_path):
    receipt_path = _write_json(tmp_path, _legacy_layer_plan(), "legacy.json")

    direct = inspect_receipt(receipt_path)
    envelope = video_workflow_inspect(receipt_path)
    client = Client().workflow_inspect(receipt_path)

    assert direct["kind"] == envelope["kind"] == client["kind"] == "layer_plan"
    assert direct["status"]["overall"] == client["status"]["overall"]


def test_inspect_is_introspectable():
    info = Client().inspect("workflow_inspect")

    assert info["category"] == "workflow"
    assert "receipt" in info["parameters"]
