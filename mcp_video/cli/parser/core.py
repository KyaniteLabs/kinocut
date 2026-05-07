"""Core CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add core subcommands to the CLI parser."""
    # doctor
    doctor_p = subparsers.add_parser("doctor", help="Diagnose core and optional integration dependencies")
    doctor_p.add_argument("--json", action="store_true", help="Output diagnostics as JSON")

    # info
    info_p = subparsers.add_parser("info", help="Get video metadata")
    info_p.add_argument("input", help="Input video file")

    # extract-frame
    eframe_p = subparsers.add_parser("extract-frame", help="Extract a single frame from a video")
    eframe_p.add_argument("input", help="Input video file")
    eframe_p.add_argument(
        "-t", "--time", dest="timestamp", type=float, help="Time in seconds (default: 10 pct of duration)"
    )
    eframe_p.add_argument("-o", "--output", help="Output image path")

    # trim
    trim_p = subparsers.add_parser("trim", help="Trim a video")
    trim_p.add_argument("input", help="Input video file")
    trim_p.add_argument("-s", "--start", default="0", help="Start time")
    trim_p.add_argument("-d", "--duration", help="Duration")
    trim_p.add_argument("-e", "--end", help="End time")
    trim_p.add_argument("-o", "--output", help="Output file path")

    # merge
    merge_p = subparsers.add_parser("merge", help="Merge multiple clips")
    merge_p.add_argument("inputs", nargs="+", help="Input video files")
    merge_p.add_argument(
        "-t",
        "--transition",
        default=None,
        choices=["fade", "dissolve", "wipe-left", "wipe-right", "wipe-up", "wipe-down"],
    )
    merge_p.add_argument(
        "--transitions",
        nargs="+",
        choices=["fade", "dissolve", "wipe-left", "wipe-right", "wipe-up", "wipe-down"],
        help="Per-pair transition types (overrides --transition)",
    )
    merge_p.add_argument("-td", "--transition-duration", type=float, default=1.0, help="Transition duration in seconds")
    merge_p.add_argument("-o", "--output", help="Output file path")

    # edit (timeline)
    edit_p = subparsers.add_parser("edit", help="Execute timeline-based edit from JSON")
    edit_p.add_argument("timeline", help="Path to timeline JSON file")
    edit_p.add_argument("-o", "--output", help="Output file path")

    # blur (convenience)
    blur_p = subparsers.add_parser("blur", help="Apply blur effect")
    blur_p.add_argument("input", help="Input video file")
    blur_p.add_argument("-r", "--radius", type=int, default=5, help="Blur radius (default: 5)")
    blur_p.add_argument("-s", "--strength", type=int, default=1, help="Blur strength (default: 1)")
    blur_p.add_argument("-o", "--output", help="Output file path")

    # color-grade (convenience)
    grade_p = subparsers.add_parser("color-grade", help="Apply color grading preset")
    grade_p.add_argument("input", help="Input video file")
    grade_p.add_argument(
        "-p", "--preset", default="warm", choices=["warm", "cool", "vintage", "cinematic", "noir"], help="Color preset"
    )
    grade_p.add_argument("-o", "--output", help="Output file path")

    # templates (list available templates)
    subparsers.add_parser("templates", help="List available video templates")

    # template (apply a template)
    template_p = subparsers.add_parser("template", help="Apply a video template")
    template_p.add_argument(
        "name",
        choices=["tiktok", "youtube-shorts", "instagram-reel", "youtube", "instagram-post"],
        help="Template name",
    )
    template_p.add_argument("input", help="Input video file")
    template_p.add_argument("--caption", help="Caption text (for tiktok, instagram)")
    template_p.add_argument("--title", help="Title text (for youtube-shorts, youtube)")
    template_p.add_argument("--music", help="Background music file")
    template_p.add_argument("--outro", help="Outro video file (for youtube)")
    template_p.add_argument("-o", "--output", help="Output file path")

    repurpose_plan_p = subparsers.add_parser("repurpose-plan", help="Create a dry-run repurposing manifest")
    repurpose_plan_p.add_argument("input", help="Input video file")
    repurpose_plan_p.add_argument("-o", "--output-dir", help="Package output directory")
    repurpose_plan_p.add_argument("--platforms", nargs="+", help="Platforms to include")

    repurpose_p = subparsers.add_parser("repurpose", help="Render a local repurposing package")
    repurpose_p.add_argument("input", help="Input video file")
    repurpose_p.add_argument("-o", "--output-dir", help="Package output directory")
    repurpose_p.add_argument("--platforms", nargs="+", help="Platforms to include")
    repurpose_p.add_argument("--skip-release-checkpoint", action="store_true")
    repurpose_p.add_argument("--min-score", type=float, default=0.0)

    # Effect commands

    # Transition commands

    # AI commands

    # Audio synthesis commands

    # Motion graphics commands

    # Layout commands

    # Audio-Video commands

    # Quality / Info commands

    # video-extract-frame
    eframe_p = subparsers.add_parser("video-extract-frame", help="Extract a single frame (alias for thumbnail)")
    eframe_p.add_argument("input", help="Input video file")
    eframe_p.add_argument("-t", "--timestamp", type=float, help="Time in seconds (default: 10%% of duration)")
    eframe_p.add_argument("-o", "--output", help="Output image path")

    # Image analysis commands
