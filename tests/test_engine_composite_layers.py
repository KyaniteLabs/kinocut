"""Tests for spec-driven composite-layers P1."""

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
    bg.write_bytes(b"bg")
    plate.write_bytes(b"plate")
    title.write_bytes(b"title")
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
    assert result.layer_plan["render_determinism_scope"].startswith("layer-plan receipt only")
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
        (lambda spec: spec["layers"][1].update({"mask": "mask.png"}), "unsupported_compositor_feature"),
        (lambda spec: spec["layers"][1].update({"id": "bad/id"}), "invalid_layer_id"),
    ],
)
def test_composite_layers_rejects_invalid_p1_specs(tmp_path, mutator, code):
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
