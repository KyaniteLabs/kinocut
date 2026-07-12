"""Tests for NIMA smart thumbnail selection.

The selection logic is verified by mocking the NIMA scorer and the FFmpeg
layer, so these tests need neither PyTorch/model weights nor real media.
A couple of integration-style tests exercise the public ``thumbnail()``
engine entry point against a real fixture when ffmpeg is available.
"""

from __future__ import annotations

import os
import shutil
from unittest import mock

import pytest

from mcp_video.aesthetic import smart_thumbnail
from mcp_video.aesthetic.smart_thumbnail import (
    _default_timestamp,
    find_best_thumbnail_timestamp,
)
from mcp_video.errors import InputFileError, MCPVideoError

DURATION = 100.0


def _patch_duration(value: float = DURATION):
    return mock.patch.object(smart_thumbnail, "_get_video_duration", return_value=value)


@pytest.fixture
def fake_video(tmp_path) -> str:
    """A small placeholder file that passes ``_validate_input_path``."""
    p = tmp_path / "input.mp4"
    p.write_bytes(b"\x00\x00\x00\x20 ftypisom")
    return str(p)


def _make_frame_writer():
    """Return a side-effect that writes dummy JPEG bytes to each output path."""

    def _write(args, *a, **kw):
        with open(args[-1], "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0")  # JPEG SOI/APP0 magic
        return mock.MagicMock()

    return _write


class TestFallbackToDefault:
    """NIMA-unavailable and failure paths must always return 10% of duration."""

    def test_falls_back_to_10pct_when_nima_unavailable(self, fake_video):
        with _patch_duration(), mock.patch("mcp_video.aesthetic.is_available", return_value=False):
            ts = find_best_thumbnail_timestamp(fake_video)
        assert ts == pytest.approx(DURATION * 0.1)

    def test_falls_back_for_short_video(self, fake_video):
        """Videos below DEFAULT_NIMA_MIN_DURATION skip smart selection."""
        with _patch_duration(2.0), mock.patch("mcp_video.aesthetic.is_available", return_value=True):
            ts = find_best_thumbnail_timestamp(fake_video)
        assert ts == pytest.approx(2.0 * 0.1)

    def test_falls_back_when_scoring_raises(self, fake_video):
        """A NIMA scoring error must not escape — returns 10% default."""
        scorer = mock.MagicMock()
        scorer.score_frames.side_effect = RuntimeError("model blew up")
        with (
            _patch_duration(),
            mock.patch("mcp_video.aesthetic.is_available", return_value=True),
            mock.patch("mcp_video.aesthetic.NimaScorer") as nima_cls,
            mock.patch.object(smart_thumbnail, "_run_ffmpeg", side_effect=_make_frame_writer()),
        ):
            nima_cls.get.return_value = scorer
            ts = find_best_thumbnail_timestamp(fake_video)
        assert ts == pytest.approx(DURATION * 0.1)

    def test_falls_back_when_all_extractions_fail(self, fake_video):
        from mcp_video.errors import ProcessingError

        with (
            _patch_duration(),
            mock.patch("mcp_video.aesthetic.is_available", return_value=True),
            mock.patch("mcp_video.aesthetic.NimaScorer"),
            mock.patch.object(smart_thumbnail, "_run_ffmpeg", side_effect=ProcessingError("ff", 1, "x")),
        ):
            ts = find_best_thumbnail_timestamp(fake_video)
        assert ts == pytest.approx(DURATION * 0.1)


class TestDefaultTimestampHelper:
    def test_returns_10pct_of_duration(self, fake_video):
        with _patch_duration(50.0):
            assert _default_timestamp(fake_video) == pytest.approx(5.0)

    def test_safe_when_duration_unreadable(self, fake_video):
        with mock.patch.object(smart_thumbnail, "_get_video_duration", side_effect=MCPVideoError("nope")):
            assert _default_timestamp(fake_video) == 1.0

    def test_safe_when_duration_non_positive(self, fake_video):
        with _patch_duration(0.0):
            assert _default_timestamp(fake_video) == 1.0


class TestFrameSelection:
    """When NIMA is available, the highest-scoring frame is selected."""

    def test_selects_highest_scoring_frame(self, fake_video):
        from mcp_video.defaults import DEFAULT_NIMA_CANDIDATES

        n = DEFAULT_NIMA_CANDIDATES
        start, end = DURATION * 0.05, DURATION * 0.95
        step = (end - start) / (n - 1)
        expected = [start + i * step for i in range(n)]

        scores = [3.0] * n
        scores[3] = 9.9  # candidate index 3 is the most beautiful

        scorer = mock.MagicMock()
        scorer.score_frames.return_value = scores

        with (
            _patch_duration(),
            mock.patch("mcp_video.aesthetic.is_available", return_value=True),
            mock.patch("mcp_video.aesthetic.NimaScorer") as nima_cls,
            mock.patch.object(smart_thumbnail, "_run_ffmpeg", side_effect=_make_frame_writer()),
        ):
            nima_cls.get.return_value = scorer
            ts = find_best_thumbnail_timestamp(fake_video)

        # Every candidate was scored.
        scored_paths = scorer.score_frames.call_args[0][0]
        assert len(scored_paths) == n
        # The best frame (index 3) was selected.
        assert ts == pytest.approx(expected[3])

    def test_skips_frames_that_fail_extraction(self, fake_video):
        """A failing candidate is skipped, not fatal; survivors are still scored."""
        from mcp_video.errors import ProcessingError

        num = 4
        # timestamps for duration=100, num=4: [5, 35, 65, 95]
        # second extraction fails -> survivors are timestamps [5, 65, 95]
        # scores map onto survivors; best is index 1 -> timestamp 65.0
        scorer = mock.MagicMock()
        scorer.score_frames.return_value = [5.0, 9.0, 2.0]

        attempts = {"n": 0}

        def flaky_run(args, *a, **kw):
            attempts["n"] += 1
            if attempts["n"] == 2:
                raise ProcessingError("ff", 1, "seek past eof")
            with open(args[-1], "wb") as fh:
                fh.write(b"\xff\xd8\xff")
            return mock.MagicMock()

        with (
            _patch_duration(),
            mock.patch("mcp_video.aesthetic.is_available", return_value=True),
            mock.patch("mcp_video.aesthetic.NimaScorer") as nima_cls,
            mock.patch.object(smart_thumbnail, "_run_ffmpeg", side_effect=flaky_run),
        ):
            nima_cls.get.return_value = scorer
            ts = find_best_thumbnail_timestamp(fake_video, num_candidates=num)

        scored_paths = scorer.score_frames.call_args[0][0]
        assert len(scored_paths) == 3  # one extraction was skipped
        assert ts == pytest.approx(65.0)

    def test_cleans_up_temp_frames(self, fake_video):
        """Candidate temp files are removed after scoring."""
        created: list[str] = []

        def tracking_writer(args, *a, **kw):
            path = args[-1]
            with open(path, "wb") as fh:
                fh.write(b"\xff\xd8\xff")
            created.append(path)
            return mock.MagicMock()

        scorer = mock.MagicMock()
        scorer.score_frames.return_value = [1.0, 9.0, 2.0, 3.0]

        with (
            _patch_duration(),
            mock.patch("mcp_video.aesthetic.is_available", return_value=True),
            mock.patch("mcp_video.aesthetic.NimaScorer") as nima_cls,
            mock.patch.object(smart_thumbnail, "_run_ffmpeg", side_effect=tracking_writer),
        ):
            nima_cls.get.return_value = scorer
            find_best_thumbnail_timestamp(fake_video, num_candidates=4)

        assert created, "expected candidate frames to be extracted"
        assert all(not os.path.exists(p) for p in created), "temp frames left behind"


class TestInputValidation:
    def test_validates_input_path(self, fake_video):
        """The input path is validated before any NIMA/ffprobe work."""
        with (
            mock.patch.object(smart_thumbnail, "_validate_input_path", wraps=lambda p: p) as validated,
            _patch_duration(),
            mock.patch("mcp_video.aesthetic.is_available", return_value=False),
        ):
            find_best_thumbnail_timestamp(fake_video)
        validated.assert_called_once_with(fake_video)

    def test_rejects_nonexistent_path(self):
        with pytest.raises(InputFileError):
            find_best_thumbnail_timestamp("/nonexistent/video.mp4")

    def test_rejects_path_with_null_byte(self):
        with pytest.raises(InputFileError):
            find_best_thumbnail_timestamp("/bad/\x00/video.mp4")


class TestEngineIntegration:
    """End-to-end through engine_thumbnail.thumbnail() — needs ffmpeg."""

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
    def test_smart_falls_back_to_10pct_without_torch(self, sample_video):
        """Without torch/weights, thumbnail(video) still works and lands near 10%."""
        from mcp_video.engine_thumbnail import thumbnail
        from mcp_video.engine_probe import get_duration

        result = thumbnail(sample_video)
        assert os.path.isfile(result.frame_path)
        dur = get_duration(sample_video)
        # NIMA unavailable in CI -> falls back to ~10% of duration.
        assert abs(result.timestamp - dur * 0.1) < 0.05

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
    def test_explicit_timestamp_bypasses_smart(self, sample_video):
        """An explicit timestamp must skip the smart-selection path entirely."""
        from mcp_video.engine_thumbnail import thumbnail

        with mock.patch("mcp_video.aesthetic.smart_thumbnail.find_best_thumbnail_timestamp") as smart:
            result = thumbnail(sample_video, timestamp=1.0)
        smart.assert_not_called()
        assert result.timestamp == 1.0
