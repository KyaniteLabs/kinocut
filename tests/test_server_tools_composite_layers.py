"""Tests for the composite-layers MCP tool wrapper."""

from __future__ import annotations

from mcp_video.server_tools_advanced import video_composite_layers


def test_video_composite_layers_returns_structured_error_for_missing_spec():
    result = video_composite_layers("/definitely/missing/layers.json")

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


def test_video_composite_layers_wraps_engine_result(monkeypatch):
    def fake_composite_layers(spec_path, output_path=None, save_layer_plan=None):
        return {
            "output_path": output_path or "out.mp4",
            "layer_plan_path": save_layer_plan,
            "layer_plan": {"tool": "video_composite_layers"},
        }

    monkeypatch.setattr("mcp_video.server_tools_advanced.composite_layers", fake_composite_layers)

    result = video_composite_layers("layers.json", output_path="out.mp4", save_layer_plan="plan.json")

    assert result["success"] is True
    assert result["output_path"] == "out.mp4"
    assert result["layer_plan_path"] == "plan.json"
    assert result["layer_plan"]["tool"] == "video_composite_layers"
