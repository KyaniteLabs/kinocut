"""Kinocut CLI entry point."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from .cli.parser import build_parser
from .cli.formatting import _format_error, console, err_console

logger = logging.getLogger(__name__)


def _import_mcp_server() -> Any:
    from .server import mcp

    return mcp


def _run_mcp_mode(import_server: Callable[[], Any] = _import_mcp_server) -> None:
    """Start the MCP server, reporting import failures under their real cause.

    Only the genuine absence of the ``mcp`` package keeps the install hint.
    Any other import failure in the server tree previously masqueraded as a
    missing ``mcp`` package (#445), hiding the real error from users.
    """

    try:
        mcp = import_server()
        mcp.run()
    except ImportError as exc:
        missing = getattr(exc, "name", None)
        if missing == "mcp" or (missing or "").startswith("mcp."):
            err_console.print(
                "[red]MCP mode requires the 'mcp' package.[/red]\nInstall with: [bold]pip install kinocut[/bold]",
            )
        else:
            err_console.print(f"[red]MCP mode failed to start:[/red] {type(exc).__name__}: {exc}")
        sys.exit(1)


def _rewrite_namespaced_argv(argv: list[str]) -> list[str]:
    """Rewrite a namespaced ``group action`` argv prefix to the matching flat command.

    Scans ``argv`` (the tail past the program name) over the recognized global
    options — boolean ``-v``/``--verbose``/``--mcp``/``--version`` and the value-taking
    ``--format VALUE`` (also ``--format=VALUE``). When the first positional token is a
    namespace group whose following token resolves via
    :func:`kinocut.cli.namespaces.resolve_namespaced`, the ``(group, action)`` pair is
    replaced by the flat command name and every other token is preserved verbatim.
    Anything else — an unrecognized option, no action following the group, an unknown
    group/action, or an option value in the action slot — returns ``argv`` unchanged so
    argparse handles it natively. The flat command set is never modified.
    """

    from .cli.namespaces import resolve_namespaced

    boolean_globals = {"-v", "--verbose", "--mcp", "--version"}
    value_globals = {"--format", "--log-file"}
    i = 0
    n = len(argv)
    while i < n:
        arg = argv[i]
        if arg in boolean_globals:
            i += 1
            continue
        if arg in value_globals:
            if i + 1 >= n:
                return argv  # malformed flag; defer to argparse
            i += 2
            continue
        if arg.startswith("--format=") or arg.startswith("--log-file="):
            i += 1
            continue
        if arg.startswith("-"):
            # Unknown option: never risk treating its value as the group.
            return argv
        if i + 1 >= n:
            return argv  # group present without a paired action
        flat = resolve_namespaced(arg, argv[i + 1])
        if flat is None:
            return argv  # unknown group/action — fall through unchanged
        return [*argv[:i], flat, *argv[i + 2 :]]
    return argv


def _configure_logging(*, verbose: bool, log_file: str | None) -> None:
    """Attach structured DEBUG logging to stderr and/or a file."""
    if not verbose and not log_file:
        return
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if verbose:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
        logger.debug("Structured logging enabled; file=%s verbose_stderr=%s", log_file, verbose)


def _dispatch_cli(args: object, *, use_json: bool) -> bool:
    from .cli.handlers_advanced import handle_advanced_commands
    from .cli.handlers_ai import handle_ai_commands
    from .cli.handlers_aivideo import handle_aivideo_commands
    from .cli.handlers_audio import handle_audio_commands
    from .cli.handlers_composition import handle_composition_command
    from .cli.handlers_core import handle_initial_command
    from .cli.handlers_effects import handle_effect_command
    from .cli.handlers_hyperframes import handle_hyperframes_commands
    from .cli.handlers_image import handle_image_commands
    from .cli.handlers_inspection import handle_inspection_commands
    from .cli.handlers_intent import handle_intent_commands
    from .cli.handlers_media import handle_media_commands
    from .cli.handlers_postrescue import handle_post_rescue_commands
    from .cli.handlers_release import handle_release_commands
    from .cli.handlers_rescue import handle_rescue_commands
    from .cli.handlers_shorts import handle_shorts_commands
    from .cli.handlers_sound import handle_sound_commands
    from .cli.handlers_transitions import handle_transition_command
    from .cli.handlers_workflow import handle_workflow_commands

    return bool(
        handle_initial_command(args, use_json=use_json)
        or handle_aivideo_commands(args, use_json=use_json)
        or handle_release_commands(args, use_json=use_json)
        or handle_shorts_commands(args, use_json=use_json)
        or handle_sound_commands(args, use_json=use_json)
        or handle_inspection_commands(args, use_json=use_json)
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
        or handle_intent_commands(args, use_json=use_json)
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args(_rewrite_namespaced_argv(sys.argv[1:]))

    _configure_logging(verbose=bool(getattr(args, "verbose", False)), log_file=getattr(args, "log_file", None))

    if args.version:
        from . import __version__

        console.print(f"Kinocut [bold]{__version__}[/bold]")
        return

    if args.mcp or args.command is None:
        _run_mcp_mode()
        return

    from .cli.runner import resolve_use_json

    use_json = resolve_use_json(args.format, sys.stdout.isatty())

    try:
        if args.command in {"doctor", "info"}:
            from .cli.handlers_core import handle_initial_command

            if handle_initial_command(args, use_json=use_json):
                return
        if _dispatch_cli(args, use_json=use_json):
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
