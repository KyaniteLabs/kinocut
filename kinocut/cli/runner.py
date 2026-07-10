"""CommandRunner seam for CLI handlers."""

from __future__ import annotations

import importlib
from typing import Any
from collections.abc import Callable

from .common import _with_spinner, output_json


class CommandRunner:
    """Dispatches CLI commands to registered handlers."""

    def __init__(self, args: Any, use_json: bool):
        self.args = args
        self.use_json = use_json
        self._handlers: dict[str, Callable] = {}

    def register(self, command: str, handler: Callable):
        """Register a command handler. handler takes (args, use_json)."""
        self._handlers[command] = handler

    def dispatch(self) -> bool:
        """Run the registered command if it matches args.command. Return True if handled."""
        handler = self._handlers.get(self.args.command)
        if handler:
            handler(self.args, self.use_json)
            return True
        return False


def _resolve_engine(engine_fn: Callable | str) -> Callable:
    """Resolve an engine function from a callable or import string like 'mcp_video.engine:trim'."""
    if callable(engine_fn):
        return engine_fn
    if isinstance(engine_fn, str):
        module_path, fn_name = engine_fn.rsplit(":", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, fn_name)
    raise TypeError(f"engine_fn must be callable or str, got {type(engine_fn)}")


def _build_args(
    args: Any, parg_attrs: tuple[str, ...], kwarg_attrs: dict[str, str]
) -> tuple[list[Any], dict[str, Any]]:
    """Build positional and keyword args from an args namespace."""
    pargs = [getattr(args, a) for a in parg_attrs]
    kwargs = {k: getattr(args, v) for k, v in kwarg_attrs.items()}
    return pargs, kwargs


def engine_cmd(
    engine_fn: Callable | str,
    spinner_msg: str,
    *parg_attrs: str,
    formatter: Callable | None = None,
    json_transform: Callable | None = None,
    **kwarg_attrs: str,
) -> Callable:
    """Create a handler for a standard engine command with spinner.

    engine_fn: callable or string like 'mcp_video.engine:trim'
    spinner_msg: message shown in the spinner
    parg_attrs: attribute names on args for positional arguments
    kwarg_attrs: keyword arg names mapped to attribute names on args
    formatter: text output formatter callable
    json_transform: JSON output transform callable
    """

    def handler(args: Any, use_json: bool) -> None:
        fn = _resolve_engine(engine_fn)
        pargs, kwargs = _build_args(args, parg_attrs, kwarg_attrs)
        result = _with_spinner(spinner_msg, fn, *pargs, **kwargs)
        if use_json:
            output_json(json_transform(result) if json_transform else result)
        else:
            formatter(result) if formatter else print(result)

    return handler


def plain_cmd(
    engine_fn: Callable | str,
    *parg_attrs: str,
    formatter: Callable | None = None,
    json_transform: Callable | None = None,
    **kwarg_attrs: str,
) -> Callable:
    """Create a handler for a standard engine command without spinner.

    Same signature as engine_cmd but skips the spinner.
    """

    def handler(args: Any, use_json: bool) -> None:
        fn = _resolve_engine(engine_fn)
        pargs, kwargs = _build_args(args, parg_attrs, kwarg_attrs)
        result = fn(*pargs, **kwargs)
        if use_json:
            output_json(json_transform(result) if json_transform else result)
        else:
            formatter(result) if formatter else print(result)

    return handler


def _out(
    result: Any,
    use_json: bool,
    formatter: Callable | None = None,
    *,
    json_transform: Callable | None = None,
) -> None:
    """Helper for custom handlers: emit JSON or formatted text."""
    if use_json:
        output_json(json_transform(result) if json_transform else result)
    else:
        formatter(result) if formatter else print(result)
