"""Thread-safe MCP progress bridge contract."""

import asyncio

import pytest

pytest.importorskip("mcp")

from kinocut.server_app import _mcp_progress_reporter


def test_mcp_progress_reporter_forwards_thread_updates_to_context():
    received: list[tuple[float, float]] = []

    class Context:
        async def report_progress(self, progress: float, total: float) -> None:
            received.append((progress, total))

    async def run() -> None:
        reporter = _mcp_progress_reporter(Context())
        assert reporter is not None
        await asyncio.to_thread(reporter, 42.5)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert received == [(42.5, 100.0)]
