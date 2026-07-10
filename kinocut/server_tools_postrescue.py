"""Post-rescue planning and verification MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .postrescue import (
    call_post_rescue,
    composition_plan,
    creative_autopilot_plan,
    remote_egress_plan,
    restoration_plan,
    semantic_query,
    semantic_timeline,
    timeline_edit_plan,
    visual_transform_plan,
)
from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_semantic_timeline(request: dict[str, Any]) -> dict[str, Any]:
    """Build a local, source-time semantic timeline from supplied analyzer evidence."""
    return _result(call_post_rescue(semantic_timeline, request))


@mcp.tool()
@_safe_tool
def video_semantic_query(request: dict[str, Any]) -> dict[str, Any]:
    """Query source-backed semantic spans locally without inventing descriptions."""
    return _result(call_post_rescue(semantic_query, request))


@mcp.tool()
@_safe_tool
def video_timeline_edit_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Plan explicit or ordinary-person timeline edits as a reviewable EDL and diff."""
    return _result(call_post_rescue(timeline_edit_plan, request))


@mcp.tool()
@_safe_tool
def video_visual_transform_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Plan subject/camera analysis, reframing, or stabilization with crop budgets."""
    return _result(call_post_rescue(visual_transform_plan, request))


@mcp.tool()
@_safe_tool
def video_restoration_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Plan or evaluate evidence-gated local restorative work."""
    return _result(call_post_rescue(restoration_plan, request))


@mcp.tool()
@_safe_tool
def video_composition_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Build source-backed manifests, selections, compositions, previews, and checks."""
    return _result(call_post_rescue(composition_plan, request))


@mcp.tool()
@_safe_tool
def video_creative_autopilot_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Coordinate proven local planners or return a structured abstention."""
    return _result(call_post_rescue(creative_autopilot_plan, request))


@mcp.tool()
@_safe_tool
def video_remote_egress_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Plan explicit remote egress and fake adapter receipts without network I/O."""
    return _result(call_post_rescue(remote_egress_plan, request))
