"""Namespaced CLI parser group (#52): ``kino aivideo <action>`` aliases.

Each namespace sub-action mirrors the corresponding flat command's arguments
exactly and dispatches to the SAME handler (see cli/handlers_aivideo.py
``handle_aivideo_namespace``) via ``cli/namespaces.py``. Flat commands are
preserved unchanged; the namespace is an additive alias surface.
"""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    group = subparsers.add_parser(
        "aivideo",
        help="Namespaced AI-video commands (aliases over flat video-* handlers)",
    )
    aivideo = group.add_subparsers(dest="aivideo_command", required=True)

    verdict = aivideo.add_parser("verdict", help="Alias for video-verdict")
    verdict.add_argument("project_dir")
    verdict.add_argument("--verdict-json", required=True)

    acceptance = aivideo.add_parser("acceptance", help="Alias for video-acceptance-eval")
    acceptance.add_argument("project_dir")
    acceptance.add_argument("acceptance_spec_id")
    acceptance.add_argument("--verdict-id", action="append", default=[])

    swap = aivideo.add_parser("body-swap", help="Alias for video-body-swap")
    swap.add_argument("project_dir")
    swap.add_argument("video_source")
    swap.add_argument("audio_source")
    swap.add_argument("output_path")
    swap.add_argument("--duration-policy", choices=("pad_video", "trim_video", "trim_audio"))
    swap.add_argument("--authorization-decision-id", action="append", default=[])

    salvage = aivideo.add_parser("salvage", help="Alias for video-salvage")
    salvage.add_argument("project_dir")
    salvage.add_argument("source_asset_id")
    salvage.add_argument(
        "recipe",
        choices=("clean_edges", "freeze_extension", "still_frame", "region_crop", "background_only"),
    )
    salvage.add_argument("acceptance_spec_id")
    salvage.add_argument("--policy-json", required=True)
    salvage.add_argument("--authorization-decision-id", action="append", default=[])
