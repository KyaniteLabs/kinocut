"""Pre-release security-hardening regression tests.

Covers the four review lanes' HIGH/blocking findings on the workflow surface:
  * S1 — artifact write-path validation (plan / receipt / receipt-dir / variants)
  * S2 — param VALUE validation at the workflow layer + engine sink hardening
  * S3 — resource caps (step / variant counts, resize dimension bound)
  * C2 — `font` excluded from the add_text workflow op (path existence oracle)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_video.engine_resize import resize
from mcp_video.engine_text import add_text
from mcp_video.errors import MCPVideoError
from mcp_video.limits import MAX_RESOLUTION, MAX_WORKFLOW_STEPS, MAX_WORKFLOW_VARIANTS
from mcp_video.workflow import plan_workflow, render_workflow, validate_workflow_spec
from mcp_video.workflow.executor import _ensure_receipt_dir, _write_receipt
from mcp_video.workflow.planner import _write_plan


def _write_spec(directory: Path, spec: dict, name: str = "job.json") -> str:
    path = Path(directory) / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _single_step_spec(op: str, params: dict, output: str | None = "@outputs.o") -> dict:
    step: dict = {"id": "s1", "op": op, "inputs": {"src": "@sources.a"}, "params": params}
    if output is not None:
        step["output"] = output
    return {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [step],
        "outputs": {"o": {"path": "out.mp4"}},
    }


def _probe_spec() -> dict:
    return {
        "schema_version": 1,
        "name": "t",
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "p", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {},
    }


# --- S1: artifact write-path validation -------------------------------------


def _bad_artifact_targets(tmp_path: Path) -> dict[str, str]:
    non_json = tmp_path / "target.txt"
    non_json.write_text("not an artifact", encoding="utf-8")
    return {
        "absolute_system_path": "/etc/mcp_video_evil_artifact.json",
        "dotdot_escape": str(tmp_path / ".." / "escape.json"),
        "sensitive_dotfile": str(Path.home() / ".ssh" / "mcp_video_evil.json"),
        "overwrite_non_json": str(non_json),
    }


@pytest.mark.parametrize("case", ["absolute_system_path", "dotdot_escape", "sensitive_dotfile", "overwrite_non_json"])
def test_write_plan_fails_closed_on_unsafe_target(tmp_path, case):
    target = _bad_artifact_targets(tmp_path)[case]
    with pytest.raises(MCPVideoError):
        _write_plan({"receipt_kind": "workflow_plan"}, target)
    assert not Path(target).is_file() or case == "overwrite_non_json"


@pytest.mark.parametrize("case", ["absolute_system_path", "dotdot_escape", "sensitive_dotfile", "overwrite_non_json"])
def test_write_receipt_fails_closed_on_unsafe_target(tmp_path, case):
    target = _bad_artifact_targets(tmp_path)[case]
    with pytest.raises(MCPVideoError):
        _write_receipt({"receipt_kind": "workflow"}, target)


@pytest.mark.parametrize("case", ["absolute_system_path", "dotdot_escape", "sensitive_dotfile"])
def test_ensure_receipt_dir_fails_closed_on_unsafe_target(tmp_path, case):
    target = _bad_artifact_targets(tmp_path)[case]
    with pytest.raises(MCPVideoError):
        _ensure_receipt_dir(target)


def test_variant_receipt_dir_fails_closed_before_any_render(tmp_path):
    spec = _probe_spec()
    spec["variants"] = [{"id": "square", "overrides": {}}]
    spec_path = _write_spec(tmp_path, spec)
    with pytest.raises(MCPVideoError):
        render_workflow(spec_path, all_variants=True, save_receipt_dir="/etc/mcp_video_evil_dir")


def test_artifact_writers_succeed_in_workspace(tmp_path):
    plan_target = tmp_path / "plan.json"
    _write_plan({"receipt_kind": "workflow_plan"}, str(plan_target))
    assert plan_target.is_file()
    # overwriting an existing .json artifact is allowed
    _write_plan({"receipt_kind": "workflow_plan", "v": 2}, str(plan_target))
    assert json.loads(plan_target.read_text())["v"] == 2

    receipt_target = tmp_path / "receipt.json"
    _write_receipt({"receipt_kind": "workflow"}, str(receipt_target))
    assert receipt_target.is_file()


def test_plan_workflow_end_to_end_save_plan_in_workspace(tmp_path):
    spec_path = _write_spec(tmp_path, _probe_spec())
    out = tmp_path / "plan.json"
    plan_workflow(spec_path, save_plan=str(out))
    assert out.is_file()


def test_plan_workflow_end_to_end_save_plan_rejects_system_path(tmp_path):
    spec_path = _write_spec(tmp_path, _probe_spec())
    with pytest.raises(MCPVideoError):
        plan_workflow(spec_path, save_plan="/etc/mcp_video_evil_plan.json")


# --- S2: param VALUE validation at the workflow layer ------------------------


@pytest.mark.parametrize(
    "op, params",
    [
        ("resize", {"width": "20000", "height": 1920}),
        ("resize", {"width": "20000,drawtext=textfile=/etc/hosts", "height": 1920}),
        ("add_text", {"text": "hi", "size": "24,drawtext=textfile=/etc/hosts"}),
        ("add_text", {"text": "hi", "size": "big"}),
        ("trim", {"start": [1, 2]}),
        ("convert", {"format": ["mp4"]}),
    ],
)
def test_param_value_type_mismatch_fails_closed(tmp_path, op, params):
    spec = _single_step_spec(op, params)
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_params"


def test_valid_param_values_still_pass(tmp_path):
    spec = _single_step_spec("resize", {"width": 1080, "height": 1920})
    verdict = validate_workflow_spec(_write_spec(tmp_path, spec))
    assert verdict["valid"] is True


def test_int_param_rejects_float_and_bool(tmp_path):
    for bad in (1080.5, True):
        spec = _single_step_spec("resize", {"width": bad, "height": 1920})
        with pytest.raises(MCPVideoError) as exc:
            validate_workflow_spec(_write_spec(tmp_path, spec, name=f"w-{bad}.json"))
        assert exc.value.code == "invalid_workflow_params"


# --- S2: engine sink hardening (direct engine calls, bad types -> MCPVideoError)


def test_resize_engine_rejects_non_int_dimensions(sample_video):
    with pytest.raises(MCPVideoError):
        resize(sample_video, width="20000", height=1080)


def test_resize_engine_rejects_oversize_dimensions(sample_video):
    with pytest.raises(MCPVideoError):
        resize(sample_video, width=MAX_RESOLUTION + 1, height=1080)


def test_add_text_engine_rejects_non_numeric_size(sample_video):
    with pytest.raises(MCPVideoError):
        add_text(sample_video, text="hi", size="24,drawtext=textfile=/etc/hosts")
    with pytest.raises(MCPVideoError):
        add_text(sample_video, text="hi", size="big")


# --- S3: resource caps ------------------------------------------------------


def test_step_count_cap_fails_closed(tmp_path):
    steps = [{"id": f"p{i}", "op": "probe", "inputs": {"src": "@sources.a"}} for i in range(MAX_WORKFLOW_STEPS + 1)]
    spec = {"schema_version": 1, "sources": {"a": {"path": "a.mp4"}}, "steps": steps, "outputs": {}}
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_variant_count_cap_fails_closed(tmp_path):
    spec = _probe_spec()
    spec["variants"] = [{"id": f"v{i}", "overrides": {}} for i in range(MAX_WORKFLOW_VARIANTS + 1)]
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_step_count_at_cap_passes(tmp_path):
    steps = [{"id": f"p{i}", "op": "probe", "inputs": {"src": "@sources.a"}} for i in range(MAX_WORKFLOW_STEPS)]
    spec = {"schema_version": 1, "sources": {"a": {"path": "a.mp4"}}, "steps": steps, "outputs": {}}
    assert validate_workflow_spec(_write_spec(tmp_path, spec))["valid"] is True


# --- C2: font is not a tunable workflow param -------------------------------


def test_add_text_font_param_rejected(tmp_path):
    spec = _single_step_spec("add_text", {"text": "hi", "font": "/etc/passwd"})
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_params"
