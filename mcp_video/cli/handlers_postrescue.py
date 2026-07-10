"""CLI handlers for post-rescue planning capabilities."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .. import postrescue
from .runner import CommandRunner, _out


def _format_plan(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def handle_post_rescue_commands(args: Any, *, use_json: bool) -> bool:
    """Load one bounded request artifact and dispatch its planning command."""

    runner = CommandRunner(args, use_json)
    functions: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "semantic-timeline": postrescue.semantic_timeline,
        "semantic-query": postrescue.semantic_query,
        "timeline-edit-plan": postrescue.timeline_edit_plan,
        "visual-transform-plan": postrescue.visual_transform_plan,
        "restoration-plan": postrescue.restoration_plan,
        "composition-plan": postrescue.composition_plan,
        "creative-autopilot-plan": postrescue.creative_autopilot_plan,
        "remote-egress-plan": postrescue.remote_egress_plan,
    }

    for command, function in functions.items():

        def handler(a: Any, use_json_output: bool, fn: Callable = function) -> None:
            request = postrescue.load_post_rescue_request(a.request)
            result = postrescue.call_post_rescue(fn, request)
            _out(result, use_json_output, _format_plan)

        runner.register(command, handler)

    return runner.dispatch()
