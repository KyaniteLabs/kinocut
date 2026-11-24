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
from collections.abc import Iterator

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
    with selected_frame(input_path, num_candidates) as (timestamp, _):
        return timestamp


@contextlib.contextmanager
def selected_frame(input_path: str, num_candidates: int = DEFAULT_NIMA_CANDIDATES, *, suffix: str = ".jpg"):
    """Keep the selected frame readable until the caller has published it."""
    input_path = _validate_input_path(input_path)
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        suffix = ".jpg"
    with contextlib.ExitStack() as stack:
        candidate = None
        try:
            candidate = _select_best_with_nima(input_path, num_candidates, stack, suffix)
        except Exception as exc:
            logger.warning("Smart thumbnail selection failed (%s); using default", exc)
        yield candidate or (_default_timestamp(input_path), None)


def _select_best_with_nima(
    input_path: str,
    num_candidates: int,
    stack: contextlib.ExitStack,
    suffix: str,
) -> tuple[float, str] | None:
    """Return the best candidate and transfer its temporary lifetime to the caller."""
    try:
        from kinocut.aesthetic import NimaScorer, is_available
    except ImportError:
        logger.debug("NIMA module not importable")
        return None

    if not is_available():
        return None

    duration = _get_video_duration(input_path)
    if duration < DEFAULT_NIMA_MIN_DURATION:
        logger.debug("Video too short (%.2fs) for smart selection", duration)
        return None

    frame_paths = stack.enter_context(_extract_candidates(input_path, duration, num_candidates, suffix))
    if not frame_paths:
        return None
    scores = NimaScorer.get().score_frames([path for _, path in frame_paths])
    best = scores.index(max(scores))
    logger.info(
        "NIMA selected t=%.2fs (score %.2f) from %d candidates", frame_paths[best][0], scores[best], len(scores)
    )
    return frame_paths[best]


@contextlib.contextmanager
def _extract_candidates(
    input_path: str,
    duration: float,
    num_candidates: int,
    suffix: str,
) -> Iterator[list[tuple[float, str]]]:
    """Extract candidate frames across the video. Returns (timestamp, path) pairs.

    Samples uniformly between 5% and 95% of duration, skipping the very
    start/end where frames are often title cards or fade-outs.
    """
    start = duration * 0.05
    end = duration * 0.95
    step = (end - start) / (num_candidates - 1) if num_candidates > 1 else 0
    timestamps = [start + i * step for i in range(num_candidates)]

    frame_paths: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory(prefix="nima_thumb_") as tmp_dir:
        for i, ts in enumerate(timestamps):
            frame_path = os.path.join(tmp_dir, f"candidate_{i:03d}{suffix}")
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
        yield frame_paths


def _default_timestamp(input_path: str) -> float:
    """Return the legacy default: 10% of duration (1.0s if unreadable)."""
    try:
        duration = _get_video_duration(input_path)
    except Exception:
        return 1.0
    if duration <= 0:
        return 1.0
    return duration * 0.1
