"""Layout CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add layout subcommands to the CLI parser."""
    # video-text-animated
    tanim_p = subparsers.add_parser("video-text-animated", help="Add animated text to video")
    tanim_p.add_argument("input", help="Input video file")
    tanim_p.add_argument("text", help="Text to display")
    tanim_p.add_argument("-o", "--output", help="Output file path")
    tanim_p.add_argument(
        "-a",
        "--animation",
        default="fade",
        choices=["fade", "slide-up", "typewriter", "glitch"],
        help="Animation type (default: fade)",
    )
    tanim_p.add_argument("--font", default="Arial", help="Font family (default: Arial)")
    tanim_p.add_argument("--size", type=int, default=48, help="Font size in pixels (default: 48)")
    tanim_p.add_argument("--color", default="white", help="Text color (default: white)")
    tanim_p.add_argument(
        "-p",
        "--position",
        default="center",
        choices=["center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"],
        help="Text position (default: center)",
    )
    tanim_p.add_argument("--start", type=float, default=0, help="Start time in seconds (default: 0)")
    tanim_p.add_argument("--duration", type=float, default=3.0, help="Display duration in seconds (default: 3.0)")
    tanim_p.add_argument(
        "--typewriter-speed", type=float, default=0.08, help="Seconds per character for typewriter (default: 0.08)"
    )

    # video-mograph-count
    mcount_p = subparsers.add_parser("video-mograph-count", help="Generate animated number counter video")
    mcount_p.add_argument("start", type=int, help="Starting number")
    mcount_p.add_argument("end", type=int, help="Ending number")
    mcount_p.add_argument("-d", "--duration", type=float, required=True, help="Animation duration in seconds")
    mcount_p.add_argument("-o", "--output", required=True, help="Output video file path")
    mcount_p.add_argument("--style", help='Style as JSON: {"font": "Arial", "size": 160, "color": "white"}')
    mcount_p.add_argument("--fps", type=int, default=30, help="Frame rate (default: 30)")

    # video-mograph-progress
    mprog_p = subparsers.add_parser("video-mograph-progress", help="Generate progress bar / loading animation")
    mprog_p.add_argument("-d", "--duration", type=float, required=True, help="Animation duration in seconds")
    mprog_p.add_argument("-o", "--output", required=True, help="Output video file path")
    mprog_p.add_argument(
        "--style", default="bar", choices=["bar", "circle", "dots"], help="Progress style (default: bar)"
    )
    mprog_p.add_argument("--color", default="#CCFF00", help="Progress color hex (default: #CCFF00)")
    mprog_p.add_argument("--track-color", default="#333333", help="Track background color hex (default: #333333)")
    mprog_p.add_argument("--fps", type=int, default=30, help="Frame rate (default: 30)")

    # video-layout-grid
    lgrid_p = subparsers.add_parser("video-layout-grid", help="Arrange multiple videos in a grid")
    lgrid_p.add_argument("inputs", nargs="+", help="Input video files")
    lgrid_p.add_argument(
        "-l", "--layout", default="2x2", choices=["2x2", "3x1", "1x3", "2x3"], help="Grid layout (default: 2x2)"
    )
    lgrid_p.add_argument("-o", "--output", required=True, help="Output file path")
    lgrid_p.add_argument("--gap", type=int, default=10, help="Gap between clips in pixels (default: 10)")
    lgrid_p.add_argument("--padding", type=int, default=20, help="Padding around grid in pixels (default: 20)")
    lgrid_p.add_argument("--background", default="#141414", help="Background color hex (default: #141414)")

    # video-layout-pip
    lpip_p = subparsers.add_parser("video-layout-pip", help="Picture-in-picture overlay with border")
    lpip_p.add_argument("main", help="Main video file")
    lpip_p.add_argument("pip", help="Picture-in-picture video file")
    lpip_p.add_argument("-o", "--output", required=True, help="Output file path")
    lpip_p.add_argument(
        "-p",
        "--position",
        default="bottom-right",
        choices=["top-left", "top-right", "bottom-left", "bottom-right"],
        help="PIP position (default: bottom-right)",
    )
    lpip_p.add_argument(
        "-s", "--size", type=float, default=0.25, help="PIP size as fraction of main 0-1 (default: 0.25)"
    )
    lpip_p.add_argument("--margin", type=int, default=20, help="Margin from edges in pixels (default: 20)")
    lpip_p.add_argument("--border", action="store_true", default=True, help="Add border around PIP (default: True)")
    lpip_p.add_argument("--no-border", dest="border", action="store_false", help="Disable border around PIP")
    lpip_p.add_argument("--border-color", default="#CCFF00", help="Border color hex (default: #CCFF00)")
    lpip_p.add_argument("--border-width", type=int, default=2, help="Border width in pixels (default: 2)")
    lpip_p.add_argument(
        "--rounded-corners", action="store_true", default=True, help="Apply rounded corners to PIP (default: True)"
    )
    lpip_p.add_argument(
        "--no-rounded-corners", dest="rounded_corners", action="store_false", help="Disable rounded corners"
    )

    comp_p = subparsers.add_parser("composite-layers", help="Composite ordered image/video layers from a JSON spec")
    comp_p.add_argument("--spec", required=True, help="Path to composite-layers JSON spec")
    comp_p.add_argument("-o", "--output", dest="output", help="Output media path")
    comp_p.add_argument("--save-layer-plan", help="Write deterministic resolved layer-plan receipt JSON")
