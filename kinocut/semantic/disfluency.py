"""Deterministic disfluency evidence from local Whisper words and Silero VAD spans."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from typing import Any

from pydantic import Field, model_validator

from kinocut.errors import ValidationError as MCPValidationError

from .edl import EditDecisionList
from .generators import generate_false_start_edl, generate_filler_edl
from .models import AnalyzerProvenance, FrozenModel, SemanticTimeline, SilenceSpan, SourceMedia, WordSpan

_FILLERS = frozenset({"um", "uh", "erm", "er", "hmm"})
_TOKEN_RE = re.compile(r"^\W+|\W+$")


class WhisperWordEvidence(FrozenModel):
    word: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    probability: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def end_follows_start(self) -> WhisperWordEvidence:
        if self.end <= self.start:
            raise ValueError("Whisper word end must be greater than start")
        return self


class VADSpeechEvidence(FrozenModel):
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def end_follows_start(self) -> VADSpeechEvidence:
        if self.end <= self.start:
            raise ValueError("VAD speech end must be greater than start")
        return self


def build_local_disfluency_timeline(
    *,
    source: SourceMedia | Mapping[str, Any],
    whisper_words: Iterable[WhisperWordEvidence | Mapping[str, Any]],
    vad_speech: Iterable[VADSpeechEvidence | Mapping[str, Any]],
    provenance: AnalyzerProvenance | Mapping[str, Any],
    min_word_confidence: float = 0.5,
) -> SemanticTimeline:
    """Bind local analyzer output to source time; uncertain evidence is never cuttable."""

    if not 0.0 <= min_word_confidence <= 1.0:
        raise MCPValidationError("min_word_confidence", "must be between zero and one")
    media = source if isinstance(source, SourceMedia) else SourceMedia.model_validate(source)
    analyzer = provenance if isinstance(provenance, AnalyzerProvenance) else AnalyzerProvenance.model_validate(provenance)
    words = tuple(
        sorted(
            (item if isinstance(item, WhisperWordEvidence) else WhisperWordEvidence.model_validate(item) for item in whisper_words),
            key=lambda item: (item.start, item.end, item.word),
        )
    )
    speech = tuple(
        sorted(
            (item if isinstance(item, VADSpeechEvidence) else VADSpeechEvidence.model_validate(item) for item in vad_speech),
            key=lambda item: (item.start, item.end),
        )
    )
    _validate_inputs(media, words, speech)
    restarts = _restart_word_indices(words)
    word_spans = tuple(
        _word_span(media, analyzer, word, index, restarts, speech, min_word_confidence)
        for index, word in enumerate(words)
    )
    silences = _silence_spans(media, analyzer, speech)
    return SemanticTimeline.create(source=media, words=word_spans, silences=silences)


def generate_disfluency_edl(
    timeline: SemanticTimeline,
    *,
    min_confidence: float = 0.85,
) -> EditDecisionList:
    """Combine source-backed filler and restart proposals without applying them."""

    fillers = generate_filler_edl(timeline, min_confidence=min_confidence)
    restarts = generate_false_start_edl(timeline, min_confidence=min_confidence)
    edits = tuple(sorted((*fillers.edits, *restarts.edits), key=lambda item: (item.source_start_seconds, item.edit_id)))
    return EditDecisionList.create(timeline=timeline, edits=edits)


def _validate_inputs(
    source: SourceMedia,
    words: tuple[WhisperWordEvidence, ...],
    speech: tuple[VADSpeechEvidence, ...],
) -> None:
    if not speech:
        raise MCPValidationError("vad_speech", "local Silero VAD evidence is required")
    if any(item.end > source.duration_seconds for item in (*words, *speech)):
        raise MCPValidationError("analysis", "Whisper/VAD evidence exceeds source duration")
    if any(current.start < previous.end for previous, current in pairwise(words)):
        raise MCPValidationError("whisper_words", "word timestamps must not overlap")
    if any(current.start < previous.end for previous, current in pairwise(speech)):
        raise MCPValidationError("vad_speech", "speech spans must not overlap")


def _token(word: str) -> str:
    return _TOKEN_RE.sub("", word.casefold())


def _restart_word_indices(words: Sequence[WhisperWordEvidence]) -> frozenset[int]:
    tokens = tuple(_token(word.word) for word in words)
    marked: set[int] = set()
    for start in range(len(tokens)):
        for length in range(min(4, (len(tokens) - start) // 2), 0, -1):
            middle = start + length
            end = middle + length
            if tokens[start:middle] == tokens[middle:end] and words[middle].start - words[middle - 1].end <= 1.5:
                marked.update(range(start, middle))
                break
    return frozenset(marked)


def _vad_coverage(word: WhisperWordEvidence, speech: Sequence[VADSpeechEvidence]) -> float:
    overlap = sum(max(0.0, min(word.end, span.end) - max(word.start, span.start)) for span in speech)
    return min(1.0, overlap / (word.end - word.start))


def _word_span(
    source: SourceMedia,
    provenance: AnalyzerProvenance,
    word: WhisperWordEvidence,
    index: int,
    restarts: frozenset[int],
    speech: Sequence[VADSpeechEvidence],
    threshold: float,
) -> WordSpan:
    uncertainty = []
    if word.probability < threshold:
        uncertainty.append("low_whisper_confidence")
    if _vad_coverage(word, speech) < 0.5:
        uncertainty.append("word_outside_vad_speech")
    disfluency = "none"
    if not uncertainty:
        disfluency = "false_start" if index in restarts else "filler" if _token(word.word) in _FILLERS else "none"
    return WordSpan.create(
        source=source,
        start_seconds=word.start,
        end_seconds=word.end,
        confidence=word.probability,
        provenance=provenance,
        text=word.word,
        text_status="uncertain" if uncertainty else "observed",
        uncertainty=tuple(uncertainty),
        disfluency=disfluency,
    )


def _silence_spans(
    source: SourceMedia,
    provenance: AnalyzerProvenance,
    speech: Sequence[VADSpeechEvidence],
) -> tuple[SilenceSpan, ...]:
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for span in speech:
        if span.start > cursor:
            gaps.append((cursor, span.start))
        cursor = span.end
    if cursor < source.duration_seconds:
        gaps.append((cursor, source.duration_seconds))
    return tuple(
        SilenceSpan.create(
            source=source,
            start_seconds=start,
            end_seconds=end,
            confidence=1.0,
            provenance=provenance,
        )
        for start, end in gaps
        if end > start
    )


__all__ = [
    "VADSpeechEvidence",
    "WhisperWordEvidence",
    "build_local_disfluency_timeline",
    "generate_disfluency_edl",
]
