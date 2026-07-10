"""Kinocut CLI entry point."""

from __future__ import annotations

import json
import logging
import sys

from .cli.handlers_advanced import handle_advanced_commands
from .cli.handlers_ai import handle_ai_commands
from .cli.handlers_audio import handle_audio_commands
from .cli.handlers_composition import handle_composition_command
from .cli.handlers_core import handle_initial_command
from .cli.handlers_effects import handle_effect_command
from .cli.handlers_image import handle_image_commands
from .cli.handlers_media import handle_media_commands
from .cli.handlers_hyperframes import handle_hyperframes_commands
from .cli.handlers_rescue import handle_rescue_commands
from .cli.handlers_postrescue import handle_post_rescue_commands
from .cli.handlers_transitions import handle_transition_command
from .cli.handlers_workflow import handle_workflow_commands
from .cli.parser import build_parser
from .cli.formatting import _format_error, console, err_console

logger = logging.getLogger(__name__)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    # --version
    if args.version:
        from . import __version__

        console.print(f"Kinocut [bold]{__version__}[/bold]")
        return

    # Default mode: run MCP server
    if args.mcp or args.command is None:
        try:
            from .server import mcp

            mcp.run()
        except ImportError:
            err_console.print(
                "[red]MCP mode requires the 'mcp' package.[/red]\n"
                "Install with: [bold]pip install kinocut[/bold]",
            )
            sys.exit(1)
        return

    use_json = args.format == "json"

    # CLI command dispatch chain
    try:
        if (
            handle_initial_command(args, use_json=use_json)
            or handle_workflow_commands(args, use_json=use_json)
            or handle_rescue_commands(args, use_json=use_json)
            or handle_post_rescue_commands(args, use_json=use_json)
            or handle_effect_command(args, use_json=use_json)
            or handle_transition_command(args, use_json=use_json)
            or handle_composition_command(args, use_json=use_json)
            or handle_media_commands(args, use_json=use_json)
            or handle_hyperframes_commands(args, use_json=use_json)
            or handle_ai_commands(args, use_json=use_json)
            or handle_audio_commands(args, use_json=use_json)
            or handle_advanced_commands(args, use_json=use_json)
            or handle_image_commands(args, use_json=use_json)
        ):
            return

    except Exception as e:
        if use_json:
            from .errors import MCPVideoError

            if isinstance(e, MCPVideoError):
                try:
                    err_data = e.to_dict()
                except Exception as exc:
                    logger.warning("MCPVideoError.to_dict() failed: %s", exc)
                    err_data = {"type": "internal_error", "code": "to_dict_failed", "message": str(e)}
                print(json.dumps({"success": False, "error": err_data}, indent=2), file=sys.stderr)
            else:
                print(
                    json.dumps({"success": False, "error": {"type": "unknown", "message": str(e)}}, indent=2),
                    file=sys.stderr,
                )
        else:
            _format_error(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
