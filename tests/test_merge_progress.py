"""Merges that re-render report one moving percentage for the whole job.

A transition merge or a normalizing merge runs one or more FFmpeg renders;
the Hermes status bar shows a percentage only when the tool sends MCP
progress notifications.
"""

import asyncio
import os
import subprocess

import pytest

from mcp_video import server_tools_basic
from mcp_video.engine_merge import merge
from mcp_video.engine_runtime_utils import _ffmpeg


def _clip(path, size):
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration=2:size={size}:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


def _assert_whole_job(progress):
    assert progress, "merge sent no progress"
    assert progress == sorted(progress), "the percentage went backwards between renders"
    assert progress[-1] == pytest.approx(100.0)
    assert all(0.0 <= p <= 100.0 for p in progress)


def test_transition_merge_reports_progress(sample_video, tmp_path):
    progress: list[float] = []

    result = merge(
        [sample_video, sample_video],
        output_path=str(tmp_path / "merged.mp4"),
        transition="fade",
        transition_duration=0.5,
        on_progress=progress.append,
    )

    assert result.success
    _assert_whole_job(progress)


def test_normalizing_merge_spans_every_render(tmp_path):
    a = _clip(tmp_path / "a.mp4", "320x240")
    b = _clip(tmp_path / "b.mp4", "640x360")
    progress: list[float] = []

    result = merge(
        [a, b],
        output_path=str(tmp_path / "merged.mp4"),
        transition="fade",
        transition_duration=0.5,
        on_progress=progress.append,
    )

    assert result.success
    _assert_whole_job(progress)
    # Normalizing two clips comes before the transition render, so the
    # first clip's render ends well short of the finish line.
    assert min(progress) < 50.0


def test_stream_copy_merge_sends_nothing(sample_video, tmp_path):
    progress: list[float] = []

    result = merge([sample_video, sample_video], output_path=str(tmp_path / "m.mp4"), on_progress=progress.append)

    assert result.success
    assert progress == []


def test_video_merge_tool_sends_mcp_progress(sample_video, tmp_path):
    reported: list[tuple[float, float | None]] = []

    class Ctx:
        async def report_progress(self, progress, total=None, message=None):
            reported.append((progress, total))

    result = asyncio.run(
        server_tools_basic.video_merge(
            [sample_video, sample_video],
            output_path=str(tmp_path / "merged.mp4"),
            transition="fade",
            transition_duration=0.5,
            ctx=Ctx(),
        )
    )

    assert result["success"] is True
    assert os.path.isfile(result["output_path"])
    assert reported
    assert reported[-1] == (pytest.approx(100.0), 100.0)
