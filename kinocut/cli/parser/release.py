"""Flat release-artifact policy command parsers."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    review_package = subparsers.add_parser(
        "video-review-package",
        help="Assemble a review package and publish-gate verdict",
    )
    review_package.add_argument("project_dir")
    review_package.add_argument("candidate_artifact")
    review_package.add_argument("--blocking-finding", action="append", default=[])

    publish_gate = subparsers.add_parser("video-publish-gate", help="Evaluate the fail-closed publish gate")
    publish_gate.add_argument("project_dir")
    publish_gate.add_argument("candidate_artifact")
    publish_gate.add_argument("--blocking-finding", action="append", default=[])

    review_decision = subparsers.add_parser("video-review-decision", help="Record a human review decision")
    review_decision.add_argument("project_dir")
    review_decision.add_argument("--decision-json", required=True)

    learning_report = subparsers.add_parser("video-learning-report", help="Project a learning report from records")
    learning_report.add_argument("project_dir")

    cost_ledger = subparsers.add_parser("video-cost-ledger", help="Sum known USD cost events by category")
    cost_ledger.add_argument("project_dir")

    recipe_capture = subparsers.add_parser("video-recipe-capture", help="Capture a workflow recipe (idempotent by digest)")
    recipe_capture.add_argument("project_dir")
    recipe_capture.add_argument("--recipe-json", required=True)

    subparsers.add_parser("video-capabilities", help="Probe host capabilities (ffmpeg, whisper, c2pa)")

    subparsers.add_parser("video-benchmark-run", help="Run the AI-video benchmark corpus")
