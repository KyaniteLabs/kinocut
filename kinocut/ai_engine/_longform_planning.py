"""Long-form chunk planning: scene-anchor discovery, deterministic chunk
emission over ``[0, duration]`` with overlap, and JSON-stable replay.
"""

from __future__ import annotations

import logging

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _get_video_duration
from ..limits import (
    LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNKS,
    MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
)
from ._longform_models import LongformChunk, LongformTranscribePlan
from ._longform_validation import (
    _validate_chunk_seconds,
    _validate_longform_path,
    _validate_overlap_seconds,
)
from .scene import ai_scene_detect

logger = logging.getLogger(__name__)


def _scene_anchors(
    video: str,
    duration: float,
    chunk_seconds: int,
    overlap_seconds: int,
) -> list[float]:
    """Return sorted scene anchor timestamps, or ``[]`` when unavailable.

    Best-effort: any failure degrades to ``[]`` so the planner falls
    back to a fixed walk.  Anchors are clamped to the body so they
    never create zero-width chunk boundaries.
    """
    try:
        raw = ai_scene_detect(video, threshold=0.3, use_ai=False)
    except Exception as exc:
        logger.debug("scene detection failed for long-form plan: %s", exc)
        return []
    if not raw:
        return []
    low = float(overlap_seconds)
    high = float(duration) - float(overlap_seconds)
    if high <= low:
        return []
    anchors: set[float] = set()
    for entry in raw:
        try:
            ts = float(entry.get("timestamp", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if low < ts < high:
            anchors.add(round(ts, 6))
    return sorted(anchors)


def _build_plan(
    video: str,
    duration: float,
    chunk_seconds: int,
    overlap_seconds: int,
    *,
    anchors: list[float] | None = None,
) -> LongformTranscribePlan:
    """Build an overlapping, gap-free plan over ``[0, duration]``.

    A nearby scene anchor may replace a nominal chunk end, but never beyond the
    configured size cap. The next chunk starts from that end minus overlap.
    """
    total = float(duration)
    cs = float(chunk_seconds)
    overlap = float(overlap_seconds)
    anchor_points = sorted({round(float(a), 6) for a in (anchors or [])})

    chunks: list[LongformChunk] = []
    cursor = 0.0
    idx = 0
    while cursor < total:
        nominal_end = min(total, cursor + cs)
        end = nominal_end
        anchor_kind = "fixed"
        if nominal_end < total:
            eligible = [
                anchor
                for anchor in anchor_points
                if cursor + MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS <= anchor <= nominal_end
                and nominal_end - anchor <= cs / 2.0
            ]
            if eligible:
                end = min(eligible, key=lambda anchor: (abs(nominal_end - anchor), anchor))
                anchor_kind = "scene"
        if end < total and end - overlap <= cursor:
            raise MCPVideoError(
                "overlap_seconds is too large for the selected scene boundary; "
                "reduce overlap_seconds or disable scene-aware planning",
                error_type="validation_error",
                code="invalid_overlap",
            )
        chunks.append(
            LongformChunk(
                index=idx,
                start=float(cursor),
                end=float(end),
                duration=end - cursor,
                anchor=anchor_kind,
            )
        )
        idx += 1
        if end >= total:
            break
        cursor = end - overlap

    if len(chunks) > MAX_LONGFORM_TRANSCRIBE_CHUNKS:
        raise MCPVideoError(
            f"Plan has {len(chunks)} chunks, exceeds cap of {MAX_LONGFORM_TRANSCRIBE_CHUNKS}",
            error_type="validation_error",
            code="too_many_chunks",
        )

    return LongformTranscribePlan(
        video_path=video,
        duration=float(duration),
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
        chunks=chunks,
    )


def plan_longform_transcription(
    video: str,
    *,
    chunk_seconds: int = MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    overlap_seconds: int = LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    scene_aware: bool = True,
) -> LongformTranscribePlan:
    """Plan a long-form transcription without invoking Whisper.

    Validates path + parameters before any probe / scene work runs.
    Scene detection is best-effort: failure or empty results yield a
    fixed walk with ``anchor="fixed"`` on every chunk.
    """
    chunk_seconds = _validate_chunk_seconds(chunk_seconds)
    overlap_seconds = _validate_overlap_seconds(overlap_seconds, chunk_seconds)
    video = _validate_longform_path(video)
    duration = _get_video_duration(video)
    anchors: list[float] = []
    if scene_aware and duration > chunk_seconds:
        anchors = _scene_anchors(video, duration, chunk_seconds, overlap_seconds)
    return _build_plan(
        video,
        duration,
        chunk_seconds,
        overlap_seconds,
        anchors=anchors,
    )


__all__ = [
    "LONGFORM_TRANSCRIBE_OVERLAP_SECONDS",
    "MAX_LONGFORM_TRANSCRIBE_CHUNKS",
    "MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS",
    "_build_plan",
    "_scene_anchors",
    "plan_longform_transcription",
]
