"""Dedicated rescue-pipeline CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add plan, render, and inspect rescue commands."""
    rescue_plan = subparsers.add_parser(
        "rescue-plan",
        help="Analyze a local video and write a policy-classified rescue plan",
    )
    rescue_plan.add_argument("--source", required=True, help="Path to the source video")
    rescue_plan.add_argument("--output-dir", required=True, help="Directory for previews, plans, and rescue packages")
    rescue_plan.add_argument("--save-plan", default=None, help="Optional path to write the rescue plan as JSON")
    rescue_plan.add_argument(
        "--policy",
        default="local_content_preserving",
        help="Rescue policy id (default: local_content_preserving)",
    )

    rescue_render = subparsers.add_parser(
        "rescue-render",
        help="Execute approved safe repairs from a reviewed rescue plan",
    )
    rescue_render.add_argument("--plan", required=True, help="Path to a persisted rescue plan")
    rescue_render.add_argument(
        "--approve",
        action="append",
        default=None,
        metavar="ID",
        help="Safe repair id to approve; repeat for multiple ids",
    )
    rescue_render.add_argument("--save-receipt", default=None, help="Optional path to copy the render receipt as JSON")
    rescue_render.add_argument("--resume", default=None, help="Optional prior rescue receipt to resume")
    rescue_render.add_argument("--cancel-file", default=None, help="Cancel when this marker file exists")
    rescue_render.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="Retain verified intermediates after successful promotion",
    )

    rescue_inspect = subparsers.add_parser(
        "rescue-inspect",
        help="Inspect a rescue plan or receipt and re-check artifact integrity",
    )
    rescue_inspect.add_argument("--receipt", required=True, help="Path to a rescue plan or render receipt")
