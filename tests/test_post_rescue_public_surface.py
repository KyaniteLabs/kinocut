from __future__ import annotations

import asyncio

from mcp_video.cli.parser import build_parser
from mcp_video.client import Client


EXPECTED_TOOLS = {
    "video_semantic_timeline",
    "video_semantic_query",
    "video_timeline_edit_plan",
    "video_visual_transform_plan",
    "video_restoration_plan",
    "video_composition_plan",
    "video_creative_autopilot_plan",
    "video_remote_egress_plan",
}

EXPECTED_COMMANDS = {
    "semantic-timeline",
    "semantic-query",
    "timeline-edit-plan",
    "visual-transform-plan",
    "restoration-plan",
    "composition-plan",
    "creative-autopilot-plan",
    "remote-egress-plan",
}

EXPECTED_CLIENT_METHODS = {
    "semantic_timeline",
    "semantic_query",
    "timeline_edit_plan",
    "visual_transform_plan",
    "restoration_plan",
    "composition_plan",
    "creative_autopilot_plan",
    "remote_egress_plan",
}


def test_post_rescue_capabilities_have_mcp_cli_and_python_parity() -> None:
    from mcp_video.server import mcp

    tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    parser = build_parser()
    command_action = next(action for action in parser._actions if action.dest == "command")
    command_names = set(command_action.choices)

    assert tool_names >= EXPECTED_TOOLS
    assert command_names >= EXPECTED_COMMANDS
    assert all(hasattr(Client, method) for method in EXPECTED_CLIENT_METHODS)
