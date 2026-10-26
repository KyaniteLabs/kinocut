"""Lazy attribute hook for the :mod:`kinocut.server` facade (PEP 562).

The server module must stay a thin facade (repository readiness audit and
``test_architecture_guardrails``), so the module-level ``__getattr__`` that
resolves compatibility imports lives here and is re-exported by
``kinocut/server.py``. Hidden tools stay callable from Python without being
registered on the active MCP surface.
"""

from __future__ import annotations

from typing import Any

from .tool_registry import TOOL_MODULE_BY_NAME, ensure_tool_loaded


_RESOURCE_EXPORTS = {
    "templates_resource": "templates_resource",
    "video_audio_resource": "video_audio_resource",
    "video_info_resource": "video_info_resource",
    "video_preview_resource": "video_preview_resource",
}


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
    raise AttributeError(f"module 'kinocut.server' has no attribute {name!r}")
