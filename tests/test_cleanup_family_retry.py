"""Cleanup refusals should describe the call that can actually be retried."""

from __future__ import annotations

import asyncio

import pytest

from kinocut.server import mcp
from kinocut.tool_registry import configure_tool_surface


@pytest.fixture(autouse=True)
def _restore_tool_surface(monkeypatch):
    monkeypatch.delenv("KINOCUT_TOOLS", raising=False)
    yield
    configure_tool_surface("all")


def test_cleanup_refusal_retry_uses_family_tool_and_cleanup_params(tmp_path):
    configure_tool_surface()
    user_file = tmp_path / "notes_review_card.html"
    user_file.write_text("user-owned review card", encoding="utf-8")

    result = asyncio.run(
        mcp.call_tool(
            "video_edit_ops",
            {
                "operation": "video_cleanup",
                "params": {"files": [str(user_file)], "keep": None},
            },
        )
    )
    message = result.structuredContent["results"][0]["error"]

    assert user_file.exists()
    assert 'call video_edit_ops(operation="video_cleanup", params={files=<list>})' in message
    assert "NoneType" not in message
    assert "video_cleanup with corrected parameters" not in message
    assert "overwrite" not in message
