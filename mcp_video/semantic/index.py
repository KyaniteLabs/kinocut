"""Dependency-free local semantic index over canonical source evidence."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from mcp_video.errors import ValidationError as MCPValidationError

from .models import AnalyzerProvenance, FrozenModel, SemanticTimeline, Sha256, SourceSpan, canonical_digest

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
MatchMethod = Literal["lexical", "vector", "hybrid"]


class EmbeddingRecord(FrozenModel):
    span_id: str
    values: tuple[float, ...] = Field(min_length=1)
    provenance: AnalyzerProvenance


class IndexDocument(FrozenModel):
    span_id: str
    source_id: str
    span_kind: Literal["word", "shot", "scene"]
    source_start_seconds: float = Field(ge=0.0)
    source_end_seconds: float = Field(ge=0.0)
    source_text: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    embedding: tuple[float, ...] | None = None
    embedding_provenance: AnalyzerProvenance | None = None


class SemanticIndex(FrozenModel):
    schema_version: Literal[1] = 1
    artifact_kind: Literal["semantic_index"] = "semantic_index"
    timeline_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    source_id: str
    dimensions: int | None = Field(default=None, ge=1)
    documents: tuple[IndexDocument, ...]
    index_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @classmethod
    def create(
        cls, *, timeline: SemanticTimeline, documents: tuple[IndexDocument, ...], dimensions: int | None
    ) -> Self:
        ordered = tuple(
            sorted(documents, key=lambda doc: (doc.source_start_seconds, doc.source_end_seconds, doc.span_id))
        )
        prototype = cls.model_construct(
            timeline_sha256=timeline.timeline_sha256,
            source_id=timeline.source.source_id,
            dimensions=dimensions,
            documents=ordered,
            index_sha256="sha256:" + "0" * 64,
        )
        digest = canonical_digest(prototype, exclude={"index_sha256"})
        return cls(
            timeline_sha256=timeline.timeline_sha256,
            source_id=timeline.source.source_id,
            dimensions=dimensions,
            documents=ordered,
            index_sha256=digest,
        )

    @model_validator(mode="after")
    def validate_index_hash(self) -> Self:
        expected = canonical_digest(self, exclude={"index_sha256"})
        if self.index_sha256 != expected:
            raise ValueError("index hash does not match canonical index content")
        if len({document.span_id for document in self.documents}) != len(self.documents):
            raise ValueError("index document span ids must be unique")
        if self.dimensions is None and any(document.embedding is not None for document in self.documents):
            raise ValueError("embedding documents require an index dimension")
        if self.dimensions is not None and any(
            document.embedding is not None and len(document.embedding) != self.dimensions for document in self.documents
        ):
            raise ValueError("all embedding dimensions must match the index")
        return self


class SemanticQueryHit(FrozenModel):
    span_id: str
    source_id: str
    span_kind: Literal["word", "shot", "scene"]
    source_start_seconds: float
    source_end_seconds: float
    source_text: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    match_method: MatchMethod


class SemanticQueryResponse(FrozenModel):
    index: SemanticIndex
    text: str | None = None
    embedding_supplied: bool = False
    results: tuple[SemanticQueryHit, ...]


def _source_text(timeline: SemanticTimeline, span: SourceSpan) -> str | None:
    if span.kind == "word":
        return getattr(span, "text", None)
    words = (
        word.text
        for word in timeline.words
        if word.text is not None
        and word.source_start_seconds < span.source_end_seconds
        and word.source_end_seconds > span.source_start_seconds
    )
    text = " ".join(words).strip()
    return text or None


def _embedding_map(records: Sequence[EmbeddingRecord]) -> tuple[dict[str, EmbeddingRecord], int | None]:
    indexed = {record.span_id: record for record in records}
    if len(indexed) != len(records):
        raise MCPValidationError("embeddings", "records must use unique span ids")
    dimensions = {len(record.values) for record in records}
    if len(dimensions) > 1:
        raise MCPValidationError("embeddings", "records must use one dimension")
    return indexed, next(iter(dimensions), None)


def build_semantic_index(
    timeline: SemanticTimeline,
    *,
    embeddings: Sequence[EmbeddingRecord] = (),
) -> SemanticIndex:
    """Build a deterministic in-process index without invoking models or network services."""

    vectors, dimensions = _embedding_map(embeddings)
    searchable: tuple[SourceSpan, ...] = (*timeline.words, *timeline.shots, *timeline.scenes)
    known_ids = {span.span_id for span in searchable}
    if not set(vectors).issubset(known_ids):
        raise MCPValidationError("embeddings", "records must reference indexed semantic span ids")
    documents = tuple(
        IndexDocument(
            span_id=span.span_id,
            source_id=span.source_id,
            span_kind=span.kind,
            source_start_seconds=span.source_start_seconds,
            source_end_seconds=span.source_end_seconds,
            source_text=_source_text(timeline, span),
            confidence=span.confidence,
            embedding=vectors[span.span_id].values if span.span_id in vectors else None,
            embedding_provenance=vectors[span.span_id].provenance if span.span_id in vectors else None,
        )
        for span in searchable
    )
    return SemanticIndex.create(timeline=timeline, documents=documents, dimensions=dimensions)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"\w+", text.casefold()))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(0.0, numerator / (left_norm * right_norm))


def _score(
    document: IndexDocument, text_tokens: frozenset[str], embedding: tuple[float, ...] | None
) -> tuple[float, MatchMethod | None]:
    lexical = 0.0
    if text_tokens and document.source_text:
        lexical = len(text_tokens & _tokens(document.source_text)) / len(text_tokens)
    vector = _cosine(document.embedding, embedding) if embedding is not None and document.embedding is not None else 0.0
    method = "hybrid" if lexical > 0 and vector > 0 else "lexical" if lexical > 0 else "vector" if vector > 0 else None
    return max(lexical, vector) * document.confidence, method


def query_semantic_index(
    index: SemanticIndex,
    *,
    text: str | None = None,
    embedding: Sequence[float] | None = None,
    limit: int = 10,
    min_confidence: float = 0.0,
) -> tuple[SemanticQueryHit, ...]:
    """Return ranked source evidence; abstain when no source-backed match exists."""

    if not text and embedding is None:
        raise MCPValidationError("query", "a lexical query or caller-supplied embedding is required")
    if limit < 1:
        raise MCPValidationError("limit", "must be at least one")
    if not 0 <= min_confidence <= 1:
        raise MCPValidationError("min_confidence", "must be between zero and one")
    vector = tuple(embedding) if embedding is not None else None
    if vector is not None and (index.dimensions is None or len(vector) != index.dimensions):
        raise MCPValidationError("embedding", "query dimension must match the local index")
    ranked: list[tuple[float, IndexDocument, MatchMethod]] = []
    for document in index.documents:
        confidence, method = _score(document, _tokens(text or ""), vector)
        if method is not None and confidence > 0 and confidence >= min_confidence:
            ranked.append((confidence, document, method))
    ranked.sort(key=lambda item: (-item[0], item[1].source_start_seconds, item[1].span_id))
    return tuple(
        SemanticQueryHit(
            span_id=document.span_id,
            source_id=document.source_id,
            span_kind=document.span_kind,
            source_start_seconds=document.source_start_seconds,
            source_end_seconds=document.source_end_seconds,
            source_text=document.source_text,
            confidence=confidence,
            match_method=method,
        )
        for confidence, document, method in ranked[:limit]
    )


def query_local_index(
    artifact: SemanticTimeline | SemanticIndex | Mapping[str, Any],
    *,
    text: str | None = None,
    embedding: Sequence[float] | None = None,
    limit: int = 10,
    min_confidence: float = 0.0,
) -> SemanticQueryResponse:
    """Surface adapter accepting a validated model or its JSON-compatible dump."""

    if isinstance(artifact, SemanticTimeline):
        index = build_semantic_index(artifact)
    elif isinstance(artifact, SemanticIndex):
        index = artifact
    elif artifact.get("artifact_kind") == "semantic_timeline":
        index = build_semantic_index(SemanticTimeline.model_validate(artifact))
    else:
        index = SemanticIndex.model_validate(artifact)
    results = query_semantic_index(index, text=text, embedding=embedding, limit=limit, min_confidence=min_confidence)
    return SemanticQueryResponse(index=index, text=text, embedding_supplied=embedding is not None, results=results)
