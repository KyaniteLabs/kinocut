"""Kinocut MCP server facade with profile-driven lazy tool registration."""

from __future__ import annotations

from .server_app import _error_result as _error_result
from .server_app import _result as _result
from .server_app import mcp as mcp
from .server_lazy import _RESOURCE_EXPORTS
from .server_lazy import __getattr__ as __getattr__  # PEP 562 facade hook
from .tool_registry import CORE_TOOLS, TOOL_REGISTRY, configure_tool_surface
from .server_tools_basic import VALID_XFADE_TRANSITIONS as VALID_XFADE_TRANSITIONS


# Load only the selected MCP surface at import time. Compatibility imports of
# hidden Python functions still work through the PEP 562 hook re-exported from
# ``server_lazy`` above, without making those functions visible to MCP clients.
configure_tool_surface()


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
