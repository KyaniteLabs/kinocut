from __future__ import annotations

from mcp_video.semantic.index import (
    EmbeddingRecord,
    build_semantic_index,
    query_semantic_index,
)
from mcp_video.semantic.models import (
    AnalyzerProvenance,
    SemanticTimeline,
    ShotSpan,
    SourceMedia,
    WordSpan,
)


def _timeline() -> tuple[SemanticTimeline, AnalyzerProvenance]:
    source = SourceMedia.create(content_sha256="sha256:" + "1" * 64, duration_seconds=8)
    provenance = AnalyzerProvenance(
        analyzer_id="fixture.semantic",
        analyzer_version="2",
        model_id="local-fixture",
        model_sha256="sha256:" + "2" * 64,
        determinism_scope="fixture",
    )
    words = (
        WordSpan.create(
            source=source, start_seconds=1, end_seconds=1.4, confidence=0.9, provenance=provenance, text="red"
        ),
        WordSpan.create(
            source=source, start_seconds=1.5, end_seconds=2, confidence=0.8, provenance=provenance, text="bicycle"
        ),
        WordSpan.create(
            source=source,
            start_seconds=5,
            end_seconds=5.5,
            confidence=0.6,
            provenance=provenance,
            text="unclear",
            text_status="uncertain",
            uncertainty=("low signal",),
        ),
    )
    shot = ShotSpan.create(
        source=source, start_seconds=0, end_seconds=4, confidence=0.95, provenance=provenance, ordinal=0
    )
    return SemanticTimeline.create(source=source, words=words, shots=(shot,)), provenance


def test_local_index_returns_only_source_backed_evidence_with_confidence() -> None:
    timeline, _ = _timeline()
    index = build_semantic_index(timeline)

    results = query_semantic_index(index, text="red bicycle")

    assert results
    assert results[0].span_id in {word.span_id for word in timeline.words} | {timeline.shots[0].span_id}
    assert results[0].source_text in {"red", "bicycle", "red bicycle"}
    assert 0 < results[0].confidence <= 0.95
    assert all("description" not in result.model_dump() for result in results)
    assert query_semantic_index(index, text="dragon flying over a castle") == ()
    assert build_semantic_index(timeline).index_sha256 == index.index_sha256


def test_vector_query_requires_caller_supplied_local_embeddings_and_stays_stable() -> None:
    timeline, provenance = _timeline()
    shot = timeline.shots[0]
    embedding = EmbeddingRecord(span_id=shot.span_id, values=(1.0, 0.0), provenance=provenance)
    index = build_semantic_index(timeline, embeddings=(embedding,))

    hits = query_semantic_index(index, embedding=(1.0, 0.0))

    assert hits[0].span_id == shot.span_id
    assert hits[0].match_method == "vector"
    assert hits[0].source_text == "red bicycle"
    assert query_semantic_index(index, embedding=(0.0, 1.0)) == ()
