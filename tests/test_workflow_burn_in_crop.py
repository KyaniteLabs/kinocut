"""``crop`` + ``burn_in`` workflow adapters — confinement, provenance, fail-closed.

``crop`` is a simple single-input op over ``engine_crop.crop`` (mirrors trim/resize/
convert: one ``src`` -> ``input_path``). ``burn_in`` is a bespoke adapter
(``BurnInOpAdapter``) over ``engine_subtitles.subtitles``: its subtitle is a SECOND
typed, workspace-confined input (``srcs[1]`` -> ``subtitle_path``), excluded from
tunables, included in input hashing/reuse; ``style`` is the only burn-in tunable.

Both sources ride the EXISTING multi-input (``srcs``) binding, so the unmodified
validator confines each ref and the planner/executor hash one slot per source — no
validator/planner branch is needed, and existing executor semantics are unchanged.

Real renders shell out to FFmpeg; the provenance/reuse/leakage tests instead stub
the engine fn with a signature-preserving recorder (``functools.wraps`` keeps the
validator's signature-derived param introspection honest) so no FFmpeg is required.
"""

from __future__ import annotations

import functools
import json
from dataclasses import replace
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.workflow import OP_ADAPTERS, plan_workflow, render_workflow, validate_workflow_spec
from mcp_video.workflow.ops import BurnInOpAdapter, CompositeOpAdapter, OpAdapter

import kinocut.workflow.ops as ops_mod


# --- Specs + workspace -------------------------------------------------------


def _write_spec(directory: Path, spec: dict, name: str = "job.json") -> str:
    path = Path(directory) / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "v.mp4").write_bytes(b"video-bytes")
    (tmp_path / "input" / "c.srt").write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    return tmp_path


def _crop_spec(params: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "name": "crop",
        "sources": {"vid": {"path": "input/v.mp4"}},
        "steps": [
            {
                "id": "c1",
                "op": "crop",
                "inputs": {"src": "@sources.vid"},
                "params": params if params is not None else {"x": 0, "y": 0, "width": 100, "height": 100},
                "output": "@outputs.f",
            }
        ],
        "outputs": {"f": {"path": "output/f.mp4"}},
    }


def _burn_in_spec(srcs: list[str] | None = None, params: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "name": "burn",
        "sources": {"vid": {"path": "input/v.mp4"}, "sub": {"path": "input/c.srt"}},
        "steps": [
            {
                "id": "b1",
                "op": "burn_in",
                "inputs": {"srcs": srcs if srcs is not None else ["@sources.vid", "@sources.sub"]},
                "params": params if params is not None else {},
                "output": "@outputs.f",
            }
        ],
        "outputs": {"f": {"path": "output/f.mp4"}},
    }


def _stub_engine(monkeypatch, op_name: str) -> tuple[dict, dict]:
    """Signature-preserving recorder: counts calls + captures kwargs, no FFmpeg.

    ``functools.wraps`` keeps ``inspect.signature(stub)`` == the real engine fn, so the
    validator's signature-derived ``accepted_params`` introspection stays honest.
    """
    real_adapter = ops_mod.OP_ADAPTERS[op_name]
    calls: dict[str, int] = {"count": 0}
    last: dict = {}

    @functools.wraps(real_adapter.engine_fn)
    def stub(**kwargs):
        calls["count"] += 1
        last.clear()
        last.update(kwargs)
        out = kwargs.get("output_path")
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"stub-output")

    monkeypatch.setitem(ops_mod.OP_ADAPTERS, op_name, replace(real_adapter, engine_fn=stub))
    return calls, last


# --- Allowlist membership + adapter params -----------------------------------


def test_crop_is_a_simple_allowlisted_op():
    adapter = OP_ADAPTERS["crop"]
    assert isinstance(adapter, OpAdapter)
    assert not isinstance(adapter, (CompositeOpAdapter, BurnInOpAdapter))
    assert adapter.input_key == "src"
    assert adapter.engine_input_param == "input_path"
    assert adapter.has_output is True
    # every engine tunable except the input/output bindings
    assert adapter.accepted_params() == frozenset({"width", "height", "x", "y", "crop_percent"})


def test_burn_in_is_a_bespoke_allowlisted_op():
    adapter = OP_ADAPTERS["burn_in"]
    assert isinstance(adapter, BurnInOpAdapter)
    assert adapter.input_key == "srcs"
    assert adapter.multi_input is True
    assert adapter.engine_input_param == "input_path"
    assert adapter.engine_subtitle_param == "subtitle_path"
    assert adapter.has_output is True
    # the subtitle/input params are NOT tunables; ``style`` is the only one.
    assert adapter.accepted_params() == frozenset({"style"})


# --- Validation acceptance ---------------------------------------------------


def test_validate_accepts_valid_crop_spec(tmp_path):
    verdict = validate_workflow_spec(_write_spec(tmp_path, _crop_spec()))
    assert verdict["valid"] is True
    assert verdict["ops"] == ["crop"]


def test_validate_accepts_valid_burn_in_spec(tmp_path):
    ws = _workspace(tmp_path)
    verdict = validate_workflow_spec(_write_spec(ws, _burn_in_spec()))
    assert verdict["valid"] is True
    assert verdict["ops"] == ["burn_in"]


def test_burn_in_subtitle_is_an_input_not_a_tunable(tmp_path):
    ws = _workspace(tmp_path)
    verdict = validate_workflow_spec(_write_spec(ws, _burn_in_spec()))
    step = verdict["steps"][0]
    # the subtitle lives in inputs (srcs), never in the tunable params list
    assert set(step["inputs"]) == {"srcs"}
    assert step["params"] == []


# --- Fail-closed: confinement ------------------------------------------------


@pytest.mark.parametrize(
    "bad_sub, code",
    [
        ("../evil.srt", "unsafe_workflow_source"),
        ("/etc/passwd", "unsafe_workflow_source"),
        ("@sources.missing", "unknown_workflow_ref"),
    ],
)
def test_burn_in_subtitle_must_stay_confined(tmp_path, bad_sub, code):
    ws = _workspace(tmp_path)
    spec = _burn_in_spec(srcs=["@sources.vid", bad_sub])
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(ws, spec))
    assert exc.value.code == code


def test_burn_in_primary_video_must_stay_confined(tmp_path):
    ws = _workspace(tmp_path)
    spec = _burn_in_spec(srcs=["../evil.mp4", "@sources.sub"])
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(ws, spec))
    assert exc.value.code == "unsafe_workflow_source"


def test_crop_source_must_stay_confined(tmp_path):
    spec = _crop_spec()
    spec["steps"][0]["inputs"]["src"] = "../evil.mp4"
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsafe_workflow_source"


def test_burn_in_extra_input_key_fails_closed(tmp_path):
    ws = _workspace(tmp_path)
    spec = _burn_in_spec()
    spec["steps"][0]["inputs"]["src"] = "@sources.vid"
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(ws, spec))
    assert exc.value.code == "invalid_workflow_spec"


# --- Fail-closed: adapter params ---------------------------------------------


def test_burn_in_non_string_style_fails_closed(tmp_path):
    ws = _workspace(tmp_path)
    spec = _burn_in_spec(params={"style": 42})
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(ws, spec))
    assert exc.value.code == "invalid_workflow_params"


def test_burn_in_unknown_param_fails_closed(tmp_path):
    ws = _workspace(tmp_path)
    spec = _burn_in_spec(params={"filtergraph": "drawtext=…"})
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(ws, spec))
    assert exc.value.code == "invalid_workflow_params"


def test_burn_in_string_style_is_accepted(tmp_path):
    ws = _workspace(tmp_path)
    spec = _burn_in_spec(params={"style": "FontSize=24,PrimaryColour=&HFFFFFF&"})
    assert validate_workflow_spec(_write_spec(ws, spec))["valid"] is True


def test_crop_unknown_param_fails_closed(tmp_path):
    spec = _crop_spec(params={"filtergraph": "x"})
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_params"


# --- Provenance: both sources hashed -----------------------------------------


def test_plan_hashes_both_burn_in_sources(tmp_path):
    ws = _workspace(tmp_path)
    plan = plan_workflow(_write_spec(ws, _burn_in_spec()))
    hashes = plan["steps"][0]["input_hashes"]
    assert set(hashes) == {"srcs[0]", "srcs[1]"}
    assert all(h.startswith("sha256:") for h in hashes.values())


def test_receipt_hashes_both_burn_in_sources(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    _stub_engine(monkeypatch, "burn_in")
    receipt = render_workflow(_write_spec(ws, _burn_in_spec()))
    assert receipt["status"] == "completed"
    assert set(receipt["steps"][0]["input_hashes"]) == {"srcs[0]", "srcs[1]"}


def test_burn_in_binds_video_to_input_path_and_subtitle_to_subtitle_path(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    spec_path = _write_spec(ws, _burn_in_spec(params={"style": "FontSize=24"}))
    _, last = _stub_engine(monkeypatch, "burn_in")
    render_workflow(spec_path)
    # the two typed inputs split into the engine's two named path params
    assert last["input_path"].endswith("v.mp4")
    assert last["subtitle_path"].endswith("c.srt")
    assert str(ws) in last["input_path"]  # confined to the workspace
    assert str(ws) in last["subtitle_path"]
    assert last["style"] == "FontSize=24"
    assert last["output_path"].endswith("f.mp4")


def test_crop_passes_params_and_confined_input(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    spec_path = _write_spec(ws, _crop_spec(params={"x": 8, "y": 16, "width": 100, "height": 100}))
    _, last = _stub_engine(monkeypatch, "crop")
    render_workflow(spec_path)
    assert last["input_path"].endswith("v.mp4")
    assert str(ws) in last["input_path"]
    assert (last["x"], last["y"], last["width"], last["height"]) == (8, 16, 100, 100)
    assert last["output_path"].endswith("f.mp4")


def test_burn_in_with_one_src_fails_closed_at_render(tmp_path, monkeypatch):
    # the validator allows any non-empty srcs list; the executor gate requires exactly
    # [video, subtitle], so a missing-subtitle spec fails closed before the engine runs.
    ws = _workspace(tmp_path)
    spec_path = _write_spec(ws, _burn_in_spec(srcs=["@sources.vid"]))
    _stub_engine(monkeypatch, "burn_in")
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path)
    assert exc.value.code == "invalid_workflow_spec"


# --- Resume: hashing drives reuse / re-run -----------------------------------


def test_burn_in_resume_reuses_on_identical_inputs(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    spec_path = _write_spec(ws, _burn_in_spec())
    calls, _ = _stub_engine(monkeypatch, "burn_in")
    render_workflow(spec_path, save_receipt=str(ws / "r1.json"), keep_intermediates=True)
    r2 = render_workflow(
        spec_path, resume_receipt=str(ws / "r1.json"), save_receipt=str(ws / "r2.json"), keep_intermediates=True
    )
    assert calls["count"] == 1  # reused, not re-rendered
    assert r2["steps"][0]["skipped"] is True
    assert r2["feature_flags"]["resume_used"] is True


def test_burn_in_resume_reruns_when_subtitle_changes(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    spec_path = _write_spec(ws, _burn_in_spec())
    calls, _ = _stub_engine(monkeypatch, "burn_in")
    render_workflow(spec_path, save_receipt=str(ws / "r1.json"), keep_intermediates=True)
    (ws / "input" / "c.srt").write_bytes(b"2\n00:00:03,000 --> 00:00:04,000\nChanged\n")
    r2 = render_workflow(
        spec_path, resume_receipt=str(ws / "r1.json"), save_receipt=str(ws / "r2.json"), keep_intermediates=True
    )
    assert calls["count"] == 2  # subtitle hash changed -> the reuse gate fails -> re-run
    assert r2["steps"][0].get("skipped") is not True


# --- No raw-path leakage on engine failure -----------------------------------


def test_burn_in_engine_failure_redacts_out_of_workspace_paths(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    spec_path = _write_spec(ws, _burn_in_spec())
    real_adapter = ops_mod.OP_ADAPTERS["burn_in"]

    @functools.wraps(real_adapter.engine_fn)
    def leaky(**kwargs):
        raise RuntimeError(f"missing /Users/secret/leak.txt and /etc/passwd near {kwargs.get('input_path')}")

    monkeypatch.setitem(ops_mod.OP_ADAPTERS, "burn_in", replace(real_adapter, engine_fn=leaky))
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path, save_receipt=str(ws / "receipt.json"), keep_intermediates=True)
    message = str(exc.value)
    assert "/Users" not in message
    assert "/etc" not in message
    assert str(ws) not in message  # the workspace absolute path is stripped
    assert "<redacted-path>" in message
    # the persisted receipt carries the SAME sanitized error — nothing leaks to disk
    receipt = json.loads((ws / "receipt.json").read_text())
    err_msg = receipt["steps"][0]["error"]["message"]
    assert "/Users" not in err_msg
    assert "/etc" not in err_msg
    assert str(ws) not in err_msg
    assert "<redacted-path>" in err_msg
