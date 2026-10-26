"""Kinocut MCP server facade with profile-driven lazy tool registration."""

from __future__ import annotations

from typing import Any

from .server_app import _error_result as _error_result
from .server_app import _result as _result
from .server_app import mcp as mcp
from .tool_registry import (
    CORE_TOOLS,
    TOOL_REGISTRY,
    TOOL_MODULE_BY_NAME,
    configure_tool_surface,
    ensure_tool_loaded,
)
from .server_tools_basic import VALID_XFADE_TRANSITIONS as VALID_XFADE_TRANSITIONS


_RESOURCE_EXPORTS = {
    "templates_resource": "templates_resource",
    "video_audio_resource": "video_audio_resource",
    "video_info_resource": "video_info_resource",
    "video_preview_resource": "video_preview_resource",
}


# Load only the selected MCP surface at import time. Compatibility imports of
# hidden Python functions still work through ``__getattr__`` without making
# those functions visible to MCP clients.
configure_tool_surface()


def __getattr__(name: str) -> Any:
    if name in TOOL_MODULE_BY_NAME:
        return ensure_tool_loaded(name)
    if name == "VALID_XFADE_TRANSITIONS":
        from .server_tools_basic import VALID_XFADE_TRANSITIONS

        return VALID_XFADE_TRANSITIONS
    resource_name = _RESOURCE_EXPORTS.get(name)
    if resource_name is not None:
        from . import server_resources

        return getattr(server_resources, resource_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "mcp",
    "_error_result",
    "_result",
    "CORE_TOOLS",
    "TOOL_REGISTRY",
    "VALID_XFADE_TRANSITIONS",
    *_RESOURCE_EXPORTS,
    *sorted(TOOL_REGISTRY),
]
