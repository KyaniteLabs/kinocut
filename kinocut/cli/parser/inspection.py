"""Flat Wave-2 inspection command parsers."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    ingest = subparsers.add_parser("video-ingest", help="Ingest immutable media into a project")
    ingest.add_argument("project_dir")
    ingest.add_argument("source_path")
    ingest.add_argument("--lineage-json", default=None)
    ingest.add_argument(
        "--usage-rights-status",
        choices=("cleared", "pending", "restricted", "unknown"),
        default="unknown",
    )
    ingest.add_argument("--usage-rights-evidence-ref", default=None)

    preflight = subparsers.add_parser("video-preflight", help="Preflight a stored project asset")
    preflight.add_argument("project_dir")
    preflight.add_argument("asset_id")

    inspect = subparsers.add_parser("video-inspect-temporal", help="Build the complete temporal inspection package")
    inspect.add_argument("project_dir")
    inspect.add_argument("asset_id")
    inspect.add_argument("--regions-json", default=None)
