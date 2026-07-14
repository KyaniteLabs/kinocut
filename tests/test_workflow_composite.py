"""``composite_layers`` as the 7th workflow op — confinement + provenance.

The workflow layer OWNS the nested layer-spec: every layer source is a workflow
``@ref`` (``@sources.*`` / ``@work/*``), resolved + confined + hashed by the SAME
machinery as every other op, then synthesized into a workspace-confined spec the
vetted engine consumes. Escaping layer sources (``../`` / absolute / symlink /
non-``@ref``) fail closed; a valid composite records one sha256 per layer source
plus the output hash.

Real renders shell out to FFmpeg and are marked ``@pytest.mark.slow``; the
filtergraph is unchanged (this op only synthesizes a spec), so it stays
FFmpeg-6-safe.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.workflow import OP_ADAPTERS, render_workflow, validate_workflow_spec
from mcp_video.workflow.ops import CompositeOpAdapter


def _write_spec(directory: Path, spec: dict, name: str = "job.json") -> str:
    path = Path(directory) / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _canvas() -> dict:
    return {"width": 320, "height": 180, "duration": 1, "fps": 12, "background": "#000000"}


def _composite_spec(layers: list[dict], sources: dict, canvas: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "name": "comp",
        "sources": sources,
        "steps": [
            {
                "id": "comp",
                "op": "composite_layers",
                "inputs": {"layers": layers},
                "params": {"canvas": canvas if canvas is not None else _canvas()},
                "output": "@outputs.final",
            }
        ],
        "outputs": {"final": {"path": "output/final.mp4"}},
    }


def _two_layer_spec() -> dict:
    return _composite_spec(
        layers=[
            {"id": "base", "type": "video", "src": "@sources.bg"},
            {"id": "mark", "type": "image", "src": "@sources.logo", "opacity": 0.7, "position": {"x": 8, "y": 8}},
        ],
        sources={"bg": {"path": "input/bg.mp4"}, "logo": {"path": "input/logo.png"}},
    )


# --- Allowlist membership ----------------------------------------------------


def test_composite_is_a_bespoke_allowlisted_op():
    adapter = OP_ADAPTERS["composite_layers"]
    assert isinstance(adapter, CompositeOpAdapter)
    assert adapter.accepted_params() == frozenset({"canvas"})


def test_validate_accepts_a_valid_composite_spec(tmp_path):
    verdict = validate_workflow_spec(_write_spec(tmp_path, _two_layer_spec()))
    assert verdict["valid"] is True
    assert verdict["ops"] == ["composite_layers"]


# --- Fail-closed: escaping / non-@ref layer sources --------------------------


@pytest.mark.parametrize(
    "bad_src, code",
    [
        ("../evil.mp4", "unsafe_workflow_source"),
        ("/etc/passwd", "unsafe_workflow_source"),
        ("input/bg.mp4", "unsafe_workflow_source"),  # raw relative path is NOT a @ref for composite
        ("@outputs.final", "unsafe_workflow_source"),
        ("@sources.missing", "unknown_workflow_ref"),
    ],
)
def test_layer_source_must_be_a_workflow_ref(tmp_path, bad_src, code):
    spec = _composite_spec(
        layers=[{"id": "base", "type": "video", "src": bad_src}],
        sources={"bg": {"path": "input/bg.mp4"}},
    )
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == code


def test_symlink_layer_source_escaping_workspace_fails_closed(tmp_path):
    link = tmp_path / "link.mp4"
    link.symlink_to("/etc/hosts")  # inside the workspace, resolves outside
    spec = _composite_spec(
        layers=[{"id": "base", "type": "video", "src": "@sources.evil"}],
        sources={"evil": {"path": "link.mp4"}},
    )
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "unsafe_workflow_source"


# --- Fail-closed: structural layer / param violations ------------------------


def test_unknown_layer_field_fails_closed(tmp_path):
    spec = _composite_spec(
        layers=[{"id": "base", "type": "video", "src": "@sources.bg", "effects": ["blur"]}],
        sources={"bg": {"path": "input/bg.mp4"}},
    )
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


@pytest.mark.parametrize("field", ["matte", "transform", "anchor"])
def test_engine_honored_but_unlisted_path_field_fails_closed(tmp_path, field):
    # matte/transform/anchor are honored by the engine but deliberately omitted from the
    # workflow layer allowlist; declaring one fails closed at validate time.
    spec = _composite_spec(
        layers=[{"id": "base", "type": "video", "src": "@sources.bg", field: "@sources.bg"}],
        sources={"bg": {"path": "input/bg.mp4"}},
    )
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_toctou_injected_matte_fails_closed_at_render(tmp_path, monkeypatch):
    # The validator reads the clean on-disk spec (no matte); the executor's independent
    # re-read is monkeypatched to inject an out-of-workspace `matte` (a validate/render
    # divergence). The render-time re-validation must fail closed before the matte path is
    # ever resolved or hashed — nothing out-of-workspace is read and no output is produced.
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "bg.mp4").write_bytes(b"bg")
    spec = _composite_spec(
        layers=[{"id": "base", "type": "video", "src": "@sources.bg"}],
        sources={"bg": {"path": "input/bg.mp4"}},
    )
    spec_path = _write_spec(tmp_path, spec)

    import mcp_video.workflow.executor as ex

    real_parse = ex.parse_spec

    def dirty_parse(data):
        parsed = real_parse(data)
        for step in parsed.steps:
            if step.op == "composite_layers":
                step.inputs["layers"][0]["matte"] = "/etc/passwd"
        return parsed

    monkeypatch.setattr(ex, "parse_spec", dirty_parse)

    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path)
    assert exc.value.code == "invalid_workflow_spec"
    assert not (tmp_path / "output" / "final.mp4").exists()
    # the synthesized spec is never written (re-validation aborts first).
    assert list(tmp_path.rglob("mcp_video_composite_*.json")) == []


def test_synth_spec_symlink_escape_fails_closed(tmp_path):
    # A planted symlink at the synth-spec write path must not redirect the write out of the
    # workspace (R1 artifact guard on the composite writer); the engine is never invoked.
    from types import SimpleNamespace

    from mcp_video.workflow.composite import render_composite_step
    from mcp_video.workflow.executor import _resolve_confined_input

    ws = tmp_path / "ws"
    ws.mkdir()
    run_dir = ws / "work" / "run1"
    run_dir.mkdir(parents=True)
    outside = tmp_path / "evil_synth.json"
    synth = ws / f"mcp_video_composite_{run_dir.name}_comp.json"
    synth.symlink_to(outside)

    called = {"engine": False}

    def engine_fn(**_kwargs):
        called["engine"] = True

    adapter = SimpleNamespace(engine_fn=engine_fn)
    step = SimpleNamespace(
        id="comp",
        inputs={"layers": [{"id": "s", "type": "solid", "color": "#000000"}]},
        params={"canvas": {"width": 32, "height": 32, "duration": 1, "fps": 12, "background": "#000000"}},
    )
    with pytest.raises(MCPVideoError) as exc:
        render_composite_step(
            adapter,
            step,
            ws,
            {},
            {},
            run_dir,
            ws / "out.mp4",
            _resolve_confined_input,
            set(),
            set(),
        )
    assert exc.value.code == "unsafe_workflow_source"
    assert called["engine"] is False


def test_duplicate_layer_id_fails_closed(tmp_path):
    spec = _composite_spec(
        layers=[
            {"id": "dup", "type": "video", "src": "@sources.bg"},
            {"id": "dup", "type": "solid", "color": "#ffffff"},
        ],
        sources={"bg": {"path": "input/bg.mp4"}},
    )
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_video_layer_without_src_fails_closed(tmp_path):
    spec = _composite_spec(layers=[{"id": "base", "type": "video"}], sources={"bg": {"path": "input/bg.mp4"}})
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_solid_layer_with_src_fails_closed(tmp_path):
    spec = _composite_spec(
        layers=[{"id": "s", "type": "solid", "src": "@sources.bg", "color": "#fff000"}],
        sources={"bg": {"path": "input/bg.mp4"}},
    )
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_extra_input_key_fails_closed(tmp_path):
    spec = _two_layer_spec()
    spec["steps"][0]["inputs"]["srcs"] = ["@sources.bg"]
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_spec"


def test_non_object_canvas_param_fails_closed(tmp_path):
    spec = _composite_spec(
        layers=[{"id": "base", "type": "video", "src": "@sources.bg"}],
        sources={"bg": {"path": "input/bg.mp4"}},
        canvas="1920x1080",  # type: ignore[arg-type]
    )
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_params"


def test_unknown_param_key_fails_closed(tmp_path):
    spec = _two_layer_spec()
    spec["steps"][0]["params"]["filtergraph"] = "drawtext=..."
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_params"


# --- Real render: provenance receipt lists every layer source hash -----------


def _workspace(tmp_path: Path, sample_video: str, sample_watermark_png: str) -> Path:
    (tmp_path / "input").mkdir(exist_ok=True)
    shutil.copy(sample_video, tmp_path / "input" / "bg.mp4")
    shutil.copy(sample_watermark_png, tmp_path / "input" / "logo.png")
    return tmp_path


@pytest.mark.slow
def test_valid_composite_renders_with_complete_layer_provenance(tmp_path, sample_video, sample_watermark_png):
    ws = _workspace(tmp_path, sample_video, sample_watermark_png)
    spec_path = _write_spec(ws, _two_layer_spec())

    receipt = render_workflow(spec_path, save_receipt=str(ws / "receipt.json"))

    assert receipt["status"] == "completed"
    assert (ws / "output" / "final.mp4").is_file()

    step = receipt["steps"][0]
    assert step["op"] == "composite_layers"
    # one sha256 per layer source, in order; the solid layer (no src) has no slot.
    assert set(step["input_hashes"]) == {"layers[0].src", "layers[1].src"}
    assert all(str(v).startswith("sha256:") for v in step["input_hashes"].values())
    # full layer structure preserved in the receipt for provenance.
    assert [layer["id"] for layer in step["inputs"]["layers"]] == ["base", "mark"]
    # output goes through the normal output binding + output_hash.
    assert receipt["outputs"][0]["output_hash"].startswith("sha256:")

    # no synthesized nested spec is left behind in the @work dir.
    assert list(ws.rglob("mcp_video_composite_*.json")) == []


@pytest.mark.slow
def test_composite_with_solid_layer_and_masked_layer_renders(tmp_path, sample_video, sample_watermark_png):
    ws = _workspace(tmp_path, sample_video, sample_watermark_png)
    spec = _composite_spec(
        layers=[
            {"id": "base", "type": "video", "src": "@sources.bg"},
            {"id": "masked", "type": "image", "src": "@sources.logo", "mask": "@sources.logo"},
            {"id": "tint", "type": "solid", "color": "#0044ff", "opacity": 0.15},
        ],
        sources={"bg": {"path": "input/bg.mp4"}, "logo": {"path": "input/logo.png"}},
    )
    spec_path = _write_spec(ws, spec)

    receipt = render_workflow(spec_path, save_receipt=str(ws / "receipt.json"))

    assert receipt["status"] == "completed"
    step = receipt["steps"][0]
    # both the masked layer's src AND its mask are hashed; the solid layer has neither.
    assert set(step["input_hashes"]) == {"layers[0].src", "layers[1].src", "layers[1].mask"}
    assert all(str(v).startswith("sha256:") for v in step["input_hashes"].values())
    assert receipt["outputs"][0]["output_hash"].startswith("sha256:")
