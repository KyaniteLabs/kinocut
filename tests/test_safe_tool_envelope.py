"""The @_safe_tool error envelope must hold for exception types it has never seen.

An uncaught exception propagating to the MCP layer would break the client
session; every tool must return the structured {"success": False, ...} shape
no matter what the engine throws.
"""

from __future__ import annotations

import asyncio

import pytest

import mcp_video.server_tools_basic as server_tools_basic


@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("bad"), OSError(28, "No space left on device")])
def test_novel_exception_types_return_error_envelope(monkeypatch, sample_video, exc):
    def explode(*args, **kwargs):
        raise exc

    monkeypatch.setattr(server_tools_basic, "trim", explode)

    result = asyncio.run(server_tools_basic.video_trim(sample_video, start="0", duration="1"))

    assert isinstance(result, dict)
    assert result["success"] is False
    assert "error" in result
