from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_video.semantic.models import (
    AnalyzerProvenance,
    AudioEventSpan,
    KeyframeSpan,
    SceneSpan,
    SemanticTimeline,
    ShotSpan,
    SilenceSpan,
    SourceMedia,
    SpeakerSpan,
    WordSpan,
)
from mcp_video.semantic.timeline import build_semantic_timeline


SHA = "sha256:" + "a" * 64
MODEL_SHA = "sha256:" + "b" * 64


def _provenance() -> AnalyzerProvenance:
    return AnalyzerProvenance(
        analyzer_id="fixture.transcriber",
        analyzer_version="1.0.0",
        model_id="fixture-local",
        model_sha256=MODEL_SHA,
        determinism_scope="same source, model, and analyzer settings",
    )


def test_canonical_timeline_has_stable_source_backed_ids_and_hashes() -> None:
    source = SourceMedia.create(content_sha256=SHA, duration_seconds=12.0)
    provenance = _provenance()
    word = WordSpan.create(
        source=source,
        start_seconds=1.0,
        end_seconds=1.4,
        confidence=0.63,
        provenance=provenance,
        text="maybe",
        text_status="uncertain",
        uncertainty=("decoder alternatives were close",),
    )
    speaker = SpeakerSpan.create(
        source=source,
        start_seconds=1.0,
        end_seconds=2.0,
        confidence=0.51,
        provenance=provenance,
        speaker_label=None,
        label_status="uncertain",
        uncertainty=("speaker could not be separated reliably",),
    )
    spans = {
        "shots": (
            ShotSpan.create(
                source=source, start_seconds=0, end_seconds=6, confidence=0.9, provenance=provenance, ordinal=0
            ),
        ),
        "scenes": (
            SceneSpan.create(
                source=source, start_seconds=0, end_seconds=12, confidence=0.8, provenance=provenance, ordinal=0
            ),
        ),
        "silences": (
            SilenceSpan.create(
                source=source, start_seconds=2, end_seconds=3, confidence=0.92, provenance=provenance, mean_dbfs=-51.0
            ),
        ),
        "audio_events": (
            AudioEventSpan.create(
                source=source,
                start_seconds=3,
                end_seconds=3.5,
                confidence=0.7,
                provenance=provenance,
                event_type="music",
            ),
        ),
        "keyframes": (KeyframeSpan.create(source=source, timestamp_seconds=4, confidence=0.99, provenance=provenance),),
    }

    first = SemanticTimeline.create(source=source, words=(word,), speakers=(speaker,), **spans)
    second = SemanticTimeline.create(source=source, words=(word,), speakers=(speaker,), **spans)

    assert first.timeline_sha256 == second.timeline_sha256
    assert (
        word.span_id
        == WordSpan.create(
            source=source,
            start_seconds=1.0,
            end_seconds=1.4,
            confidence=0.63,
            provenance=provenance,
            text="maybe",
            text_status="uncertain",
            uncertainty=("decoder alternatives were close",),
        ).span_id
    )
    assert word.span_id.startswith("word:")
    assert word.span_sha256.startswith("sha256:")
    assert first.words[0].text_status == "uncertain"
    assert first.speakers[0].speaker_label is None
    assert "description" not in first.shots[0].model_dump()


def test_timeline_rejects_invalid_source_time_tampering_and_extra_claims() -> None:
    source = SourceMedia.create(content_sha256=SHA, duration_seconds=5.0)
    provenance = _provenance()

    with pytest.raises(ValidationError, match="source duration"):
        WordSpan.create(
            source=source,
            start_seconds=4.8,
            end_seconds=5.1,
            confidence=0.9,
            provenance=provenance,
            text="outside",
        )

    word = WordSpan.create(
        source=source,
        start_seconds=1,
        end_seconds=2,
        confidence=1,
        provenance=provenance,
        text="source",
    )
    with pytest.raises(ValidationError, match="Extra inputs"):
        WordSpan.model_validate({**word.model_dump(mode="json"), "invented_description": "a happy person"})

    tampered = word.model_dump(mode="json")
    tampered["span_id"] = "word:" + "0" * 64
    with pytest.raises(ValidationError, match="stable span id"):
        WordSpan.model_validate(tampered)

    other_source = SourceMedia.create(content_sha256="sha256:" + "c" * 64, duration_seconds=5)
    foreign = WordSpan.create(
        source=other_source,
        start_seconds=1,
        end_seconds=2,
        confidence=1,
        provenance=provenance,
        text="foreign",
    )
    with pytest.raises(ValidationError, match="timeline source"):
        SemanticTimeline.create(source=source, words=(foreign,))


def test_surface_builder_accepts_json_compatible_inputs() -> None:
    timeline = build_semantic_timeline(
        source={"content_sha256": SHA, "duration_seconds": 5.0},
        words=(
            {
                "start_seconds": 1.0,
                "end_seconds": 1.5,
                "confidence": 0.8,
                "provenance": _provenance().model_dump(mode="json"),
                "text": "hello",
            },
        ),
    )

    assert isinstance(timeline, SemanticTimeline)
    assert timeline.words[0].text == "hello"
