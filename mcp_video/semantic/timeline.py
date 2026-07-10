"""Pure construction adapter for canonical semantic timelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TypeVar

from .models import (
    AnalyzerProvenance,
    AudioEventSpan,
    KeyframeSpan,
    SceneSpan,
    SemanticTimeline,
    ShotSpan,
    SilenceSpan,
    SourceMedia,
    SourceSpan,
    SpeakerSpan,
    WordSpan,
)

SpanT = TypeVar("SpanT", bound=SourceSpan)


def _source(value: SourceMedia | Mapping[str, Any]) -> SourceMedia:
    if isinstance(value, SourceMedia):
        return value
    if "source_id" in value:
        return SourceMedia.model_validate(value)
    return SourceMedia.create(
        content_sha256=str(value["content_sha256"]),
        duration_seconds=float(value["duration_seconds"]),
    )


def _span(span_type: type[SpanT], value: SpanT | Mapping[str, Any], source: SourceMedia) -> SpanT:
    if not isinstance(value, Mapping):
        return value
    if "span_id" in value:
        return span_type.model_validate(value)
    payload = dict(value)
    provenance = AnalyzerProvenance.model_validate(payload.pop("provenance"))
    if span_type is KeyframeSpan:
        timestamp = payload.pop("timestamp_seconds", payload.pop("source_start_seconds", None))
        return span_type._create(
            source=source,
            source_start_seconds=timestamp,
            source_end_seconds=timestamp,
            provenance=provenance,
            **payload,
        )
    start = payload.pop("start_seconds", payload.pop("source_start_seconds", None))
    end = payload.pop("end_seconds", payload.pop("source_end_seconds", None))
    return span_type._create(
        source=source,
        source_start_seconds=start,
        source_end_seconds=end,
        provenance=provenance,
        **payload,
    )


def _track(
    span_type: type[SpanT], values: Iterable[SpanT | Mapping[str, Any]], source: SourceMedia
) -> tuple[SpanT, ...]:
    return tuple(_span(span_type, value, source) for value in values)


def build_semantic_timeline(
    *,
    source: SourceMedia | Mapping[str, Any],
    words: Iterable[WordSpan | Mapping[str, Any]] = (),
    speakers: Iterable[SpeakerSpan | Mapping[str, Any]] = (),
    shots: Iterable[ShotSpan | Mapping[str, Any]] = (),
    scenes: Iterable[SceneSpan | Mapping[str, Any]] = (),
    silences: Iterable[SilenceSpan | Mapping[str, Any]] = (),
    audio_events: Iterable[AudioEventSpan | Mapping[str, Any]] = (),
    keyframes: Iterable[KeyframeSpan | Mapping[str, Any]] = (),
) -> SemanticTimeline:
    """Validate JSON-compatible analyzer evidence and assign canonical stable IDs."""

    canonical_source = _source(source)
    return SemanticTimeline.create(
        source=canonical_source,
        words=_track(WordSpan, words, canonical_source),
        speakers=_track(SpeakerSpan, speakers, canonical_source),
        shots=_track(ShotSpan, shots, canonical_source),
        scenes=_track(SceneSpan, scenes, canonical_source),
        silences=_track(SilenceSpan, silences, canonical_source),
        audio_events=_track(AudioEventSpan, audio_events, canonical_source),
        keyframes=_track(KeyframeSpan, keyframes, canonical_source),
    )
