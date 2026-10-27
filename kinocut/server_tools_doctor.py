"""Core MCP environment doctor."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_doctor() -> dict[str, Any]:
    """Return a read-only JSON readiness verdict for the next video job."""

    from .doctor import run_diagnostics

    return _result(run_diagnostics())
