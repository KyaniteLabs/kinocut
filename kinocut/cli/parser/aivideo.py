"""Flat Wave 3 governed AI-video command parsers."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    verdict = subparsers.add_parser(
        "video-verdict",
        help="Persist exact-asset analysis; approvals require human evidence",
    )
    verdict.add_argument("project_dir")
    verdict.add_argument("--verdict-json", required=True)

    acceptance = subparsers.add_parser("video-acceptance-eval", help="Evaluate governed acceptance evidence")
    acceptance.add_argument("project_dir")
    acceptance.add_argument("acceptance_spec_id")
    acceptance.add_argument("--verdict-id", action="append", default=[])

    swap = subparsers.add_parser("video-body-swap", help="Replace video while preserving approved audio")
    swap.add_argument("project_dir")
    swap.add_argument("video_source")
    swap.add_argument("audio_source")
    swap.add_argument("output_path")
    swap.add_argument("--duration-policy", choices=("pad_video", "trim_video", "trim_audio"))
    swap.add_argument("--authorization-decision-id", action="append", default=[])

    salvage = subparsers.add_parser("video-salvage", help="Create a lineage-bound salvage derivative")
    salvage.add_argument("project_dir")
    salvage.add_argument("source_asset_id")
    salvage.add_argument(
        "recipe",
        choices=(
            "clean_edges",
            "freeze_extension",
            "still_frame",
            "region_crop",
            "background_only",
        ),
    )
    salvage.add_argument("acceptance_spec_id")
    salvage.add_argument("--policy-json", required=True)
    salvage.add_argument("--authorization-decision-id", action="append", default=[])
