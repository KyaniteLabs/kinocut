"""Quality CLI subcommands."""

from __future__ import annotations

import argparse


def _add_command_output_format(parser: argparse.ArgumentParser) -> None:
    """Allow quality commands to accept the global output format locally.

    Argparse normally requires global options before the subcommand. Quality
    commands do not use a command-local ``--format`` flag, so accepting it here
    makes dogfood-friendly invocations such as
    ``kino video-quality-check input.mp4 --format json`` work without
    changing the existing global form.
    """
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default=argparse.SUPPRESS,
        help="Output format; equivalent to global --format for this command",
    )


def _add_quality_profile(parser: argparse.ArgumentParser) -> None:
    """Content profile for the picture heuristics (#679)."""
    from kinocut.quality_profiles import DEFAULT_QUALITY_PROFILE, QUALITY_PROFILES

    parser.add_argument(
        "--profile",
        choices=list(QUALITY_PROFILES),
        default=DEFAULT_QUALITY_PROFILE,
        help="Content profile: default (camera footage), dark-grade (footage graded dark on purpose), "
        "ui-capture-dark or ui-capture-light; "
        "recorded in the report (default: default)",
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
    _add_quality_profile(qcheck_p)
    _add_command_output_format(qcheck_p)

    # video-design-quality-check
    dqcheck_p = subparsers.add_parser("video-design-quality-check", help="Run design quality analysis on a video")
    dqcheck_p.add_argument("input", help="Input video file")
    dqcheck_p.add_argument("--auto-fix", action="store_true", help="Automatically fix issues where possible")
    dqcheck_p.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    _add_command_output_format(dqcheck_p)

    # video-fix-design-issues
    dfix_p = subparsers.add_parser(
        "video-fix-design-issues", help="Auto-fix brightness and saturation in a video; audio is not changed"
    )
    dfix_p.add_argument("input", help="Input video file")
    dfix_p.add_argument("-o", "--output", help="Output file path (auto-generated if omitted)")
    _add_command_output_format(dfix_p)

    # release-checkpoint (CLI passthrough of the MCP video_release_checkpoint tool)
    from kinocut.defaults import DEFAULT_QUALITY_GATE_SCORE

    rcheck_p = subparsers.add_parser(
        "release-checkpoint",
        help="Hard release quality gate, then thumbnail + storyboard for human review",
    )
    rcheck_p.add_argument("input", help="Input video file")
    rcheck_p.add_argument("-o", "--output-dir", help="Review artifact directory (default: <input>_release_review)")
    rcheck_p.add_argument(
        "--min-score",
        type=float,
        default=DEFAULT_QUALITY_GATE_SCORE,
        help=f"Minimum quality score 0-100 (default: {DEFAULT_QUALITY_GATE_SCORE})",
    )
    rcheck_p.add_argument("--frame-count", type=int, default=6, help="Storyboard frame count (default: 6)")
    _add_quality_profile(rcheck_p)
    rcheck_p.add_argument(
        "--profile-reason",
        help="Why a non-default profile fits this cut; required when the default profile would fail it",
    )
    rcheck_p.add_argument(
        "--require-audio", action=argparse.BooleanOptionalAction, default=True, help="Require an audio stream"
    )
    _add_command_output_format(rcheck_p)
