"""Trim reports render progress the way convert does.

The Hermes status bar shows a percentage only when a tool sends MCP progress
notifications; before this, trim (the most common render) sent none.
"""

import asyncio

import pytest

from mcp_video import server_tools_basic
from mcp_video.engine_edit import trim


@pytest.mark.parametrize(
    "window",
    [
        {"start": "0", "duration": "1"},
        {"start": "0.5", "end": "1.5"},
        {"start": "0.5"},
    ],
    ids=["duration", "end", "start-only"],
)
def test_trim_progress_reaches_100(sample_video, tmp_path, window):
    progress: list[float] = []

    result = trim(sample_video, output_path=str(tmp_path / "cut.mp4"), on_progress=progress.append, **window)

    assert result.success
    assert progress, "trim sent no progress"
    assert progress == sorted(progress)
    assert progress[-1] == pytest.approx(100.0)


def test_video_trim_tool_sends_mcp_progress(sample_video, tmp_path):
    reported: list[tuple[float, float | None]] = []

    class Ctx:
        async def report_progress(self, progress, total=None, message=None):
            reported.append((progress, total))

    result = asyncio.run(
        server_tools_basic.video_trim(
            sample_video, start="0", duration="1", output_path=str(tmp_path / "cut.mp4"), ctx=Ctx()
        )
    )

    assert result["success"] is True
    assert reported
    assert reported[-1] == (pytest.approx(100.0), 100.0)
