"""CLI argument parser subpackage."""

from __future__ import annotations

import argparse

from . import advanced
from . import ai
from . import audio
from . import core
from . import effects
from . import image
from . import layout
from . import media
from . import quality
from . import rescue
from . import postrescue
from . import hyperframes
from . import workflow
from . import inspection
from . import aivideo
from . import release


def build_parser() -> argparse.ArgumentParser:
    """Build and return the Kinocut CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="kino",
        description="Kinocut - trusted video editing for AI agents (and humans)",
        epilog=(
            "Namespaced aliases: `kino <group> <action> ...` rewrites to the matching "
            "flat command (e.g. `kino aivideo verdict` -> `kino video-verdict`). "
            "Groups: aivideo, audio, qa, edit. The flat command set above is unchanged."
        ),
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Run as MCP server (default mode)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "auto"],
        default="text",
        help="Output format: text (default), json, or auto (json when stdout is piped)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging to stderr",
    )
    subparsers = parser.add_subparsers(dest="command", help="CLI commands")

    core.add_parsers(subparsers)
    media.add_parsers(subparsers)
    effects.add_parsers(subparsers)
    advanced.add_parsers(subparsers)
    audio.add_parsers(subparsers)
    ai.add_parsers(subparsers)
    hyperframes.add_parsers(subparsers)
    layout.add_parsers(subparsers)
    image.add_parsers(subparsers)
    quality.add_parsers(subparsers)
    workflow.add_parsers(subparsers)
    rescue.add_parsers(subparsers)
    postrescue.add_parsers(subparsers)
    inspection.add_parsers(subparsers)
    aivideo.add_parsers(subparsers)
    release.add_parsers(subparsers)

    return parser
