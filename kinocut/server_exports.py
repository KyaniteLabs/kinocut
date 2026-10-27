"""Lazy re-export machinery for the Kinocut server facade.

The repository readiness audit and architecture guardrails require
``kinocut/server.py`` to stay a pure re-export facade — no function/class
definitions and no top-level assignments.  Module-level ``__getattr__``
(PEP 562) keeps hidden tools and resources importable from the facade
without importing their modules eagerly, so the callable and the facade's
``__all__`` live here and the facade imports them.
"""

from __future__ import annotations

from typing import Any

from .tool_registry import TOOL_MODULE_BY_NAME, TOOL_REGISTRY, ensure_tool_loaded

_RESOURCE_EXPORTS = {
    "templates_resource": "templates_resource",
    "video_audio_resource": "video_audio_resource",
    "video_info_resource": "video_info_resource",
    "video_preview_resource": "video_preview_resource",
}

# Names the facade re-exports from server_app/tool_registry/server_tools_basic;
# listed here so kinocut.server can stay assignment-free (guardrail) while
# still owning one authoritative __all__.
_FACADE_EXPORTS = [
    "mcp",
    "_error_result",
    "_result",
    "CORE_TOOLS",
    "TOOL_REGISTRY",
    "VALID_XFADE_TRANSITIONS",
]

__all__ = [*_FACADE_EXPORTS, *_RESOURCE_EXPORTS, *sorted(TOOL_REGISTRY)]


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
