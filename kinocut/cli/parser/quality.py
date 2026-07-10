"""Quality CLI subcommands."""

from __future__ import annotations

import argparse


def _add_command_output_format(parser: argparse.ArgumentParser) -> None:
    """Allow quality commands to accept the global output format locally.

    Argparse normally requires global options before the subcommand. Quality
    commands do not use a command-local ``--format`` flag, so accepting it here
    makes dogfood-friendly invocations such as
    ``mcp-video video-quality-check input.mp4 --format json`` work without
    changing the existing global form.
    """
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default=argparse.SUPPRESS,
        help="Output format; equivalent to global --format for this command",
    )


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add quality subcommands to the CLI parser."""
    # video-auto-chapters
    achap_p = subparsers.add_parser("video-auto-chapters", help="Auto-detect scene changes and create chapters")
    achap_p.add_argument("input", help="Input video file")
    achap_p.add_argument("-t", "--threshold", type=float, default=0.3, help="Scene detection threshold (default: 0.3)")
    _add_command_output_format(achap_p)

    # video-info-detailed
    idetail_p = subparsers.add_parser("video-info-detailed", help="Get extended video metadata with scene detection")
    idetail_p.add_argument("input", help="Input video file")
    _add_command_output_format(idetail_p)

    # video-quality-check
    qcheck_p = subparsers.add_parser("video-quality-check", help="Run visual quality checks on a video")
    qcheck_p.add_argument("input", help="Input video file")
    qcheck_p.add_argument("--fail-on-warning", action="store_true", help="Treat warnings as failures")
    _add_command_output_format(qcheck_p)

    # video-design-quality-check
    dqcheck_p = subparsers.add_parser("video-design-quality-check", help="Run design quality analysis on a video")
    dqcheck_p.add_argument("input", help="Input video file")
    dqcheck_p.add_argument("--auto-fix", action="store_true", help="Automatically fix issues where possible")
    dqcheck_p.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    _add_command_output_format(dqcheck_p)

    # video-fix-design-issues
    dfix_p = subparsers.add_parser("video-fix-design-issues", help="Auto-fix design issues in a video")
    dfix_p.add_argument("input", help="Input video file")
    dfix_p.add_argument("-o", "--output", help="Output file path (auto-generated if omitted)")
    _add_command_output_format(dfix_p)
