"""TE QoL + proposed mutations tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.te import (
    BrandKit,
    compile_cutfile_to_workflow,
    estimate_operation,
    init_project,
    load_cutfile,
    render_cutfile,
    save_brand_kit,
    validate_cutfile,
)
from kinocut.watching import MetricFinding, propose_mutations_from_findings


def test_init_project_scaffold(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    r = init_project(str(root), name="demo")
    assert Path(r["media_dir"]).is_dir()
    assert Path(r["cutfile"]).is_file()


def test_brand_kit_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "brand.json"
    save_brand_kit(str(path), BrandKit(name="acme", primary_color="#112233"))
    from kinocut.te import load_brand_kit

    kit = load_brand_kit(str(path))
    assert kit.name == "acme"
    assert kit.primary_color == "#112233"


def test_estimate_operation() -> None:
    est = estimate_operation("repurpose", duration_seconds=60.0)
    assert est["dry_run"] is True
    assert est["estimated_wall_seconds"] > 0
    assert est["currency"] is None


def test_cutfile_validate() -> None:
    cf = validate_cutfile({"name": "demo", "version": 1, "sources": [], "ops": [{"op": "trim", "start": 0}]})
    assert cf.name == "demo"
    assert len(cf.ops) == 1


def test_cutfile_yaml_scaffold(tmp_path: Path) -> None:
    p = tmp_path / "cutfile.yaml"
    p.write_text('name: "demo"\nversion: 1\nsources: []\nops: []\n', encoding="utf-8")
    cf = load_cutfile(str(p))
    assert cf.name == "demo"


def test_cutfile_compile_to_workflow() -> None:
    cf = validate_cutfile(
        {
            "name": "demo",
            "version": 1,
            "sources": [{"id": "hero", "path": "media/hero.mp4"}],
            "ops": [
                {"op": "trim", "start": 0, "duration": 1},
                {"op": "resize", "width": 320, "height": 240},
            ],
        }
    )
    spec = compile_cutfile_to_workflow(cf, output_relpath="out/final.mp4")
    assert spec["schema_version"] == 1
    assert spec["sources"]["hero"]["path"] == "media/hero.mp4"
    assert len(spec["steps"]) == 2
    assert spec["steps"][0]["op"] == "trim"
    assert spec["steps"][0]["inputs"]["src"] == "@sources.hero"
    assert spec["steps"][1]["inputs"]["src"] == "@work/step_1.mp4"
    assert spec["steps"][1]["output"] == "@outputs.master"
    assert spec["outputs"]["master"]["path"] == "out/final.mp4"


def test_cutfile_compile_rejects_unsupported_op() -> None:
    cf = validate_cutfile(
        {
            "name": "bad",
            "version": 1,
            "sources": [{"id": "hero", "path": "media/hero.mp4"}],
            "ops": [{"op": "teleport"}],
        }
    )
    with pytest.raises(MCPVideoError) as exc:
        compile_cutfile_to_workflow(cf)
    assert exc.value.code == "cutfile_unsupported_op"


def test_cutfile_compile_rejects_composite_layers_shape() -> None:
    cf = validate_cutfile(
        {
            "name": "layers",
            "version": 1,
            "sources": [{"id": "hero", "path": "media/hero.mp4"}],
            "ops": [{"op": "composite_layers"}],
        }
    )
    with pytest.raises(MCPVideoError) as exc:
        compile_cutfile_to_workflow(cf)
    assert exc.value.code == "cutfile_op_shape"


def test_cutfile_compile_rejects_probe_only() -> None:
    cf = validate_cutfile(
        {
            "name": "probe",
            "version": 1,
            "sources": [{"id": "hero", "path": "media/hero.mp4"}],
            "ops": [{"op": "probe"}],
        }
    )
    with pytest.raises(MCPVideoError) as exc:
        compile_cutfile_to_workflow(cf)
    assert exc.value.code == "cutfile_no_media_ops"


def test_cutfile_compile_rejects_parent_output_relpath() -> None:
    cf = validate_cutfile(
        {
            "name": "escape",
            "version": 1,
            "sources": [{"id": "hero", "path": "media/hero.mp4"}],
            "ops": [{"op": "trim", "start": 0, "duration": 1}],
        }
    )
    with pytest.raises(MCPVideoError) as exc:
        compile_cutfile_to_workflow(cf, output_relpath="../out/final.mp4")
    assert exc.value.code in {"cutfile_output_invalid", "invalid_cutfile_output", "cutfile_output_path"}


def test_cutfile_compile_requires_sources_and_ops() -> None:
    empty_ops = validate_cutfile({"name": "x", "version": 1, "sources": [{"id": "a", "path": "a.mp4"}], "ops": []})
    with pytest.raises(MCPVideoError) as exc:
        compile_cutfile_to_workflow(empty_ops)
    assert exc.value.code == "cutfile_ops_required"

    no_src = validate_cutfile({"name": "x", "version": 1, "sources": [], "ops": [{"op": "trim", "start": 0}]})
    with pytest.raises(MCPVideoError) as exc2:
        compile_cutfile_to_workflow(no_src)
    assert exc2.value.code == "cutfile_sources_required"


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_cutfile_render_trim_resize(tmp_path: Path, sample_video: str) -> None:
    root = tmp_path / "proj"
    init_project(str(root), name="render-demo")
    media = root / "media" / "hero.mp4"
    shutil.copy(sample_video, media)
    cutfile = {
        "name": "render-demo",
        "version": 1,
        "sources": [{"id": "hero", "path": "media/hero.mp4"}],
        "ops": [
            {"op": "trim", "start": 0, "duration": 1},
            {"op": "resize", "width": 320, "height": 240},
        ],
    }
    (root / "cutfile.json").write_text(json.dumps(cutfile), encoding="utf-8")

    result = render_cutfile(str(root / "cutfile.json"), output_path="out/final.mp4")
    assert result["artifact_kind"] == "cutfile_render"
    assert Path(result["output_path"]).is_file()
    assert result["workflow"]["status"] == "completed"


def test_propose_mutations_from_findings() -> None:
    findings = [
        MetricFinding("duration.min", "fail", "too short", (0.0, 0.1)),
        MetricFinding("black_frames.ratio", "warn", "blackish", (0.0, 1.0)),
        MetricFinding("ok", "info", "fine"),
    ]
    props = propose_mutations_from_findings(findings)
    assert len(props) == 2
    assert all(p.apply_policy == "human_review_required" for p in props)
