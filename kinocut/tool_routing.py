"""Resolve a refused operation to the surface that actually received it."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .cli.command_names import COMMAND_NAMES
from .type_names import builtin_type_name

_EXPLICIT_ROUTES: dict[str, str | None] = {
    "video_review_package": "video-review-package",
    "video_quality_check": "video-quality-check",
    "search_tools": None,
    "video_add_texts": None,
    "video_project_create": None,
    "video_shorts": None,
    "video_validate_text_layout": None,
}


def _cli_command_set() -> frozenset[str]:
    return COMMAND_NAMES


def cli_route_for_operation(operation: str) -> str | None:
    if operation in _EXPLICIT_ROUTES:
        return _EXPLICIT_ROUTES[operation]
    for candidate in (operation.removeprefix("video_"), operation):
        route = candidate.replace("_", "-")
        if route in COMMAND_NAMES:
            return route
    return None


@dataclass(frozen=True)
class RetryRoute:
    operation: str
    arguments: dict[str, Any]
    family: str | None = None
    cli: bool = False

    def mcp_target(self) -> str:
        if not self.family:
            return self.operation
        params = "..."
        if self.operation == "video_cleanup":
            params = ", ".join(
                f"{key}={_argument_type(self.arguments[key])}"
                for key in ("files", "keep")
                if self.arguments.get(key) is not None
            )
        return f'{self.family}(operation="{self.operation}", params={{{params}}})'


_current: ContextVar[RetryRoute | None] = ContextVar("kinocut_retry_route", default=None)


@contextmanager
def retry_context(
    tool_name: str, arguments: dict[str, Any] | None = None, *, family: str | None = None, cli: bool = False
):
    outer = _current.get()
    if outer and outer.family and outer.operation == tool_name and family is None:
        # The inner registered handler must not replace the caller's family address.
        yield
        return
    token = _current.set(RetryRoute(tool_name, arguments or {}, family, cli))
    try:
        yield
    finally:
        _current.reset(token)


def _argument_names(arguments: dict[str, Any]) -> str:
    """Name the arguments a failed call carried, without echoing their values.

    The retry context exists to make a refusal addressable — which tool, with
    which inputs — and the stored arguments are what make it so: the operator
    learns exactly which parameters the call carried, and therefore which one
    to correct. Each name carries its value's type as a replayable
    placeholder, so the invocation can be re-issued by substituting a value
    for the type. The values are the caller's own input and can be hostile (a
    validation error must not echo the value it just rejected), so only the
    names and types are named.
    """
    if not arguments:
        return ""
    parts = [f"{_argument_name(key)}={_argument_type(value)}" for key, value in arguments.items()]
    return " (arguments: " + ", ".join(sorted(parts)) + ")"


#: The type names a retry placeholder may publish. A class's ``__name__``
#: is mutable, caller-controlled data, so only shipped builtin categories
#: are named; anything else gets the fixed ``<object>`` placeholder.


def _argument_type(value: Any) -> str:
    """A replayable placeholder for one argument: its type, never its value.

    The category is read off the type object by identity against the
    shipped map (:func:`builtin_type_name`) — a caller's subclass that
    renames itself to a shipped category is still a subclass, so it gets
    the fixed ``<object>`` placeholder.
    """
    name = builtin_type_name(value)
    return f"<{name}>" if name is not None else "<object>"


def _argument_name(key: Any) -> str:
    """A bounded, package-authored name for one argument of a refused call.

    JSON and ``vars()`` give string keys; a string key is echoed (bounded,
    printable) because the operator must know which parameter to correct.
    A non-string key's text is not ours to publish — its ``str()`` is
    caller data, however the key's class renders itself — so it is named
    by a fixed placeholder instead.
    """
    if not isinstance(key, str):
        return "<non-string-key>"
    text = "".join(char if char.isprintable() else "_" for char in key)
    return text[:64] or "argument"


def _actions(code: str, submitted: str, *, params_overwrite: bool = False) -> tuple[str, str]:
    if code in {"output_exists", "overwrite_refused"}:
        mcp_overwrite = "params.overwrite=true" if params_overwrite else "overwrite=true"
        return f"{mcp_overwrite}{submitted}", f"--overwrite{submitted}"
    if code in {"unsafe_path", "invalid_output_path"}:
        return f"a new output_path{submitted}", f"--output <new-media-path>{submitted}"
    return f"corrected parameters{submitted}", f"corrected flags{submitted}"


def retry_message(message: str, code: str) -> str:
    route = _current.get()
    operation = route.operation if route else "the same tool"
    target = route.mcp_target() if route else operation
    submitted = _argument_names(route.arguments) if route and not route.family else ""
    params_overwrite = bool(
        route and route.family and isinstance(route.arguments, Mapping) and route.arguments.get("overwrite") is False
    )
    command = cli_route_for_operation(operation) if route else None
    mcp_action, cli_action = _actions(code, submitted, params_overwrite=params_overwrite)
    mcp = f"call {target} with {mcp_action}" if route else mcp_action
    cli = f"run kino {command} with {cli_action}" if command else cli_action
    if code in {"hyperframes_telemetry_consent_required", "network_consent_required"}:
        mcp = f"KINOCUT_HYPERFRAMES_TELEMETRY=true{submitted}"
        cli = f"KINOCUT_HYPERFRAMES_TELEMETRY=true kino {command or ''}{submitted}".rstrip()
    elif code in {"ffmpeg_not_found", "ffprobe_not_found"}:
        mcp = f"install FFmpeg, then call {target}{submitted}"
        cli = f"install FFmpeg, then run kino {command or ''}{submitted}".rstrip()
    if route and route.cli:
        invocation = f"{cli} (CLI)"
    elif route and route.family and operation == "video_cleanup":
        invocation = f"call {target} (MCP)"
    elif command or not route:
        invocation = f"{mcp} (MCP) / {cli} (CLI)"
    elif operation in _EXPLICIT_ROUTES and not route.family:
        invocation = (
            f"{mcp} (MCP) / no single-command CLI equivalent (run kino --help to browse related commands) (CLI)"
        )
    else:
        invocation = f"{mcp} (MCP)"
    return f"{message}; retry with {invocation}"
