"""Unit + adversarial tests for the workflow job-spec model and validator."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.workflow import OP_ADAPTERS, validate_workflow_spec


def _write_spec(directory: Path, spec: dict, name: str = "job.json") -> str:
    path = Path(directory) / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


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
                "params": {"start": 0, "duration": 6},
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
                "params": {"text": "Watch this", "position": "bottom-center"},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
        "variants": [{"id": "square", "overrides": {"steps.vertical.params": {"width": 1080, "height": 1080}}}],
    }


# --- happy path -------------------------------------------------------------


def test_valid_flagship_spec_passes(tmp_path):
    verdict = validate_workflow_spec(_write_spec(tmp_path, _flagship_spec()))

    assert verdict["valid"] is True
    assert verdict["schema_version"] == 1
    assert verdict["name"] == "captioned-vertical-short"
    assert verdict["sources"] == ["hero"]
    assert verdict["outputs"] == ["master"]
    assert verdict["ops"] == ["add_text", "probe", "resize", "trim"]
    assert verdict["variants"] == ["square"]
    assert [step["id"] for step in verdict["steps"]] == ["probe-hero", "trim-hero", "vertical", "caption"]
    assert verdict["source_paths"] == {"hero": "input/hero.mp4"}


def test_validation_is_deterministic(tmp_path):
    path = _write_spec(tmp_path, _flagship_spec())
    assert validate_workflow_spec(path) == validate_workflow_spec(path)


def test_valid_merge_uses_srcs_list(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}, "b": {"path": "b.mp4"}},
        "steps": [
            {"id": "trim-a", "op": "trim", "inputs": {"src": "@sources.a"}, "output": "@work/a.mp4"},
            {"id": "trim-b", "op": "trim", "inputs": {"src": "@sources.b"}, "output": "@work/b.mp4"},
            {
                "id": "join",
                "op": "merge",
                "inputs": {"srcs": ["@work/a.mp4", "@work/b.mp4"]},
                "output": "@outputs.final",
            },
        ],
        "outputs": {"final": {"path": "out.mp4"}},
    }
    verdict = validate_workflow_spec(_write_spec(tmp_path, spec))
    assert verdict["steps"][-1]["inputs"] == {"srcs": ["@work/a.mp4", "@work/b.mp4"]}


# --- op allowlist -----------------------------------------------------------


@pytest.mark.parametrize("op", ["composite_layers", "explode", "video_batch", ""])
def test_unsupported_op_fails_closed(tmp_path, op):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": op, "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsupported_workflow_op"
    assert exc.value.suggested_action is not None


# --- @ref resolution + backward-reference-only ------------------------------


def test_undeclared_source_ref_fails(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "@sources.missing"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unknown_workflow_ref"


def test_forward_work_ref_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [
            {"id": "s1", "op": "trim", "inputs": {"src": "@work/later.mp4"}, "output": "@work/early.mp4"},
            {"id": "s2", "op": "resize", "inputs": {"src": "@sources.a"}, "output": "@work/later.mp4"},
        ],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unknown_workflow_ref"


def test_self_work_ref_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "@work/self.mp4"}, "output": "@work/self.mp4"}],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unknown_workflow_ref"


def test_outputs_ref_as_input_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "@outputs.o"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unknown_workflow_ref"


def test_unknown_ref_namespace_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "@foo.bar"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unknown_workflow_ref"


def test_output_to_undeclared_output_id_fails(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "@sources.a"}, "output": "@outputs.nope"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unknown_workflow_ref"


# --- input/output binding ---------------------------------------------------


def test_merge_rejects_single_src_key(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "merge", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_single_input_op_rejects_list(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": ["@sources.a"]}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_probe_with_output_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "probe", "inputs": {"src": "@sources.a"}, "output": "@work/x.mp4"}],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_render_op_missing_output_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "@sources.a"}}],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


# --- per-op param introspection ---------------------------------------------


def test_unknown_param_rejected_by_introspection(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [
            {
                "id": "s1",
                "op": "trim",
                "inputs": {"src": "@sources.a"},
                "params": {"bogus_param": 1},
                "output": "@outputs.o",
            }
        ],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_params"


def test_engine_bound_and_output_params_are_not_tunable(tmp_path):
    # input_path (the bound arg) and output_path are wired by the engine, not
    # exposed as tunable params — passing them fails closed.
    for reserved in ("input_path", "output_path"):
        spec = {
            "schema_version": 1,
            "sources": {"a": {"path": "a.mp4"}},
            "steps": [
                {
                    "id": "s1",
                    "op": "trim",
                    "inputs": {"src": "@sources.a"},
                    "params": {reserved: "x"},
                    "output": "@outputs.o",
                }
            ],
            "outputs": {"o": {"path": "out.mp4"}},
        }
        with pytest.raises(MCPVideoError) as exc:
            validate_workflow_spec(_write_spec(tmp_path, spec, name=f"{reserved}.json"))
        assert exc.value.code == "invalid_workflow_params"


def test_adapter_accepted_params_subset_of_engine_signature():
    """Drift-guard: no adapter may advertise a param the engine cannot accept,
    the bound input param must exist, and output-producing ops must expose
    output_path."""
    for name, adapter in OP_ADAPTERS.items():
        signature_params = set(inspect.signature(adapter.engine_fn).parameters)
        assert adapter.accepted_params() <= signature_params, name
        assert adapter.engine_input_param in signature_params, name
        if adapter.has_output:
            assert "output_path" in signature_params, name


# --- schema / structural fail-closed ----------------------------------------


def test_unknown_top_level_key_fails_closed(tmp_path):
    spec = _flagship_spec()
    spec["filtergraph"] = "drawtext=..."  # raw filtergraph injection attempt
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_unknown_step_key_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [
            {
                "id": "s1",
                "op": "trim",
                "inputs": {"src": "@sources.a"},
                "output": "@outputs.o",
                "args": ["-vf", "evil"],  # no passthrough key allowed
            }
        ],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_schema_version_must_be_one(tmp_path):
    spec = _flagship_spec()
    spec["schema_version"] = 2
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_empty_steps_fails_closed(tmp_path):
    spec = {"schema_version": 1, "sources": {"a": {"path": "a.mp4"}}, "steps": [], "outputs": {}}
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_duplicate_step_id_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [
            {"id": "dup", "op": "trim", "inputs": {"src": "@sources.a"}, "output": "@work/x.mp4"},
            {"id": "dup", "op": "resize", "inputs": {"src": "@work/x.mp4"}, "output": "@outputs.o"},
        ],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_duplicate_work_output_name_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [
            {"id": "s1", "op": "trim", "inputs": {"src": "@sources.a"}, "output": "@work/dup.mp4"},
            {"id": "s2", "op": "resize", "inputs": {"src": "@work/dup.mp4"}, "output": "@work/dup.mp4"},
        ],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_non_object_spec_fails_closed(tmp_path):
    path = Path(tmp_path) / "job.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(str(path))
    assert exc.value.code == "invalid_workflow_spec"


def test_non_json_suffix_fails_closed(tmp_path):
    path = Path(tmp_path) / "job.txt"
    path.write_text(json.dumps(_flagship_spec()), encoding="utf-8")
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(str(path))
    assert exc.value.code == "invalid_workflow_spec"


def test_missing_spec_file_fails_closed(tmp_path):
    with pytest.raises(MCPVideoError):
        validate_workflow_spec(str(Path(tmp_path) / "does_not_exist.json"))


# --- adversarial path safety ------------------------------------------------


def test_absolute_source_path_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "/etc/passwd"}},
        "steps": [{"id": "s1", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsafe_workflow_source"


def test_dotdot_escape_source_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "../secret.mp4"}},
        "steps": [{"id": "s1", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsafe_workflow_source"


def test_symlink_escape_source_fails_closed(tmp_path):
    workspace = Path(tmp_path) / "ws"
    workspace.mkdir()
    outside = Path(tmp_path) / "outside.mp4"
    outside.write_bytes(b"x")
    (workspace / "evil.mp4").symlink_to(outside)
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "evil.mp4"}},
        "steps": [{"id": "s1", "op": "probe", "inputs": {"src": "@sources.a"}}],
        "outputs": {},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(workspace, spec))
    assert exc.value.code == "unsafe_workflow_source"


def test_raw_input_path_escape_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "../escape.mp4"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsafe_workflow_source"


def test_absolute_output_path_fails_closed(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "trim", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "/tmp/escape.mp4"}},
    }
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsafe_workflow_source"
