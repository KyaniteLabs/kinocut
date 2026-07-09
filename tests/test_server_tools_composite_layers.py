"""Tests for the composite-layers MCP tool wrapper."""

from __future__ import annotations

import json

from mcp_video.server_tools_advanced import video_composite_layers


def test_video_composite_layers_returns_structured_error_for_missing_spec():
    result = video_composite_layers("/definitely/missing/layers.json")

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


def test_video_composite_layers_surfaces_blend_geometry_error(tmp_path):
    spec = {
        "canvas": {"width": 64, "height": 64, "background": "#000000", "fps": 5, "duration": 0.5},
        "layers": [
            {"id": "base", "type": "solid", "color": "#204060"},
            {"id": "tint", "type": "solid", "color": "#a0c0e0", "blend": "multiply", "position": {"x": 8, "y": 8}},
        ],
    }
    spec_path = tmp_path / "layers.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = video_composite_layers(str(spec_path), output_path=str(tmp_path / "out.mp4"))

    assert result["success"] is False
    assert result["error"]["code"] == "unsupported_blend_geometry"


def test_video_composite_layers_wraps_engine_result(monkeypatch):
    def fake_composite_layers(spec_path, output_path=None, save_layer_plan=None, dry_run=False):
        return {
            "output_path": output_path or "out.mp4",
            "layer_plan_path": save_layer_plan,
            "layer_plan": {"tool": "video_composite_layers"},
            "dry_run": dry_run,
        }

    monkeypatch.setattr("mcp_video.server_tools_advanced.composite_layers", fake_composite_layers)

    result = video_composite_layers("layers.json", output_path="out.mp4", save_layer_plan="plan.json", dry_run=True)

    assert result["success"] is True
    assert result["output_path"] == "out.mp4"
    assert result["layer_plan_path"] == "plan.json"
    assert result["layer_plan"]["tool"] == "video_composite_layers"
    assert result["dry_run"] is True
