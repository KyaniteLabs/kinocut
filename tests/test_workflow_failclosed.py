"""Fail-closed + confinement regression tests (C1/C3/C4/C5, F1).

Depth checks beyond S2's type-confusion guard: arbitrary engine exceptions,
client dict-render rejection, cross-variant output collisions, execution-time
re-confinement, and a version-derived download User-Agent.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mcp_video.client import Client
from mcp_video.errors import MCPVideoError
from mcp_video.workflow import OP_ADAPTERS, OpAdapter, render_workflow
from mcp_video.workflow.executor import _resolve_ref_path


def _write_spec(directory: Path, spec: dict, name: str = "job.json") -> str:
    path = Path(directory) / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


# --- C1: any engine exception is wrapped fail-closed ------------------------


def _raising_resize(input_path=None, width=None, height=None, output_path=None, **_):
    raise RuntimeError(f"kaboom in {input_path}")


def test_engine_runtime_error_is_wrapped_and_receipt_written(sample_video, tmp_path, monkeypatch):
    shutil.copy(sample_video, tmp_path / "in.mp4")
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "in.mp4"}},
        "steps": [
            {
                "id": "trim",
                "op": "trim",
                "inputs": {"src": "@sources.a"},
                "params": {"start": 0, "duration": 1},
                "output": "@work/t.mp4",
            },
            {
                "id": "boom",
                "op": "resize",
                "inputs": {"src": "@work/t.mp4"},
                "params": {"width": 100, "height": 100},
                "output": "@outputs.o",
            },
        ],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    spec_path = _write_spec(tmp_path, spec)
    receipt_path = tmp_path / "receipt.json"

    boom = OpAdapter("resize", _raising_resize, input_key="src", engine_input_param="input_path")
    monkeypatch.setitem(OP_ADAPTERS, "resize", boom)

    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path, save_receipt=str(receipt_path))
    assert exc.value.code == "workflow_step_failed"
    assert exc.value.suggested_action is not None

    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "failed"
    boom_step = next(s for s in receipt["steps"] if s["id"] == "boom")
    assert boom_step["status"] == "failed"
    assert boom_step["error"]["code"] == "workflow_step_failed"
    assert str(tmp_path) not in boom_step["error"]["message"]  # workspace path sanitized

    # resume after restoring the real engine continues from the failed step
    monkeypatch.undo()
    resumed = render_workflow(spec_path, resume_receipt=str(receipt_path))
    assert resumed["status"] == "completed"
    assert (tmp_path / "out.mp4").is_file()


# --- C3: client rejects a dict spec for render ------------------------------


def test_client_workflow_render_rejects_dict_spec():
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "in.mp4"}},
        "steps": [{"id": "p", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        Client().workflow_render(spec)
    assert exc.value.code == "invalid_workflow_spec"


def test_client_validate_and_plan_still_accept_dict(tmp_path):
    spec = {
        "schema_version": 1,
        "name": "d",
        "sources": {"a": {"path": "in.mp4"}},
        "steps": [{"id": "p", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {},
    }
    assert Client().workflow_validate(spec)["valid"] is True
    assert Client().workflow_plan(spec)["receipt_kind"] == "workflow_plan"


# --- C4: cross-variant output collision fails closed ------------------------


def test_variant_output_collision_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "in.mp4"}},
        "steps": [{"id": "p", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {"o": {"path": "out.mp4"}},
        "variants": [
            {"id": "a", "overrides": {"outputs.o.path": "same/final.mp4"}},
            {"id": "b", "overrides": {"outputs.o.path": "same/final.mp4"}},
        ],
    }
    spec_path = _write_spec(tmp_path, spec)
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path, all_variants=True)
    assert exc.value.code == "invalid_workflow_variant"


def test_distinct_variant_outputs_do_not_collide(tmp_path):
    # Default auto-naming keeps outputs distinct; precheck must not false-positive.
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "in.mp4"}},
        "steps": [{"id": "p", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {"o": {"path": "out.mp4"}},
        "variants": [{"id": "a", "overrides": {}}, {"id": "b", "overrides": {}}],
    }
    from mcp_video.workflow.executor import _reject_variant_output_collisions

    _reject_variant_output_collisions(_write_spec(tmp_path, spec), ["a", "b"])  # no raise


# --- C5: execution-time re-confinement --------------------------------------


def test_resolve_ref_path_reconfines_escaping_symlink(tmp_path):
    workspace = Path(tmp_path)
    (workspace / "evil").symlink_to("/etc")  # symlink escaping the workspace
    with pytest.raises(MCPVideoError) as exc:
        _resolve_ref_path("evil/hosts", workspace, {}, {})
    assert exc.value.code == "unsafe_workflow_source"


def test_resolve_ref_path_allows_in_workspace_relative(tmp_path):
    workspace = Path(tmp_path)
    resolved = _resolve_ref_path("clip.mp4", workspace, {}, {})
    assert Path(resolved) == workspace / "clip.mp4"


# --- F1: download User-Agent derives from the package version ---------------


def test_download_user_agent_uses_package_version():
    import mcp_video.ai_engine.download as dl

    source = Path(dl.__file__).read_text(encoding="utf-8")
    assert 'f"mcp-video/{__version__}' in source
    assert "mcp-video/1.5.2" not in source
