"""A tool that fails reports isError, so hosts do not show a failed call as done."""

import asyncio


def _call(name, arguments):
    from kinocut.server import mcp

    return asyncio.run(mcp.call_tool(name, arguments))


def test_operational_failure_is_an_mcp_error(tmp_path):
    result = _call("video_info", {"input_path": str(tmp_path / "missing.mp4")})

    assert getattr(result, "isError", False) is True
    assert result.structuredContent["success"] is False
    assert result.structuredContent["error"]["code"]


def test_success_is_not_flagged(sample_video):
    result = _call("video_info", {"input_path": sample_video})

    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload["success"] is True
    assert getattr(result, "isError", False) is False
