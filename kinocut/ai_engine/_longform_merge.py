"""Timestamp remapping and overlap deduplication for long-form chunks."""

from __future__ import annotations

import math
from typing import Any

from ._longform_models import LongformChunk, LongformSegment, LongformWord


def _word_probability(word: dict[str, Any]) -> float | None:
    """Return an observed probability, or an exp(logprob) fallback, without invention."""
    raw = word.get("probability")
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = math.nan
        if math.isfinite(value) and 0.0 <= value <= 1.0:
            return value
    raw = word.get("avg_logprob")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return 1.0 if value >= 0.0 else math.exp(value)


def _segment_no_speech_prob(segment: dict[str, Any]) -> float | None:
    raw = segment.get("no_speech_prob")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _segment_avg_logprob(segment: dict[str, Any]) -> float | None:
    raw = segment.get("avg_logprob")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value <= 0.0 else None


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
        except (TypeError, ValueError):
            continue
        if not text or not math.isfinite(start) or not math.isfinite(end) or start < 0.0 or end <= start:
            continue
        extracted.append((text, start, end, _word_probability(word)))
    return extracted


def _build_dedup_tail(words: list[LongformWord], overlap_start: float) -> set[str]:
    return {word.word.strip().casefold() for word in words if word.start >= overlap_start}


def _merge_chunk(
    accumulated_words: list[LongformWord],
    accumulated_segments: list[LongformSegment],
    chunk_result: dict[str, Any],
    chunk: LongformChunk,
    overlap_seconds: int,
    prev_chunk_end: float | None,
) -> None:
    """Append one chunk in global source time, dropping repeated overlap-tail words."""
    offset = chunk.start
    overlap_end = prev_chunk_end if prev_chunk_end is not None else offset + overlap_seconds
    prior_tail = _build_dedup_tail(accumulated_words, offset)
    new_words: list[LongformWord] = []
    for raw_segment in chunk_result.get("segments") or ():
        if not isinstance(raw_segment, dict):
            continue
        try:
            local_start = float(raw_segment.get("start", 0.0) or 0.0)
            local_end = float(raw_segment.get("end", local_start) or local_start)
        except (TypeError, ValueError):
            continue
        text = str(raw_segment.get("text", "")).strip()
        if not text or local_start < 0.0 or local_end <= local_start:
            continue
        for word_text, word_start, word_end, probability in _extract_segment_words(raw_segment):
            global_start = word_start + offset
            normalized = word_text.casefold()
            if offset <= global_start < overlap_end and normalized in prior_tail:
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
