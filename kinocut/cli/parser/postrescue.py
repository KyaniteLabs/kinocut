"""CLI parsers for post-rescue planning capabilities."""

from __future__ import annotations

import argparse


COMMANDS = {
    "semantic-timeline": "Build a source-backed semantic timeline",
    "semantic-query": "Query a local semantic timeline",
    "timeline-edit-plan": "Build a reviewable timeline edit plan",
    "visual-transform-plan": "Plan visual analysis, reframing, or stabilization",
    "restoration-plan": "Plan or evaluate restorative work",
    "composition-plan": "Plan and verify source-backed composition work",
    "creative-autopilot-plan": "Coordinate available local creative planners",
    "remote-egress-plan": "Plan and approve explicit remote egress",
}


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add flat commands that consume one reviewable JSON request artifact."""

    for command, help_text in COMMANDS.items():
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("request", help="Path to a UTF-8 JSON request artifact")
