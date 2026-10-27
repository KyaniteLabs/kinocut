"""Kinocut MCP server facade with profile-driven lazy tool registration."""

from __future__ import annotations

from .server_app import _error_result as _error_result
from .server_app import _result as _result
from .server_app import mcp as mcp
from .server_exports import __all__ as __all__  # re-exported facade surface
from .server_exports import __getattr__ as __getattr__  # PEP 562 lazy re-exports
from .tool_registry import (
    CORE_TOOLS as CORE_TOOLS,
    TOOL_REGISTRY as TOOL_REGISTRY,
    TOOL_MODULE_BY_NAME as TOOL_MODULE_BY_NAME,
    configure_tool_surface,
    ensure_tool_loaded as ensure_tool_loaded,
)
from .server_tools_basic import VALID_XFADE_TRANSITIONS as VALID_XFADE_TRANSITIONS
from . import server_resources  # noqa: F401  — resource registration (mcp-video:// URIs)


# Load only the selected MCP surface at import time. Compatibility imports of
# hidden Python functions still work through ``__getattr__`` without making
# those functions visible to MCP clients.
configure_tool_surface()
