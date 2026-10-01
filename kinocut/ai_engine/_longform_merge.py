"""Timestamp remapping and overlap deduplication for long-form chunks."""

from __future__ import annotations

import math
from typing import Any

from ..errors import MCPVideoError
from ..defaults import DEFAULT_LONGFORM_DUPLICATE_TIME_TOLERANCE_SECONDS
from ._longform_models import LongformChunk, LongformSegment, LongformWord


def _word_probability(word: dict[str, Any]) -> float | None:
    """Return an observed probability, or an exp(logprob) fallback, without invention."""
    raw = word.get("probability")
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            value = math.nan
        if not isinstance(raw, bool) and math.isfinite(value) and 0.0 <= value <= 1.0:
            return value
    raw = word.get("avg_logprob")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(raw, bool) or not math.isfinite(value):
        return None
    return 1.0 if value >= 0.0 else math.exp(value)


def _segment_no_speech_prob(segment: dict[str, Any]) -> float | None:
    raw = segment.get("no_speech_prob")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if not isinstance(raw, bool) and math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _segment_avg_logprob(segment: dict[str, Any]) -> float | None:
    raw = segment.get("avg_logprob")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if not isinstance(raw, bool) and math.isfinite(value) and value <= 0.0 else None


def _extract_segment_words(
    segment: dict[str, Any],
) -> list[tuple[str, float, float, float | None]]:
    """Extract valid real word spans; absent confidence remains ``None``."""
    extracted: list[tuple[str, float, float, float | None]] = []
    for word in segment.get("words") or ():
        if not isinstance(word, dict):
            continue
        text = str(word.get("word", "")).strip()
        try:
            start = float(word.get("start", 0.0) or 0.0)
            end = float(word.get("end", start) or start)
        except (TypeError, ValueError, OverflowError):
            continue
        if not text or not math.isfinite(start) or not math.isfinite(end) or start < 0.0 or end <= start:
            continue
        extracted.append((text, start, end, _word_probability(word)))
    return extracted


def _build_dedup_tail(words: list[LongformWord], overlap_start: float) -> set[str]:
    return {word.word.strip().casefold() for word in words if word.end > overlap_start}


def _validate_chunk_result_shape(chunk_result: Any) -> None:
    """Validate iterable containers before formatting or merging backend output."""
    if not isinstance(chunk_result, dict):
        raise MCPVideoError(
            "Recognizer output must be an object", error_type="validation_error", code="invalid_transcript_output"
        )
    segments = chunk_result.get("segments")
    collections = [segments]
    if isinstance(segments, (list, tuple)):
        collections.extend(segment.get("words") for segment in segments if isinstance(segment, dict))
    if any(collection is not None and not isinstance(collection, (list, tuple)) for collection in collections):
        raise MCPVideoError(
            "Recognizer segments and words must be arrays",
            error_type="validation_error",
            code="invalid_transcript_output",
        )


def _validate_chunk_timings(chunk_result: dict[str, Any], chunk: LongformChunk) -> None:
    """Reject claimed non-finite/out-of-source spans before mutating accumulated output."""
    _validate_chunk_result_shape(chunk_result)
    for segment in chunk_result.get("segments") or ():
        if not isinstance(segment, dict):
            continue
        for kind, entries in (("segment", (segment,)), ("word", segment.get("words") or ())):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    if any(isinstance(entry.get(key), bool) for key in ("start", "end")):
                        start = end = math.nan
                    else:
                        start, end = float(entry.get("start", 0.0)), float(entry.get("end", entry.get("start", 0.0)))
                except OverflowError:
                    start = end = math.inf
                except (TypeError, ValueError):
                    continue  # Preserve existing handling of missing/unparseable entries.
                if math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= chunk.duration:
                    continue
                raise MCPVideoError(
                    "Observed transcript timing is non-finite or outside its decoded chunk",
                    error_type="validation_error",
                    code="invalid_transcript_timing",
                    suggested_action={
                        "auto_fix": False,
                        "chunk_index": chunk.index,
                        "entry_kind": kind,
                        "expected_range_seconds": [0.0, chunk.duration],
                        "description": "Review recognizer timing; no span was clipped or invented",
                    },
                )


def _consume_duplicate_event(
    prior_events: list[LongformWord],
    consumed: set[int],
    text: str,
    start: float,
    end: float,
) -> bool:
    """Match one same-token overlapping event; disjoint repetitions always survive."""
    candidates = [
        index
        for index, word in enumerate(prior_events)
        if index not in consumed
        and word.word.strip().casefold() == text
        and min(word.end, end) > max(word.start, start)
        and abs(word.start - start) <= DEFAULT_LONGFORM_DUPLICATE_TIME_TOLERANCE_SECONDS
        and abs(word.end - end) <= DEFAULT_LONGFORM_DUPLICATE_TIME_TOLERANCE_SECONDS
    ]
    if not candidates:
        return False
    match = min(
        candidates,
        key=lambda index: (
            abs(prior_events[index].start - start) + abs(prior_events[index].end - end),
            index,
        ),
    )
    consumed.add(match)
    return True


def _merge_chunk(
    accumulated_words: list[LongformWord],
    accumulated_segments: list[LongformSegment],
    chunk_result: dict[str, Any],
    chunk: LongformChunk,
    overlap_seconds: int,
    prev_chunk_end: float | None,
) -> None:
    """Append source-bound spans; deduplicate one-to-one overlapping word events."""
    _validate_chunk_timings(chunk_result, chunk)
    offset = chunk.start
    overlap_end = prev_chunk_end if prev_chunk_end is not None else offset + overlap_seconds
    prior_tail = _build_dedup_tail(accumulated_words, offset)
    prior_events = [word for word in accumulated_words if word.end > offset and word.start < overlap_end]
    consumed: set[int] = set()
    new_words: list[LongformWord] = []
    for raw_segment in chunk_result.get("segments") or ():
        if not isinstance(raw_segment, dict):
            continue
        try:
            local_start = float(raw_segment.get("start", 0.0) or 0.0)
            local_end = float(raw_segment.get("end", local_start) or local_start)
        except (TypeError, ValueError, OverflowError):
            continue
        text = str(raw_segment.get("text", "")).strip()
        if not text or local_start < 0.0 or local_end <= local_start:
            continue
        for word_text, word_start, word_end, probability in _extract_segment_words(raw_segment):
            global_start = word_start + offset
            normalized = word_text.casefold()
            if (
                offset <= global_start < overlap_end
                and normalized in prior_tail
                and _consume_duplicate_event(
                    prior_events,
                    consumed,
                    normalized,
                    global_start,
                    word_end + offset,
                )
            ):
                continue
            new_words.append(
                LongformWord(
                    word=word_text,
                    start=global_start,
                    end=word_end + offset,
                    chunk_index=chunk.index,
                    probability=probability,
                )
            )
        accumulated_segments.append(
            LongformSegment(
                start=local_start + offset,
                end=local_end + offset,
                text=text,
                chunk_index=chunk.index,
                avg_logprob=_segment_avg_logprob(raw_segment),
                no_speech_prob=_segment_no_speech_prob(raw_segment),
            )
        )
    accumulated_words.extend(new_words)


__all__ = [
    "_build_dedup_tail",
    "_extract_segment_words",
    "_merge_chunk",
    "_segment_avg_logprob",
    "_segment_no_speech_prob",
    "_word_probability",
]
