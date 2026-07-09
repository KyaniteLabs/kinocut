"""Tests for spec-driven composite-layers."""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from mcp_video.engine_composite_layers import composite_layers
from mcp_video.errors import MCPVideoError


def _write_minimal_assets(tmp_path):
    bg = tmp_path / "bg.mp4"
    plate = tmp_path / "plate.png"
    title = tmp_path / "title.png"
    mask = tmp_path / "mask.png"
    bg.write_bytes(b"bg")
    plate.write_bytes(b"plate")
    title.write_bytes(b"title")
    mask.write_bytes(b"mask")
    return bg, plate, title


def _write_spec(tmp_path, spec):
    spec_path = tmp_path / "layers.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path


def _minimal_spec():
    return {
        "canvas": {"width": 320, "height": 180, "background": "#000000", "fps": 12, "duration": 1.0},
        "layers": [
            {"id": "background", "type": "video", "src": "bg.mp4", "position": {"x": 0, "y": 0}},
            {"id": "plate", "type": "image", "src": "plate.png", "opacity": 0.75, "position": {"x": 8, "y": 10}},
            {"id": "title", "type": "image", "src": "title.png", "opacity": 0.9, "position": {"x": 24, "y": 12}},
        ],
        "output": {"format": "mp4"},
    }


def test_composite_layers_builds_three_layer_filtergraph_and_receipt(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    spec_path = _write_spec(tmp_path, _minimal_spec())
    output = tmp_path / "out.mp4"
    plan = tmp_path / "layer-plan.json"
    calls = []

    def fake_run_ffmpeg(args):
        calls.append(args.copy())
        output.write_bytes(b"render")

    monkeypatch.setattr("mcp_video.engine_composite_layers._run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        "mcp_video.engine_probe.probe",
        lambda path: SimpleNamespace(duration=1.0, resolution="320x180", size_mb=0.1, format="mp4"),
    )

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan))

    assert result.output_path == str(output)
    assert result.layer_plan_path == str(plan)
    assert len(result.layer_plan["layers"]) == 3
    assert result.layer_plan["layers"][1]["resolved_src"] == "plate.png"
    assert result.layer_plan["layers"][1]["source_hash"].startswith("sha256:")
    assert "input/spec/filtergraph/output hashes" in result.layer_plan["render_determinism_scope"]
    assert result.layer_plan["output_hash"].startswith("sha256:")
    assert plan.is_file()
    saved = json.loads(plan.read_text())
    assert saved["spec_hash"].startswith("sha256:")

    cmd = calls[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.count("overlay=") == 3
    assert "colorchannelmixer=aa=0.75" in graph
    assert "overlay=8:10" in graph
    assert graph.endswith(",format=yuv420p[vout]")
    assert cmd.count("-loop") == 2


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda spec: spec["layers"].append({**spec["layers"][0]}), "duplicate_layer_id"),
        (lambda spec: spec["layers"][1].update({"blend": "screen"}), "unsupported_blend_mode"),
        (lambda spec: spec.update({"passes": []}), "unsupported_compositor_feature"),
        (lambda spec: spec["layers"][1].update({"transform": {"rotate": 12}}), "unsupported_compositor_feature"),
        (lambda spec: spec["layers"][1].update({"id": "bad/id"}), "invalid_layer_id"),
        (lambda spec: spec["layers"][1].update({"position": {"x": "left", "y": 0}}), "invalid_position"),
        (lambda spec: spec["layers"][1].update({"duration": 1.0}), "invalid_layer_timing"),
        (lambda spec: spec["layers"][1].update({"effects": [{"type": "blur"}]}), "unsupported_compositor_feature"),
    ],
)
def test_composite_layers_rejects_invalid_specs(tmp_path, mutator, code):
    _write_minimal_assets(tmp_path)
    spec = _minimal_spec()
    mutator(spec)
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == code


def test_composite_layers_rejects_relative_source_escape(tmp_path):
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    spec = _minimal_spec()
    spec["layers"][0]["src"] = "../outside.mp4"
    (tmp_path / "outside.mp4").write_bytes(b"outside")
    (spec_dir / "plate.png").write_bytes(b"plate")
    (spec_dir / "title.png").write_bytes(b"title")
    spec_path = _write_spec(spec_dir, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(spec_dir / "out.mp4"))

    assert excinfo.value.code == "unsafe_layer_source"


def test_composite_layers_dry_run_supports_transform_mask_and_timing(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    spec = _minimal_spec()
    spec["layers"][1].update(
        {
            "mask": "mask.png",
            "transform": {"x": 8, "y": 10, "width": 80},
            "start": 0.25,
            "duration": 0.5,
        }
    )
    spec_path = _write_spec(tmp_path, spec)
    output = tmp_path / "out.mp4"
    plan = tmp_path / "layer-plan.json"
    calls = []

    monkeypatch.setattr("mcp_video.engine_composite_layers._run_ffmpeg", lambda args: calls.append(args.copy()))

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan), dry_run=True)

    assert calls == []
    assert not output.exists()
    assert result.dry_run is True
    assert result.operation == "composite_layers_dry_run"
    assert result.layer_plan["features"]["transforms"] is True
    assert result.layer_plan["features"]["masks"] is True
    assert result.layer_plan["features"]["timing_windows"] is True
    assert result.layer_plan["layers"][1]["mask"] == "mask.png"
    assert result.layer_plan["layers"][1]["mask_hash"].startswith("sha256:")

    saved = json.loads(plan.read_text())
    assert saved["output_hash"] is None
    graph_hash = saved["filtergraph_hash"]
    assert graph_hash.startswith("sha256:")


def test_composite_layers_scales_mask_to_transformed_layer(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    spec = _minimal_spec()
    spec["layers"][1].update({"mask": "mask.png", "transform": {"x": 8, "y": 10, "width": 80}})
    spec_path = _write_spec(tmp_path, spec)
    output = tmp_path / "out.mp4"
    calls = []

    def fake_run_ffmpeg(args):
        calls.append(args.copy())
        output.write_bytes(b"render")

    monkeypatch.setattr("mcp_video.engine_composite_layers._run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        "mcp_video.engine_probe.probe",
        lambda path: SimpleNamespace(duration=1.0, resolution="320x180", size_mb=0.1, format="mp4"),
    )

    composite_layers(str(spec_path), output_path=str(output))

    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "scale=80:-1" in graph
    assert "scale2ref=w=rw:h=rh" in graph
    assert "alphamerge" in graph


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_composite_layers_renders_video_with_transparent_png_overlays(tmp_path):
    bg = tmp_path / "bg.mp4"
    plate = tmp_path / "plate.png"
    title = tmp_path / "title.png"
    output = tmp_path / "out.mp4"
    plan = tmp_path / "plan.json"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=0.5:r=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(bg),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    for path, color in ((plate, "red@0.5"), (title, "green@0.7")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=20x20:d=0.1",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgba",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
    spec = _minimal_spec()
    spec["canvas"] = {"width": 64, "height": 64, "background": "#000000", "fps": 5, "duration": 0.5}
    spec["layers"][1]["position"] = {"x": 4, "y": 4}
    spec["layers"][2]["position"] = {"x": 30, "y": 30}
    spec_path = _write_spec(tmp_path, spec)

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan))

    assert output.is_file()
    assert plan.is_file()
    assert result.success is True
    assert result.resolution == "64x64"
    assert len(result.layer_plan["layers"]) == 3


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_composite_layers_renders_transformed_masked_timed_layer(tmp_path):
    bg = tmp_path / "bg.mp4"
    plate = tmp_path / "plate.png"
    mask = tmp_path / "mask.png"
    output = tmp_path / "out.mp4"
    plan = tmp_path / "plan.json"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=0.5:r=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(bg),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    for path, pix_fmt, color in ((plate, "rgba", "red@1"), (mask, "gray", "white")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=20x20:d=0.1",
                "-frames:v",
                "1",
                "-pix_fmt",
                pix_fmt,
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
    spec = {
        "canvas": {"width": 64, "height": 64, "background": "#000000", "fps": 5, "duration": 0.5},
        "layers": [
            {"id": "background", "type": "video", "src": "bg.mp4", "position": {"x": 0, "y": 0}},
            {
                "id": "plate",
                "type": "image",
                "src": "plate.png",
                "mask": "mask.png",
                "opacity": 0.8,
                "transform": {"x": 8, "y": 10, "width": 30},
                "start": 0,
                "duration": 0.5,
            },
        ],
        "output": {"format": "mp4"},
    }
    spec_path = _write_spec(tmp_path, spec)

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan))

    assert output.is_file()
    assert plan.is_file()
    assert result.success is True
    assert result.resolution == "64x64"
    assert result.layer_plan["features"]["transforms"] is True
    assert result.layer_plan["features"]["masks"] is True
    assert result.layer_plan["features"]["timing_windows"] is True
    assert result.layer_plan["output_hash"].startswith("sha256:")
