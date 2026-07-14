"""Tests for spec-driven composite-layers."""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from mcp_video.engine_composite_layers import composite_layers
from mcp_video.errors import MCPVideoError
from mcp_video.limits import MAX_VIDEO_DURATION


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
        (lambda spec: spec["layers"][1].update({"blend": "difference"}), "unsupported_blend_mode"),
        (lambda spec: spec["layers"][1].update({"blend": "screen"}), "unsupported_blend_geometry"),
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


@pytest.mark.parametrize("field", ["src", "mask", "matte"])
def test_composite_layers_rejects_absolute_source_escape(tmp_path, field):
    # An ABSOLUTE src/mask/matte pointing outside the spec directory fails closed (it must
    # resolve UNDER spec_dir, matching the relative branch) — no read-any-absolute-file hole.
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "bg.mp4").write_bytes(b"bg")
    (spec_dir / "plate.png").write_bytes(b"plate")
    if field == "src":
        layers = [{"id": "background", "type": "video", "src": str(outside)}]
    else:
        layers = [
            {"id": "background", "type": "video", "src": "bg.mp4"},
            {"id": "plate", "type": "image", "src": "plate.png", field: str(outside)},
        ]
    spec = {
        "canvas": {"width": 64, "height": 64, "background": "#000000", "fps": 12, "duration": 1.0},
        "layers": layers,
    }
    spec_path = _write_spec(spec_dir, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(spec_dir / "out.mp4"))

    assert excinfo.value.code == "unsafe_layer_source"


@pytest.mark.parametrize(
    "canvas_over",
    [
        {"width": 100000, "height": 100000},
        {"width": 100000},
        {"height": 100000},
        {"duration": MAX_VIDEO_DURATION + 1},
    ],
)
def test_composite_layers_rejects_oversize_canvas(tmp_path, canvas_over):
    # Unbounded canvas dims/duration would fan out into a giant FFmpeg job (DoS); clamp them.
    _write_minimal_assets(tmp_path)
    spec = _minimal_spec()
    spec["canvas"].update(canvas_over)
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "invalid_canvas"


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
    # Bare scale2ref (no rw/rh expr) for FFmpeg 6 compatibility; the default
    # scales the mask to the layer/reference size on all supported versions.
    assert "scale2ref" in graph
    assert "scale2ref=w=rw:h=rh" not in graph
    assert "alphamerge" in graph


_BLEND_MODES = ["multiply", "screen", "overlay", "darken", "lighten"]


def _full_canvas_blend_spec(mode):
    """A base solid plus a full-canvas solid using ``mode`` (position {0,0}, opacity 1.0)."""
    return {
        "canvas": {"width": 64, "height": 64, "background": "#000000", "fps": 5, "duration": 0.5},
        "layers": [
            {"id": "base", "type": "solid", "color": "#204060"},
            {"id": "tint", "type": "solid", "color": "#a0c0e0", "blend": mode},
        ],
        "output": {"format": "mp4"},
    }


def _render_graph(tmp_path, spec, monkeypatch):
    """Run composite_layers with a stubbed ffmpeg and return (result, filtergraph)."""
    spec_path = _write_spec(tmp_path, spec)
    output = tmp_path / "out.mp4"
    calls = []

    def fake_run_ffmpeg(args):
        calls.append(args.copy())
        output.write_bytes(b"render")

    monkeypatch.setattr("mcp_video.engine_composite_layers._run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        "mcp_video.engine_probe.probe",
        lambda path: SimpleNamespace(duration=0.5, resolution="64x64", size_mb=0.1, format="mp4"),
    )
    result = composite_layers(str(spec_path), output_path=str(output))
    cmd = calls[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    return result, graph


@pytest.mark.parametrize("mode", _BLEND_MODES)
def test_composite_layers_accepts_full_canvas_blend(tmp_path, monkeypatch, mode):
    result, graph = _render_graph(tmp_path, _full_canvas_blend_spec(mode), monkeypatch)

    assert f"blend=all_mode={mode}" in graph
    assert "scale=64:64" in graph
    # The base layer ("base") is normal and still overlays onto the canvas;
    # only the "tint" blend layer uses the blend filter.
    assert graph.count("overlay=") == 1
    assert graph.count("blend=all_mode=") == 1
    assert graph.endswith(",format=yuv420p[vout]")
    assert result.layer_plan["layers"][1]["blend"] == mode
    assert result.layer_plan["features"]["blend_modes"] == sorted(["normal", mode])


def test_composite_layers_normal_layers_never_use_blend_filter(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    _result, graph = _render_graph(tmp_path, _minimal_spec(), monkeypatch)

    assert "blend=all_mode=" not in graph
    assert graph.count("overlay=") == 3


@pytest.mark.parametrize(
    "mutator",
    [
        lambda layer: layer.update({"position": {"x": 5, "y": 0}}),
        lambda layer: layer.update({"position": {"x": 0, "y": 7}}),
        lambda layer: layer.update({"scale": 2}),
        lambda layer: layer.update({"width": 32}),
        lambda layer: layer.update({"height": 32}),
        lambda layer: layer.update({"start": 0.1}),
        lambda layer: layer.update({"start": 0.1, "duration": 0.2}),
        lambda layer: layer.update({"opacity": 0.5}),
        lambda layer: layer.update({"mask": "mask.png"}),
        lambda layer: layer.update({"matte": "mask.png"}),
    ],
)
def test_composite_layers_rejects_non_full_canvas_blend(tmp_path, mutator):
    _write_minimal_assets(tmp_path)
    spec = _full_canvas_blend_spec("multiply")
    mutator(spec["layers"][1])
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_blend_geometry"


def test_composite_layers_rejects_unknown_blend_mode(tmp_path):
    spec = _full_canvas_blend_spec("difference")
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_blend_mode"


def test_composite_layers_receipt_summary_notes_blend(tmp_path, monkeypatch):
    result, _graph = _render_graph(tmp_path, _full_canvas_blend_spec("darken"), monkeypatch)

    assert any("blend=all_mode" in line for line in result.layer_plan["filtergraph_summary"])


def test_composite_layers_receipt_blend_modes_stays_normal_only_without_blend(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    result, _graph = _render_graph(tmp_path, _minimal_spec(), monkeypatch)

    assert result.layer_plan["features"]["blend_modes"] == ["normal"]


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
@pytest.mark.parametrize("mode", _BLEND_MODES)
def test_composite_layers_renders_full_canvas_blend(tmp_path, mode):
    spec = _full_canvas_blend_spec(mode)
    output = tmp_path / f"blend_{mode}.mp4"
    plan = tmp_path / "plan.json"
    spec_path = _write_spec(tmp_path, spec)

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan))

    assert output.is_file()
    assert output.stat().st_size > 0
    assert result.success is True
    assert result.resolution == "64x64"
    assert result.layer_plan["layers"][1]["blend"] == mode
    assert plan.is_file()


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_composite_layers_full_canvas_blend_is_ssim_stable_across_renders(tmp_path):
    """Deterministic-enough (not byte-identical) proof: two independent renders of the
    same full-canvas blend spec must be near-identical by SSIM. Reuses the existing
    engine_compare_quality SSIM utility rather than a new golden-frame fixture harness.
    """
    from mcp_video.engine_compare_quality import compare_quality

    spec = _full_canvas_blend_spec("multiply")
    spec_path = _write_spec(tmp_path, spec)
    out_a = tmp_path / "run_a.mp4"
    out_b = tmp_path / "run_b.mp4"

    composite_layers(str(spec_path), output_path=str(out_a))
    composite_layers(str(spec_path), output_path=str(out_b))

    quality = compare_quality(str(out_a), str(out_b), metrics=["ssim"])

    assert quality.metrics["ssim"] >= 0.98


# --- Story P1: positioned in-canvas non-normal blend -----------------------


def _positioned_blend_spec(mode, x=8, y=16, width=24, height=32):
    """Base solid plus a positioned in-canvas solid using ``mode``.

    The blend layer carries an explicit integral width/height and an integral,
    non-negative position whose rectangle sits fully inside the 64x64 canvas."""
    return {
        "canvas": {"width": 64, "height": 64, "background": "#000000", "fps": 5, "duration": 0.5},
        "layers": [
            {"id": "base", "type": "solid", "color": "#204060"},
            {
                "id": "tint",
                "type": "solid",
                "color": "#a0c0e0",
                "blend": mode,
                "position": {"x": x, "y": y},
                "width": width,
                "height": height,
            },
        ],
        "output": {"format": "mp4"},
    }


@pytest.mark.parametrize("mode", _BLEND_MODES)
def test_composite_layers_accepts_positioned_blend(tmp_path, monkeypatch, mode):
    result, graph = _render_graph(tmp_path, _positioned_blend_spec(mode), monkeypatch)

    # base crop (crop=W:H:X:Y), same-size blend, then overlay back at X:Y
    assert "crop=24:32:8:16" in graph
    assert f"blend=all_mode={mode}" in graph
    assert "overlay=8:16" in graph
    # the layer is scaled to the rectangle, never force-scaled to full canvas
    assert "scale=24:32" in graph
    assert "scale=64:64" not in graph
    # base normal overlay + the positioned re-overlay
    assert graph.count("overlay=") == 2
    assert graph.count("blend=all_mode=") == 1
    assert graph.count("crop=") == 1
    assert graph.endswith(",format=yuv420p[vout]")
    assert result.layer_plan["layers"][1]["blend"] == mode


def test_composite_layers_positioned_blend_filtergraph_splits_base_before_crop_and_overlay(tmp_path, monkeypatch):
    _result, graph = _render_graph(tmp_path, _positioned_blend_spec("overlay"), monkeypatch)

    # The running base is split so each output is consumed exactly once: one is
    # kept for the final overlay and the other is cropped for the tile blend.
    assert "[base1]split=2[layer2keep][layer2cropsource]" in graph
    assert "[layer2cropsource]crop=24:32:8:16[layer2base]" in graph
    assert "[layer2base][layer2]blend=all_mode=overlay[layer2blend]" in graph
    assert "[layer2keep][layer2blend]overlay=8:16:format=auto:eof_action=pass" in graph
    assert "[base1]crop=" not in graph
    assert "[base1][layer2blend]overlay=" not in graph


def test_composite_layers_positioned_blend_at_origin_is_valid(tmp_path, monkeypatch):
    # position {0,0} with an explicit sub-canvas rectangle is a valid positioned blend.
    _result, graph = _render_graph(tmp_path, _positioned_blend_spec("multiply", x=0, y=0), monkeypatch)

    assert "crop=24:32:0:0" in graph
    assert "overlay=0:0" in graph
    assert "blend=all_mode=multiply" in graph


def test_composite_layers_positioned_blend_rectangle_equal_to_canvas_is_valid(tmp_path, monkeypatch):
    # A rectangle that exactly fills the canvas is still fully inside it.
    _result, graph = _render_graph(
        tmp_path, _positioned_blend_spec("screen", x=0, y=0, width=64, height=64), monkeypatch
    )

    assert "crop=64:64:0:0" in graph
    assert "blend=all_mode=screen" in graph


@pytest.mark.parametrize("mode", _BLEND_MODES)
def test_composite_layers_positioned_blend_receipt_uses_existing_geometry_fields(tmp_path, monkeypatch, mode):
    result, _graph = _render_graph(tmp_path, _positioned_blend_spec(mode), monkeypatch)

    layer = result.layer_plan["layers"][1]
    assert layer["position"] == {"x": 8.0, "y": 16.0}
    assert layer["transform"]["width"] == 24
    assert layer["transform"]["height"] == 32
    assert "blend_geometry" not in layer
    assert result.layer_plan["features"]["positioned_blend"] is True
    assert result.layer_plan["features"]["blend_modes"] == sorted(["normal", mode])


def test_composite_layers_full_canvas_blend_receipt_preserves_layer_keys(tmp_path, monkeypatch):
    result, _graph = _render_graph(tmp_path, _full_canvas_blend_spec("multiply"), monkeypatch)

    assert "blend_geometry" not in result.layer_plan["layers"][1]
    assert result.layer_plan["features"]["positioned_blend"] is False


def test_composite_layers_positioned_blend_summary_note(tmp_path, monkeypatch):
    result, _graph = _render_graph(tmp_path, _positioned_blend_spec("darken"), monkeypatch)

    assert any("positioned" in line.lower() and "blend" in line.lower() for line in result.layer_plan["filtergraph_summary"])


@pytest.mark.parametrize(
    "mutator",
    [
        lambda layer: layer.update({"position": {"x": 8.5, "y": 16}}),  # fractional x
        lambda layer: layer.update({"position": {"x": 8, "y": 16.25}}),  # fractional y
        lambda layer: layer.update({"position": {"x": 48, "y": 16}}),  # x + width > canvas.width
        lambda layer: layer.update({"position": {"x": 8, "y": 48}}),  # y + height > canvas.height
        lambda layer: layer.update({"width": 80}),  # over-canvas width
        lambda layer: layer.update({"height": 80}),  # over-canvas height
        lambda layer: layer.pop("height"),  # width without height -> underivable rectangle
        lambda layer: layer.pop("width"),  # height without width -> underivable rectangle
        lambda layer: layer.update({"mask": "mask.png"}),  # positioned + mask deferred
        lambda layer: layer.update({"matte": "mask.png"}),  # positioned + matte deferred
        lambda layer: layer.update({"rotation": 45}),  # positioned + rotation deferred
        lambda layer: layer.update({"start": 0.1}),  # positioned + timing deferred
        lambda layer: layer.update({"start": 0.1, "duration": 0.2}),
        lambda layer: layer.update({"opacity": 0.5}),  # blend opacity stays full this release
    ],
)
def test_composite_layers_rejects_invalid_positioned_blend(tmp_path, mutator):
    _write_minimal_assets(tmp_path)
    spec = _positioned_blend_spec("multiply")
    mutator(spec["layers"][1])
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_blend_geometry"


def test_composite_layers_positioned_blend_with_video_layer_source(tmp_path, monkeypatch):
    # Positioned blend is not limited to solids: a video layer with an explicit
    # in-canvas rectangle and a non-normal blend is accepted too.
    _write_minimal_assets(tmp_path)
    spec = {
        "canvas": {"width": 320, "height": 180, "background": "#000000", "fps": 12, "duration": 1.0},
        "layers": [
            {"id": "background", "type": "video", "src": "bg.mp4", "position": {"x": 0, "y": 0}},
            {
                "id": "grain",
                "type": "video",
                "src": "bg.mp4",
                "blend": "overlay",
                "position": {"x": 40, "y": 30},
                "width": 120,
                "height": 90,
            },
        ],
        "output": {"format": "mp4"},
    }
    _result, graph = _render_graph(tmp_path, spec, monkeypatch)

    assert "crop=120:90:40:30" in graph
    assert "blend=all_mode=overlay" in graph
    assert "overlay=40:30" in graph


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
@pytest.mark.parametrize("mode", _BLEND_MODES)
def test_composite_layers_renders_positioned_blend(tmp_path, mode):
    spec = _positioned_blend_spec(mode)
    output = tmp_path / f"positioned_{mode}.mp4"
    plan = tmp_path / "plan.json"
    spec_path = _write_spec(tmp_path, spec)

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan))

    assert output.is_file()
    assert output.stat().st_size > 0
    assert result.success is True
    assert result.resolution == "64x64"
    layer = result.layer_plan["layers"][1]
    assert layer["position"] == {"x": 8.0, "y": 16.0}
    assert layer["transform"]["width"] == 24
    assert layer["transform"]["height"] == 32
    assert result.layer_plan["features"]["positioned_blend"] is True
    assert result.layer_plan["output_hash"].startswith("sha256:")
    assert plan.is_file()


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_composite_layers_positioned_blend_is_ssim_stable_across_renders(tmp_path):
    """Two independent renders of the same positioned blend spec must be near-identical."""
    from mcp_video.engine_compare_quality import compare_quality

    spec = _positioned_blend_spec("multiply")
    spec_path = _write_spec(tmp_path, spec)
    out_a = tmp_path / "run_a.mp4"
    out_b = tmp_path / "run_b.mp4"

    composite_layers(str(spec_path), output_path=str(out_a))
    composite_layers(str(spec_path), output_path=str(out_b))

    quality = compare_quality(str(out_a), str(out_b), metrics=["ssim"])

    assert quality.metrics["ssim"] >= 0.98


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


# --- Story 7: rotation + pivot ---------------------------------------------

_PIVOTS = ["center", "top_left", "top_right", "bottom_left", "bottom_right"]


def _rotation_spec(rotation=45, pivot=None, **layer_extra):
    """Base video + an image plate carrying rotation (position {20, 16})."""
    plate = {"id": "plate", "type": "image", "src": "plate.png", "position": {"x": 20, "y": 16}, "rotation": rotation}
    if pivot is not None:
        plate["pivot"] = pivot
    plate.update(layer_extra)
    return {
        "canvas": {"width": 320, "height": 180, "background": "#000000", "fps": 12, "duration": 1.0},
        "layers": [
            {"id": "background", "type": "video", "src": "bg.mp4", "position": {"x": 0, "y": 0}},
            plate,
        ],
        "output": {"format": "mp4"},
    }


@pytest.mark.parametrize("rotation", [45, -30, 0, 360, -360, 12.5])
def test_composite_layers_accepts_valid_rotation(tmp_path, monkeypatch, rotation):
    _write_minimal_assets(tmp_path)
    result, graph = _render_graph(tmp_path, _rotation_spec(rotation=rotation), monkeypatch)

    assert "rotate=" in graph
    assert result.layer_plan["layers"][1]["transform"]["rotation"] == float(rotation)
    assert result.layer_plan["features"]["rotation"] is True


@pytest.mark.parametrize("rotation", [361, -361, 500, -720])
def test_composite_layers_rejects_out_of_range_rotation(tmp_path, rotation):
    _write_minimal_assets(tmp_path)
    spec_path = _write_spec(tmp_path, _rotation_spec(rotation=rotation))

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "invalid_transform"


@pytest.mark.parametrize("rotation", ["spin", [1, 2], {"deg": 3}])
def test_composite_layers_rejects_non_numeric_rotation(tmp_path, rotation):
    _write_minimal_assets(tmp_path)
    spec_path = _write_spec(tmp_path, _rotation_spec(rotation=rotation))

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_compositor_feature"


def test_validate_rotation_rejects_non_finite():
    from mcp_video.engine_composite_layers_rotate import validate_rotation

    layer = SimpleNamespace(id="plate", rotation=float("inf"), pivot=None, mask=None, matte=None)
    with pytest.raises(MCPVideoError) as excinfo:
        validate_rotation(layer)

    assert excinfo.value.code == "invalid_transform"


@pytest.mark.parametrize("pivot", _PIVOTS)
def test_composite_layers_accepts_each_pivot(tmp_path, monkeypatch, pivot):
    _write_minimal_assets(tmp_path)
    result, graph = _render_graph(tmp_path, _rotation_spec(rotation=45, pivot=pivot), monkeypatch)

    assert result.layer_plan["layers"][1]["transform"]["pivot"] == pivot
    assert "rotate=" in graph


def test_composite_layers_rejects_unknown_pivot(tmp_path):
    _write_minimal_assets(tmp_path)
    spec_path = _write_spec(tmp_path, _rotation_spec(rotation=45, pivot="middle"))

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_compositor_feature"


def test_composite_layers_rejects_pivot_without_rotation(tmp_path):
    _write_minimal_assets(tmp_path)
    spec = _rotation_spec(rotation=45, pivot="center")
    del spec["layers"][1]["rotation"]  # pivot present, rotation absent
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "invalid_transform"


def test_composite_layers_rejects_rotation_with_blend(tmp_path):
    """Rotation composes with the overlay path only; blend stays full-canvas-only."""
    spec = _full_canvas_blend_spec("multiply")
    spec["layers"][1]["rotation"] = 45
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_blend_geometry"


@pytest.mark.parametrize("mask_key", ["mask", "matte"])
def test_composite_layers_rejects_rotation_with_mask(tmp_path, mask_key):
    """Rotation + mask/matte is deferred this release and fails closed."""
    _write_minimal_assets(tmp_path)
    spec = _rotation_spec(rotation=45, **{mask_key: "mask.png"})
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_compositor_feature"


def _anchor_alias_spec(position_key):
    """A no-rotation spec whose plate is placed via ``position_key`` (anchor|position)."""
    return {
        "canvas": {"width": 320, "height": 180, "background": "#000000", "fps": 12, "duration": 1.0},
        "layers": [
            {"id": "background", "type": "video", "src": "bg.mp4", "position": {"x": 0, "y": 0}},
            {"id": "plate", "type": "image", "src": "plate.png", "opacity": 0.75, position_key: {"x": 24, "y": 12}},
        ],
        "output": {"format": "mp4"},
    }


def test_composite_layers_anchor_still_behaves_as_position_alias(tmp_path, monkeypatch):
    """Regression: `anchor` remains a position alias, identical to before Story 7 —
    it must NOT gain any rotation/pivot behavior."""
    _write_minimal_assets(tmp_path)
    _anchor_result, anchor_graph = _render_graph(tmp_path, _anchor_alias_spec("anchor"), monkeypatch)
    _pos_result, position_graph = _render_graph(tmp_path, _anchor_alias_spec("position"), monkeypatch)

    assert anchor_graph == position_graph
    assert "overlay=24:12" in anchor_graph  # anchor coords placed directly, no pivot offset
    assert "rotate=" not in anchor_graph
    assert _anchor_result.layer_plan["layers"][1]["transform"]["rotation"] is None
    assert _anchor_result.layer_plan["layers"][1]["transform"]["pivot"] is None
    assert _anchor_result.layer_plan["features"]["rotation"] is False


def test_composite_layers_rotation_filtergraph_order_and_transparent_fill(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    _result, graph = _render_graph(tmp_path, _rotation_spec(rotation=30, scale=1.5), monkeypatch)

    # transparent-fill rotate with expanded bounding box
    assert "rotate=" in graph
    assert "fillcolor=none" in graph
    assert "rotw(" in graph and "roth(" in graph
    # order within the plate pipeline: scale -> rotate -> opacity -> position(overlay)
    scale_pos = graph.index("scale=iw*1.5")  # unique to the plate layer
    rotate_pos = graph.index("rotate=")  # only the plate rotates
    opacity_pos = graph.index("colorchannelmixer", rotate_pos)  # the plate's opacity, after rotate
    overlay_pos = graph.rindex("overlay=")  # the plate's overlay, last in the chain
    assert scale_pos < rotate_pos < opacity_pos < overlay_pos
    # rotation is never interpolated raw: the graph carries a formatted radian literal, not "30"
    assert "rotate=30:" not in graph


@pytest.mark.parametrize(
    ("pivot", "expected"),
    [
        ("center", "overlay=20-w/2:16-h/2"),
        ("top_left", "overlay=20:16"),
        ("top_right", "overlay=20-w:16"),
        ("bottom_left", "overlay=20:16-h"),
        ("bottom_right", "overlay=20-w:16-h"),
    ],
)
def test_composite_layers_pivot_sets_overlay_reference_point(tmp_path, monkeypatch, pivot, expected):
    _write_minimal_assets(tmp_path)
    _result, graph = _render_graph(tmp_path, _rotation_spec(rotation=45, pivot=pivot), monkeypatch)

    assert expected in graph


def test_composite_layers_receipt_is_layer_plan_v2(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    result, _graph = _render_graph(tmp_path, _minimal_spec(), monkeypatch)

    assert result.layer_plan["schema_version"] == 2
    assert result.layer_plan["receipt_kind"] == "layer_plan"
    assert result.layer_plan["audio_policy"] == "dropped_video_only"
    assert result.layer_plan["features"]["audio"] == "dropped"
    # no rotation in this spec
    assert result.layer_plan["features"]["rotation"] is False
    assert result.layer_plan["layers"][1]["transform"]["rotation"] is None
    assert result.layer_plan["layers"][1]["transform"]["pivot"] is None
    # unchanged transform receipt keys still present
    assert set(result.layer_plan["layers"][1]["transform"]) == {"width", "height", "scale", "rotation", "pivot"}


def test_composite_layers_receipt_records_rotation_and_pivot(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    result, _graph = _render_graph(tmp_path, _rotation_spec(rotation=-30, pivot="top_right"), monkeypatch)

    transform = result.layer_plan["layers"][1]["transform"]
    assert transform["rotation"] == -30.0
    assert transform["pivot"] == "top_right"
    assert result.layer_plan["features"]["rotation"] is True
    assert any("rotated layers" in line for line in result.layer_plan["filtergraph_summary"])


def test_composite_layers_rotation_default_pivot_is_center(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    result, graph = _render_graph(tmp_path, _rotation_spec(rotation=45), monkeypatch)

    assert result.layer_plan["layers"][1]["transform"]["pivot"] == "center"
    assert "overlay=20-w/2:16-h/2" in graph


def test_composite_layers_dry_run_rotation_receipt_is_consistent(tmp_path, monkeypatch):
    _write_minimal_assets(tmp_path)
    spec_path = _write_spec(tmp_path, _rotation_spec(rotation=90, pivot="bottom_left"))
    output = tmp_path / "out.mp4"
    plan = tmp_path / "plan.json"
    calls = []

    monkeypatch.setattr("mcp_video.engine_composite_layers._run_ffmpeg", lambda args: calls.append(args.copy()))

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan), dry_run=True)

    assert calls == []
    assert not output.exists()
    assert result.layer_plan["schema_version"] == 2
    assert result.layer_plan["receipt_kind"] == "layer_plan"
    assert result.layer_plan["features"]["rotation"] is True
    assert result.layer_plan["layers"][1]["transform"]["rotation"] == 90.0
    assert result.layer_plan["layers"][1]["transform"]["pivot"] == "bottom_left"
    saved = json.loads(plan.read_text())
    assert saved["output_hash"] is None
    assert saved["schema_version"] == 2


def test_composite_layers_unknown_transform_key_still_rejected(tmp_path):
    """A `rotate` key nested under `transform` is still an unknown transform key
    (rotation is a top-level `layer.rotation` field, not a transform key)."""
    _write_minimal_assets(tmp_path)
    spec = _minimal_spec()
    spec["layers"][1].update({"transform": {"rotate": 12}})
    spec_path = _write_spec(tmp_path, spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert excinfo.value.code == "unsupported_compositor_feature"


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_composite_layers_renders_rotated_image_over_solid_canvas(tmp_path):
    plate = tmp_path / "plate.png"
    output = tmp_path / "rotated.mp4"
    plan = tmp_path / "plan.json"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=24x16:d=0.1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgba",
            str(plate),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    spec = {
        "canvas": {"width": 64, "height": 64, "background": "#101010", "fps": 5, "duration": 0.5},
        "layers": [
            {"id": "base", "type": "solid", "color": "#204060"},
            {"id": "plate", "type": "image", "src": "plate.png", "position": {"x": 32, "y": 32}, "rotation": 45},
        ],
        "output": {"format": "mp4"},
    }
    spec_path = _write_spec(tmp_path, spec)

    result = composite_layers(str(spec_path), output_path=str(output), save_layer_plan=str(plan))

    assert output.is_file()
    assert output.stat().st_size > 0
    assert result.success is True
    assert result.resolution == "64x64"
    assert result.layer_plan["features"]["rotation"] is True
    assert result.layer_plan["layers"][1]["transform"]["rotation"] == 45.0
    assert result.layer_plan["layers"][1]["transform"]["pivot"] == "center"
    assert result.layer_plan["output_hash"].startswith("sha256:")


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_composite_layers_rotation_is_ssim_stable_across_renders(tmp_path):
    """Two independent renders of the same rotated spec must be near-identical by
    SSIM (mirrors the Story 6 blend self-consistency check)."""
    from mcp_video.engine_compare_quality import compare_quality

    plate = tmp_path / "plate.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=24x16:d=0.1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgba",
            str(plate),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    spec = {
        "canvas": {"width": 64, "height": 64, "background": "#101010", "fps": 5, "duration": 0.5},
        "layers": [
            {"id": "base", "type": "solid", "color": "#204060"},
            {"id": "plate", "type": "image", "src": "plate.png", "position": {"x": 32, "y": 32}, "rotation": 30},
        ],
        "output": {"format": "mp4"},
    }
    spec_path = _write_spec(tmp_path, spec)
    out_a = tmp_path / "run_a.mp4"
    out_b = tmp_path / "run_b.mp4"

    composite_layers(str(spec_path), output_path=str(out_a))
    composite_layers(str(spec_path), output_path=str(out_b))

    quality = compare_quality(str(out_a), str(out_b), metrics=["ssim"])

    assert quality.metrics["ssim"] >= 0.98
