"""Workflow-engine CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add workflow-engine subcommands to the CLI parser."""
    wf_validate = subparsers.add_parser(
        "workflow-validate",
        help="Validate a workflow job-spec without rendering any media",
    )
    wf_validate.add_argument("--spec", required=True, help="Path to the workflow job-spec JSON file")

    wf_plan = subparsers.add_parser(
        "workflow-plan",
        help="Produce a no-render plan (op graph, source probes, hashes) for a workflow job-spec",
    )
    wf_plan.add_argument("--spec", required=True, help="Path to the workflow job-spec JSON file")
    wf_plan.add_argument("--save-plan", default=None, help="Optional path to write the plan artifact as JSON")

    wf_render = subparsers.add_parser(
        "workflow-render",
        help="Execute a workflow job-spec sequentially and emit a provenance receipt",
    )
    wf_render.add_argument("--spec", required=True, help="Path to the workflow job-spec JSON file")
    wf_render.add_argument(
        "--resume", default=None, help="Optional path to a prior render receipt to resume from"
    )
    wf_render.add_argument(
        "--save-receipt", default=None, help="Optional path to write the workflow receipt as JSON"
    )

    wf_inspect = subparsers.add_parser(
        "workflow-inspect",
        help="Summarize any workflow/layer_plan receipt with a read-only integrity check",
    )
    wf_inspect.add_argument("--receipt", required=True, help="Path to the receipt JSON file to inspect")
