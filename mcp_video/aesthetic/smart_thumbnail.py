"""Smart thumbnail selection using NIMA aesthetic scoring.

Instead of extracting a frame at a fixed timestamp (default 10% of duration),
this samples N candidate frames across the video, scores each with NIMA,
and selects the most aesthetically pleasing one.

Integration: called by engine_thumbnail.py when timestamp is None.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile

from ..defaults import DEFAULT_NIMA_CANDIDATES, DEFAULT_NIMA_MIN_DURATION
from ..errors import ProcessingError
from ..ffmpeg_helpers import _get_video_duration, _run_ffmpeg, _validate_input_path

logger = logging.getLogger(__name__)


def find_best_thumbnail_timestamp(
    input_path: str,
    num_candidates: int = DEFAULT_NIMA_CANDIDATES,
) -> float:
    """Find the most aesthetic timestamp for thumbnail extraction.

    Samples ``num_candidates`` frames across the video, scores each with NIMA,
    and returns the timestamp of the highest-scoring frame.

    Always returns a valid timestamp. Falls back to 10% of duration whenever
    NIMA is unavailable, the video is too short, or scoring fails for any
    reason.
    """
    input_path = _validate_input_path(input_path)
    try:
        ts = _select_best_with_nima(input_path, num_candidates)
        if ts is not None:
            return ts
        logger.debug("NIMA unavailable, using default timestamp")
    except Exception as exc:
        logger.warning("Smart thumbnail selection failed (%s); using default", exc)
    return _default_timestamp(input_path)


def _select_best_with_nima(
    input_path: str,
    num_candidates: int,
) -> float | None:
    """Run NIMA selection. Returns the best timestamp, or None if unavailable."""
    try:
        from mcp_video.aesthetic import NimaScorer, is_available
    except ImportError:
        logger.debug("NIMA module not importable")
        return None

    if not is_available():
        return None

    duration = _get_video_duration(input_path)
    if duration < DEFAULT_NIMA_MIN_DURATION:
        logger.debug("Video too short (%.2fs) for smart selection", duration)
        return None

    frame_paths = _extract_candidates(input_path, duration, num_candidates)
    if not frame_paths:
        return None

    scorer = NimaScorer.get()
    paths_only = [p for _, p in frame_paths]
    scores = scorer.score_frames(paths_only)

    best_idx = scores.index(max(scores))
    best_ts = frame_paths[best_idx][0]
    best_score = scores[best_idx]
    logger.info(
        "NIMA smart thumbnail: selected t=%.2fs (score %.2f) from %d candidates (avg %.2f, range %.2f-%.2f)",
        best_ts,
        best_score,
        len(scores),
        sum(scores) / len(scores),
        min(scores),
        max(scores),
    )
    return best_ts


def _extract_candidates(
    input_path: str,
    duration: float,
    num_candidates: int,
) -> list[tuple[float, str]]:
    """Extract candidate frames across the video. Returns (timestamp, path) pairs.

    Samples uniformly between 5% and 95% of duration, skipping the very
    start/end where frames are often title cards or fade-outs.
    """
    start = duration * 0.05
    end = duration * 0.95
    step = (end - start) / (num_candidates - 1) if num_candidates > 1 else 0
    timestamps = [start + i * step for i in range(num_candidates)]

    tmp_dir = tempfile.mkdtemp(prefix="nima_thumb_")
    frame_paths: list[tuple[float, str]] = []
    try:
        for i, ts in enumerate(timestamps):
            frame_path = os.path.join(tmp_dir, f"candidate_{i:03d}.jpg")
            try:
                # _run_ffmpeg sets timeout=DEFAULT_FFMPEG_TIMEOUT internally.
                _run_ffmpeg(
                    [
                        "-ss",
                        str(ts),
                        "-i",
                        input_path,
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        frame_path,
                    ]
                )
            except ProcessingError as exc:
                logger.debug("Failed to extract candidate at %.2fs: %s", ts, exc)
                continue
            if os.path.isfile(frame_path):
                frame_paths.append((ts, frame_path))
        return frame_paths
    finally:
        _cleanup_candidates(frame_paths, tmp_dir)


def _cleanup_candidates(frame_paths: list[tuple[float, str]], tmp_dir: str) -> None:
    """Remove temp candidate frames and their directory."""
    for _, path in frame_paths:
        with contextlib.suppress(OSError):
            os.remove(path)
    with contextlib.suppress(OSError):
        os.rmdir(tmp_dir)


def _default_timestamp(input_path: str) -> float:
    """Return the legacy default: 10% of duration (1.0s if unreadable)."""
    try:
        duration = _get_video_duration(input_path)
    except Exception:
        return 1.0
    if duration <= 0:
        return 1.0
    return duration * 0.1
