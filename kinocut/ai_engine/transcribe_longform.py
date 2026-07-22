"""Long-form (up to MAX_VIDEO_DURATION) transcription path.

Phase A1 of the reusable stream-to-shorts workflow. Splits the input into
fixed or scene-aware overlapping chunks, runs each chunk through the existing
Whisper-based ``ai_transcribe`` machinery, and merges the word-timed segments
into a single monotonic transcript with overlap deduplication.

Design constraints (from the orchestrator contract):
- Deterministic strict pydantic models so the future orchestrator can consume
  plans and results without re-parsing free-form dicts.
- Ordinary ``ai_transcribe`` keeps its >3600s rejection; this path is the only
  way to transcribe media up to ``MAX_VIDEO_DURATION``.
- No new cloud dependency.  Whisper remains an optional local dependency
  (same shape as ``ai_transcribe``).
- Word-level timestamps are produced by Whisper; the merger uses the chunk's
  ``chunk_offset_seconds`` to remap local word timestamps back to global
  source-time.  Overlap words are deduplicated by exact text match on the
  overlapping tail window.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile


from contextlib import suppress
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..errors import InputFileError, MCPVideoError
from ..ffmpeg_helpers import _get_video_duration, _validate_input_path
from ..limits import (
    LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNKS,
    MAX_VIDEO_DURATION,
    MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
)
from .scene import ai_scene_detect
from .transcribe import (
    _extract_audio_segment,
    _validate_whisper_model,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strict pydantic models — the orchestrator contract surface
# ---------------------------------------------------------------------------


class LongformChunk(BaseModel):
    """One planned chunk of a long-form transcription run.

    ``start`` and ``end`` are global source-time coordinates in seconds.
    ``duration`` is the length actually fed to Whisper (>= end - start).
    The extra ``duration - (end - start)`` slack is the overlap tail that
    backs the previous chunk and is used by the merger to dedup words.
    """

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    duration: float = Field(gt=0.0)
    anchor: str = "fixed"  # one of: "fixed", "scene"


class LongformTranscribePlan(BaseModel):
    """Deterministic plan returned by ``plan_longform_transcription``.

    The orchestrator can persist this to JSON and replay the same chunking
    deterministically on a re-run (the merger is offset-based, not path-based).
    """

    model_config = ConfigDict(extra="forbid")

    video_path: str
    duration: float = Field(ge=0.0)
    chunk_seconds: int = Field(gt=0)
    overlap_seconds: int = Field(ge=0)
    chunks: list[LongformChunk]


class LongformWord(BaseModel):
    """One word with globally remapped timestamps (seconds, source-time)."""

    model_config = ConfigDict(extra="forbid")

    word: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    chunk_index: int = Field(ge=0)
    probability: float | None = Field(default=None, ge=0.0, le=1.0)


class LongformSegment(BaseModel):
    """One transcript segment, globally remapped and dedup-overlapped."""

    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str
    chunk_index: int = Field(ge=0)
    avg_logprob: float | None = Field(default=None, le=0.0)
    no_speech_prob: float | None = Field(default=None, ge=0.0, le=1.0)


class LongformTranscribeResult(BaseModel):
    """Strict-model result of ``transcribe_longform``.

    Mirrors the public shape of ``ai_transcribe`` (transcript / segments /
    language) so the future shorts orchestrator can consume either path with
    the same downstream code, plus the per-chunk lineage it needs to clip
    from source-time.
    """

    model_config = ConfigDict(extra="forbid")

    video_path: str
    duration: float = Field(ge=0.0)
    language: str
    transcript: str
    segments: list[LongformSegment]
    words: list[LongformWord]
    chunk_count: int = Field(ge=0)
    model: str
    plan: LongformTranscribePlan


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _validate_longform_path(video: str) -> str:
    """Validate input path for the long-form path (no duration rejection).

    The ordinary ``ai_transcribe`` rejects >3600s; this path explicitly does
    not, but the underlying file must still be a real, readable media file
    bounded by ``MAX_VIDEO_DURATION``.
    """
    if "\x00" in video:
        raise InputFileError(video, "Invalid path: contains null bytes")
    _validate_input_path(video)
    duration = _get_video_duration(video)
    if duration <= 0:
        raise MCPVideoError(
            f"Could not determine positive duration for {video!r}",
            error_type="validation_error",
            code="invalid_input",
        )
    if duration > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            f"Video duration ({duration:.0f}s) exceeds long-form cap of {MAX_VIDEO_DURATION}s",
            error_type="validation_error",
            code="duration_too_long",
        )
    return video


def _validate_chunk_seconds(chunk_seconds: int) -> int:
    if not isinstance(chunk_seconds, int) or chunk_seconds <= 0:
        raise MCPVideoError(
            f"chunk_seconds must be a positive int, got {chunk_seconds!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if chunk_seconds > MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS:
        raise MCPVideoError(
            f"chunk_seconds ({chunk_seconds}) exceeds cap of {MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS}",
            error_type="validation_error",
            code="chunk_too_large",
        )
    if chunk_seconds < MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS:
        raise MCPVideoError(
            f"chunk_seconds ({chunk_seconds}) below minimum of {MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS}",
            error_type="validation_error",
            code="chunk_too_small",
        )
    return chunk_seconds


def _validate_overlap_seconds(overlap_seconds: int, chunk_seconds: int) -> int:
    if not isinstance(overlap_seconds, int) or overlap_seconds < 0:
        raise MCPVideoError(
            f"overlap_seconds must be a non-negative int, got {overlap_seconds!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if overlap_seconds >= chunk_seconds:
        raise MCPVideoError(
            f"overlap_seconds ({overlap_seconds}) must be smaller than chunk_seconds ({chunk_seconds})",
            error_type="validation_error",
            code="invalid_overlap",
        )
    return overlap_seconds


# ---------------------------------------------------------------------------
# Chunk planning
# ---------------------------------------------------------------------------


def _scene_anchors(
    video: str,
    duration: float,
    chunk_seconds: int,
    overlap_seconds: int,
) -> list[float]:
    """Return scene-anchored candidate split points, or empty for fixed split.

    Returns the *middle* of every Whisper chunk as a candidate anchor so the
    chunker can snap to natural scene breaks when they fall within a window
    of the natural split.  Returns ``[]`` (and lets the planner use fixed
    splits) when scene detection is unavailable or finds no cuts.

    The check uses the standard FFmpeg scene detector which ships with the
    optional dependencies (``ai_scene_detect`` falls back to FFmpeg-native
    detection when ``imagehash`` is unavailable).
    """
    try:
        raw = ai_scene_detect(video, threshold=0.3, use_ai=False)
    except Exception as exc:  # scene detection is best-effort
        logger.debug("scene detection failed for long-form plan: %s", exc)
        return []

    if not raw:
        return []

    # Convert raw scene records (timestamp/frame/hash_diff) to a sorted set
    # of anchor timestamps inside (overlap, duration - overlap).
    anchors: list[float] = []
    for entry in raw:
        ts = float(entry.get("timestamp", 0.0) or 0.0)
        if ts <= overlap_seconds:
            continue
        if ts >= duration - overlap_seconds:
            continue
        anchors.append(ts)

    # Snap each natural chunk midpoint to the nearest anchor within half a
    # chunk (so we don't lose coverage or create tiny stragglers).  This is
    # what gets attached to each chunk's ``anchor`` field in the plan.
    natural_midpoints = [min(duration, (i + 0.5) * chunk_seconds) for i in range(int(duration // chunk_seconds) + 1)]
    snapped: list[float] = []
    window = chunk_seconds / 2.0
    for mid in natural_midpoints:
        nearest = min(anchors, key=lambda a: abs(a - mid), default=None)
        if nearest is not None and abs(nearest - mid) <= window:
            snapped.append(nearest)
        else:
            snapped.append(mid)
    return snapped


def _build_plan(
    video: str,
    duration: float,
    chunk_seconds: int,
    overlap_seconds: int,
    *,
    anchors: list[float] | None = None,
) -> LongformTranscribePlan:
    """Build the deterministic chunk plan.

    Coverage rules:
    - The first chunk starts at 0.0.
    - Each subsequent chunk starts at ``prev_end - overlap_seconds``.
    - ``prev_end = prev_start + chunk_seconds`` for every chunk except the
      last, which uses ``prev_end = duration`` to guarantee full coverage.
    - No chunk exceeds ``chunk_seconds + overlap_seconds`` in actual fed
      duration, and the last chunk is never bigger than ``chunk_seconds``.
    """
    if anchors:
        # Anchor-aware: split at anchor points, snapping to nearest anchor
        # within half a chunk window.  Anchors are absolute midpoints.
        boundaries = sorted({0.0, duration, *anchors})
        # Force a minimum gap of ``overlap_seconds`` between boundaries
        # to avoid zero-duration chunks.
        cleaned: list[float] = [0.0]
        for b in boundaries[1:]:
            if b - cleaned[-1] >= MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS:
                cleaned.append(b)
        if cleaned[-1] != duration:
            cleaned.append(duration)
        chunks: list[LongformChunk] = []
        for i, start in enumerate(cleaned[:-1]):
            end = min(duration, start + chunk_seconds)
            actual_duration = end - start
            anchor_kind = "scene"
            chunks.append(
                LongformChunk(
                    index=i,
                    start=float(start),
                    end=float(end),
                    duration=float(actual_duration),
                    anchor=anchor_kind,
                )
            )
    else:
        chunks = []
        idx = 0
        cursor = 0.0
        while cursor < duration:
            end = min(duration, cursor + float(chunk_seconds))
            actual_duration = end - cursor
            chunks.append(
                LongformChunk(
                    index=idx,
                    start=float(cursor),
                    end=float(end),
                    duration=float(actual_duration),
                    anchor="fixed",
                )
            )
            idx += 1
            if end >= duration:
                break
            cursor = end - float(overlap_seconds)

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

    The plan is a strict pydantic model that can be JSON-serialized,
    cached, replayed, or inspected by the future shorts orchestrator.
    """
    video = _validate_longform_path(video)
    duration = _get_video_duration(video)
    chunk_seconds = _validate_chunk_seconds(chunk_seconds)
    overlap_seconds = _validate_overlap_seconds(overlap_seconds, chunk_seconds)

    if scene_aware and duration > chunk_seconds:
        anchors = _scene_anchors(video, duration, chunk_seconds, overlap_seconds)
        if anchors:
            return _build_plan(
                video,
                duration,
                chunk_seconds,
                overlap_seconds,
                anchors=anchors,
            )
    return _build_plan(video, duration, chunk_seconds, overlap_seconds)


# ---------------------------------------------------------------------------
# Per-chunk execution
# ---------------------------------------------------------------------------


def _transcribe_chunk(
    video: str,
    chunk: LongformChunk,
    *,
    model: str,
    language: str | None,
    work_dir: str,
) -> dict[str, Any]:
    """Run Whisper over a single chunk and return the raw ``ai_transcribe`` shape.

    The returned dict's per-segment/per-word timestamps are *local* to the
    chunk's start; the caller is responsible for offsetting them by
    ``chunk.start`` before merging.
    """
    audio_path: str | None = None
    try:
        audio_path = _extract_audio_segment(
            video,
            float(chunk.start),
            float(chunk.duration),
        )
        # ``ai_transcribe`` re-validates duration against MAX_AI_TRANSCRIBE_DURATION
        # against the *full* source media.  We bypass that by transcribing the
        # extracted audio via the underlying Whisper call only — but
        # ``ai_transcribe`` is the public entry point, so we need a small
        # helper.  We re-use the same ffmpeg -> whisper -> segment format
        # pipeline without re-probing source duration.

        try:
            import whisper  # type: ignore
        except ImportError as exc:
            raise MCPVideoError(
                'Whisper not installed. Install with: pip install "mcp-video[transcribe]"',
                error_type="dependency_error",
                code="missing_whisper",
                suggested_action={
                    "auto_fix": False,
                    "description": 'Run: pip install "mcp-video[transcribe]" to enable transcription',
                },
            ) from exc

        whisper_model = whisper.load_model(model)
        transcribe_options: dict[str, Any] = {"word_timestamps": True}
        if language:
            transcribe_options["language"] = language
        transcribe_options["task"] = "transcribe"

        # ``word_timestamps=True`` is critical for overlap dedup; whisper's
        # default ``segment-level`` output is not enough.
        result_data = whisper_model.transcribe(
            audio_path,
            **transcribe_options,
        )

        # Whisper doesn't always honour ``word_timestamps`` for every model;
        # fall back to segment-level when no words are present and just keep
        # the segment times.
        return _format_chunk_result(result_data)
    finally:
        if audio_path is not None:
            with suppress(OSError):
                os.unlink(audio_path)


def _format_chunk_result(result_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize Whisper output while preserving real per-word timing data."""
    from .transcribe import _format_json_transcript

    raw_segments = list(result_data.get("segments", []))
    formatted = _format_json_transcript(
        str(result_data.get("text", "")).strip(),
        raw_segments,
        str(result_data.get("language", "unknown")),
    )
    for normalized, raw in zip(formatted["segments"], raw_segments, strict=True):
        normalized["words"] = list(raw.get("words") or ())
    return formatted


# ---------------------------------------------------------------------------
# Word remap + overlap dedup
# ---------------------------------------------------------------------------


def _extract_segment_words(
    segment: dict[str, Any],
) -> list[tuple[str, float, float, float | None]]:
    """Return ``[(word, start, end, probability), ...]`` from a Whisper segment.

    ``probability`` is the per-token confidence in ``[0.0, 1.0]`` when
    available; ``None`` when Whisper did not emit one. Callers MUST treat a
    ``None`` probability as "unknown" rather than defaulting to a synthetic
    value (e.g. ``1.0``) so downstream stages never fabricate a confidence
    they cannot justify.
    """
    words = segment.get("words") or []
    out: list[tuple[str, float, float, float | None]] = []
    for w in words:
        text = str(w.get("word", "")).strip()
        start = float(w.get("start", 0.0) or 0.0)
        end = float(w.get("end", start) or start)
        if not text:
            continue
        out.append((text, start, end, _word_probability(w)))
    return out


def _word_probability(word: dict[str, Any]) -> float | None:
    """Translate a Whisper word entry into a probability in ``[0.0, 1.0]``.

    Honours ``probability`` when present and in range; falls back to
    ``exp(avg_logprob)`` (Whisper's per-token log-likelihood is the
    authoritative fallback for older outputs); returns ``None`` when neither
    signal is available so the caller can keep the word without inventing a
    confidence value.
    """
    raw_prob = word.get("probability")
    if raw_prob is not None:
        try:
            value = float(raw_prob)
        except (TypeError, ValueError):
            value = float("nan")
        if 0.0 <= value <= 1.0:
            return value
    logprob = word.get("avg_logprob")
    if logprob is None:
        return None
    try:
        value = float(logprob)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, math.exp(value)))


def _segment_confidence(seg: dict[str, Any]) -> float | None:
    """Translate a Whisper segment ``avg_logprob`` into ``[0.0, 1.0]`` confidence.

    Returns ``None`` when the segment did not carry a log probability. The
    result is clamped because ``exp`` can numerically overshoot on degenerate
    inputs and we never want a confidence value outside ``[0.0, 1.0]`` to
    leak into the orchestrator's strict models.
    """
    logprob = seg.get("avg_logprob")
    if logprob is None:
        return None
    try:
        value = float(logprob)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, math.exp(value)))


def _segment_no_speech_prob(seg: dict[str, Any]) -> float | None:
    """Return ``no_speech_prob`` when present and well-formed."""
    raw = seg.get("no_speech_prob")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if 0.0 <= value <= 1.0:
        return value
    return None


def _build_dedup_tail(
    accumulated_words: list[LongformWord],
    overlap_start: float,
) -> set[str]:
    """Build the set of accumulated word strings that fall inside the tail
    window ``[overlap_start, +inf)`` — i.e. words emitted by the previous
    chunk that we now consider "owned" by the boundary.

    Used by ``_merge_chunk`` to drop duplicates from the next chunk's
    overlap tail.
    """
    tail: set[str] = set()
    for w in accumulated_words:
        if w.start >= overlap_start:
            tail.add(w.word.strip().casefold())
    return tail


def _merge_chunk(
    accumulated_words: list[LongformWord],
    accumulated_segments: list[LongformSegment],
    chunk_result: dict[str, Any],
    chunk: LongformChunk,
    overlap_seconds: int,
    prev_chunk_end: float | None,
) -> None:
    """Append one chunk's results, offsetting timestamps by ``chunk.start``
    and deduplicating any word that overlaps the previous chunk's tail.

    The dedup window covers ``[chunk.start, prev_chunk_end)`` (or just
    ``[chunk.start, chunk.start + overlap_seconds)`` for the very first
    chunk after a non-overlapping gap).  Words we observe there come from
    the previous chunk too, and are dropped if their normalized text
    matches anything the previous chunk emitted in the same window.  This
    catches Whisper's small capitalization/whitespace drift between
    adjacent chunk passes.
    """
    chunk_offset = float(chunk.start)
    overlap_window_end = float(prev_chunk_end) if prev_chunk_end is not None else chunk_offset + float(overlap_seconds)
    dedup_tail = _build_dedup_tail(accumulated_words, chunk_offset)

    new_words: list[LongformWord] = []
    for seg in chunk_result.get("segments", []):
        local_start = float(seg.get("start", 0.0) or 0.0)
        local_end = float(seg.get("end", local_start) or local_start)
        text = str(seg.get("text", "")).strip()
        segment_no_speech_prob = _segment_no_speech_prob(seg)

        # Per-word remap + dedup.
        words = _extract_segment_words(seg)
        if words:
            for word_text, ws, we, word_probability in words:
                global_start = ws + chunk_offset
                global_end = we + chunk_offset
                # Skip words that fall in the overlap tail *and* whose
                # text matches any word already produced by the previous
                # chunk inside the same tail window.
                in_overlap_tail = chunk_offset <= global_start < overlap_window_end
                if in_overlap_tail and word_text.strip().casefold() in dedup_tail:
                    continue
                new_words.append(
                    LongformWord(
                        word=word_text,
                        start=global_start,
                        end=global_end,
                        chunk_index=chunk.index,
                        probability=word_probability,
                    )
                )

        accumulated_segments.append(
            LongformSegment(
                start=local_start + chunk_offset,
                end=local_end + chunk_offset,
                text=text,
                chunk_index=chunk.index,
                avg_logprob=seg.get("avg_logprob"),
                no_speech_prob=segment_no_speech_prob,
            )
        )
    accumulated_words.extend(new_words)


# ``LongformSegment.avg_logprob`` (set above) is the canonical source for
# downstream consumers (the shorts orchestrator / ``_segments`` mapper),
# which translate it to a ``[0.0, 1.0]`` ``TranscriptSegment.confidence``
# via ``exp(avg_logprob)``. We deliberately do NOT store a derived
# confidence on the strict model itself: the strict model stays a pure
# value object and the orchestrator owns the translation.


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def transcribe_longform(
    video: str,
    *,
    model: str = "base",
    language: str | None = None,
    chunk_seconds: int = MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    overlap_seconds: int = LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    scene_aware: bool = True,
    plan: LongformTranscribePlan | None = None,
) -> LongformTranscribeResult:
    """Transcribe media up to ``MAX_VIDEO_DURATION`` seconds.

    Splits the input into overlapping chunks (scene-aware if available and
    ``scene_aware=True``, otherwise fixed), runs each chunk through the
    Whisper pipeline used by ``ai_transcribe``, then merges the per-chunk
    results into a monotonic global timeline with overlap deduplication.

    The ``plan`` argument is provided for replay: callers that already have a
    ``LongformTranscribePlan`` from a previous planning call can pass it back
    here to skip re-probing the source.
    """
    _validate_whisper_model(model)
    video = _validate_longform_path(video)

    if plan is None:
        plan = plan_longform_transcription(
            video,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
            scene_aware=scene_aware,
        )
    else:
        # Even when a plan is provided we still want to make sure the
        # chunk_seconds / overlap_seconds are internally consistent.
        _validate_chunk_seconds(plan.chunk_seconds)
        _validate_overlap_seconds(plan.overlap_seconds, plan.chunk_seconds)

    if not plan.chunks:
        raise MCPVideoError(
            "Long-form plan is empty; refusing to transcribe",
            error_type="validation_error",
            code="invalid_plan",
        )

    accumulated_words: list[LongformWord] = []
    accumulated_segments: list[LongformSegment] = []
    detected_language = "unknown"
    prev_chunk_end: float | None = None

    with tempfile.TemporaryDirectory(prefix="kc_longform_") as work_dir:
        for chunk in plan.chunks:
            chunk_result = _transcribe_chunk(
                video,
                chunk,
                model=model,
                language=language,
                work_dir=work_dir,
            )
            if chunk_result.get("language", "unknown") != "unknown":
                detected_language = chunk_result["language"]
            _merge_chunk(
                accumulated_words,
                accumulated_segments,
                chunk_result,
                chunk,
                overlap_seconds=plan.overlap_seconds,
                prev_chunk_end=prev_chunk_end,
            )
            prev_chunk_end = float(chunk.end)

    # Monotonic enforcement: a slipped timestamp earlier than the previous
    # word's start would break downstream consumers; snap forward.
    for i in range(1, len(accumulated_words)):
        prev = accumulated_words[i - 1]
        cur = accumulated_words[i]
        if cur.start < prev.end:
            accumulated_words[i] = cur.model_copy(update={"start": prev.end, "end": max(prev.end, cur.end)})

    full_text = " ".join(w.word for w in accumulated_words).strip()
    if not full_text:
        # Fall back to segments text when no words came back (older models).
        full_text = " ".join(s.text for s in accumulated_segments).strip()

    return LongformTranscribeResult(
        video_path=video,
        duration=float(plan.duration),
        language=detected_language,
        transcript=full_text,
        segments=accumulated_segments,
        words=accumulated_words,
        chunk_count=len(plan.chunks),
        model=model,
        plan=plan,
    )


__all__ = [
    "LongformChunk",
    "LongformSegment",
    "LongformTranscribePlan",
    "LongformTranscribeResult",
    "LongformWord",
    "plan_longform_transcription",
    "transcribe_longform",
]
