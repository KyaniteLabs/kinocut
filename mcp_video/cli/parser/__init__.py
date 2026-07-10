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


def build_parser() -> argparse.ArgumentParser:
    """Build and return the mcp-video CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="mcp-video",
        description="mcp-video — Video editing for AI agents (and humans)",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Run as MCP server (default mode)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
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

    return parser
