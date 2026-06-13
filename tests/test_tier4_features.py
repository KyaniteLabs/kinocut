"""Tests for Tier 4 features: audio ducking, LUT color grading, MCP progress."""

from __future__ import annotations

import asyncio
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_video.engine_probe import probe
from mcp_video.errors import MCPVideoError


# --- FEAT-1: audio ducking ------------------------------------------------------


class TestDuckAudio:
    def test_mixes_music_under_voice(self, sample_video, sample_audio, tmp_path):
        from mcp_video.engine_audio_ops import duck_audio

        out = str(tmp_path / "ducked.mp4")
        result = duck_audio(sample_video, sample_audio, output_path=out)
        assert result.success
        info = probe(out)
        assert info.audio_codec is not None
        # duration=first keeps the video's length even though the music is longer
        assert abs(info.duration - 3.0) < 0.5

    def test_requires_video_audio_track(self, sample_video_no_audio, sample_audio, tmp_path):
        from mcp_video.engine_audio_ops import duck_audio

        with pytest.raises(MCPVideoError, match="audio track"):
            duck_audio(sample_video_no_audio, sample_audio, output_path=str(tmp_path / "x.mp4"))

    def test_validates_ratio_lower_bound(self, sample_video, sample_audio, tmp_path):
        from mcp_video.engine_audio_ops import duck_audio

        with pytest.raises(MCPVideoError, match="ratio"):
            duck_audio(sample_video, sample_audio, ratio=0.5, output_path=str(tmp_path / "x.mp4"))

    def test_tool_rejects_bad_threshold(self, sample_video, sample_audio, tmp_path):
        from mcp_video.server_tools_audio import video_duck_audio

        result = video_duck_audio(sample_video, sample_audio, threshold=5.0, output_path=str(tmp_path / "x.mp4"))
        assert result["success"] is False

    def test_tool_success_envelope(self, sample_video, sample_audio, tmp_path):
        from mcp_video.server_tools_audio import video_duck_audio

        out = str(tmp_path / "ducked_tool.mp4")
        result = video_duck_audio(sample_video, sample_audio, output_path=out)
        assert result["success"] is True
        assert result["output_path"] == out


# --- FEAT-2: MCP progress notifications for long renders -------------------------


def test_video_convert_streams_mcp_progress(sample_video, tmp_path):
    """The engine's on_progress callback was never wired to the MCP layer, so
    long renders looked hung to clients. video_convert now streams progress
    notifications, ending at 100."""
    received: list[float] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append(progress)

    out = str(tmp_path / "progress.webm")

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_video"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(
                "video_convert",
                {"input_path": sample_video, "format": "webm", "output_path": out},
                progress_callback=on_progress,
            )

    result = asyncio.run(run())

    assert result.isError is False
    assert received, "expected at least one MCP progress notification"
    assert received[-1] == 100.0


# --- FEAT-3: LUT file support in color grading ----------------------------------


class TestColorGradeLut:
    @pytest.fixture()
    def identity_cube(self, tmp_path) -> str:
        """Minimal valid identity .cube LUT."""
        lut = tmp_path / "identity.cube"
        lines = ["LUT_3D_SIZE 2"]
        for b in (0.0, 1.0):
            for g in (0.0, 1.0):
                for r in (0.0, 1.0):
                    lines.append(f"{r:.1f} {g:.1f} {b:.1f}")
        lut.write_text("\n".join(lines) + "\n")
        return str(lut)

    def test_applies_cube_lut(self, sample_video, identity_cube, tmp_path):
        from mcp_video.ai_engine.color import ai_color_grade

        out = str(tmp_path / "lut_graded.mp4")
        assert ai_color_grade(sample_video, out, lut_path=identity_cube) == out
        assert probe(out).duration > 0

    def test_rejects_unknown_lut_extension(self, sample_video, tmp_path):
        from mcp_video.ai_engine.color import ai_color_grade

        bad = tmp_path / "lut.txt"
        bad.write_text("not a lut")
        with pytest.raises(MCPVideoError, match="LUT"):
            ai_color_grade(sample_video, str(tmp_path / "x.mp4"), lut_path=str(bad))

    def test_rejects_missing_lut_file(self, sample_video, tmp_path):
        from mcp_video.ai_engine.color import ai_color_grade

        with pytest.raises(MCPVideoError):
            ai_color_grade(sample_video, str(tmp_path / "x.mp4"), lut_path=str(tmp_path / "missing.cube"))
