"""Flat CLI parsers for saved-plan shorts stages."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    show = subparsers.add_parser(
        "shorts-plan-show",
        help="Show proposals from a saved shorts plan (source-free)",
    )
    show.add_argument("plan", help="Path to a plan file or directory containing exactly one plan")

    review = subparsers.add_parser(
        "shorts-review",
        help="Append a human review decision to a saved shorts plan",
    )
    review.add_argument("plan", help="Path to a plan file or directory containing exactly one plan")
    review.add_argument("--candidate-id", required=True)
    review.add_argument(
        "--decision",
        required=True,
        help="approve | reject | trim | title_hook_edit | sensitivity, or JSON object",
    )
    review.add_argument("--evidence-ref", default=None)

    render = subparsers.add_parser(
        "shorts-render",
        help="Render approved platform drafts from a saved shorts plan",
    )
    render.add_argument("plan", help="Path to a plan file or directory containing exactly one plan")
    render.add_argument("--candidate-id", required=True)
    render.add_argument("-o", "--output", dest="output_path", default=None)

    package = subparsers.add_parser(
        "shorts-package",
        help="Package approved platform renders from a saved shorts plan",
    )
    package.add_argument("plan", help="Path to a plan file or directory containing exactly one plan")
    package.add_argument("--candidate-id", required=True)
    package.add_argument("--package-root", default=None)
    package.add_argument("--overwrite", action="store_true")
