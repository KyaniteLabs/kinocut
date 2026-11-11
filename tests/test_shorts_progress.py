"""A shorts run reports one moving percentage across all of its renders.

Shorts trims each segment, merges the trims, burns captions and renders the
vertical cut. The Hermes status bar shows a percentage only when the tool
sends MCP progress notifications, so the flow maps every render's own
0-100 onto one job-wide number.
"""

import asyncio

import pytest

from mcp_video import server_tools_shorts
from mcp_video.product import shorts_flow
from mcp_video.product.shorts_flow import _StagedProgress


def _assert_whole_job(progress):
    assert progress, "shorts sent no progress"
    assert progress == sorted(progress), "the percentage went backwards between renders"
    assert progress[-1] == pytest.approx(100.0)
    assert all(0.0 <= p <= 100.0 for p in progress)


def test_staged_progress_maps_each_stage_onto_its_slice():
    seen: list[float] = []
    progress = _StagedProgress(seen.append, [1.0, 0.0, 3.0])
    progress.stage(1.0)(50.0)
    progress.finish(1.0)
    assert progress.stage(0.0) is None, "a skipped stage has no slice"
    progress.finish(0.0)
    progress.stage(3.0)(200.0)
    progress.finish(3.0)
    assert seen == [12.5, 25.0, 25.0, 100.0, 100.0]


def test_staged_progress_is_silent_without_a_listener():
    progress = _StagedProgress(None, [1.0])
    assert progress.stage(1.0) is None
    progress.finish(1.0)


def test_two_segment_short_reports_one_rising_percentage(sample_video, tmp_path):
    progress: list[float] = []

    result = shorts_flow.video_shorts(
        sample_video,
        [{"start": 0, "end": 1}, {"start": 1, "end": 2}],
        output_path=str(tmp_path / "short.mp4"),
        on_progress=progress.append,
    )

    assert result["success"]
    _assert_whole_job(progress)
    assert min(progress) < 25.0, "the first trim reports before the later renders"


def test_video_shorts_tool_sends_mcp_progress(sample_video, tmp_path):
    reported: list[float] = []

    class Ctx:
        async def report_progress(self, progress, total=None, message=None):
            reported.append(progress)

    result = asyncio.run(
        server_tools_shorts.video_shorts(
            sample_video,
            [{"start": 0, "end": 1}],
            output_path=str(tmp_path / "short.mp4"),
            ctx=Ctx(),
        )
    )

    assert result["success"]
    assert reported and reported[-1] == pytest.approx(100.0)
