"""Deterministic BM25 (k1=1.2, b=0.75) for the router eval baseline."""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase and split on every non-alphanumeric run."""

    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """Rank a fixed document set with deterministic name tie-breaking."""

    def __init__(self, documents: dict[str, str], *, k1: float = 1.2, b: float = 0.75) -> None:
        if not documents:
            raise ValueError("BM25Index needs at least one document")
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 parameters out of range")
        self.k1 = k1
        self.b = b
        self._terms: dict[str, Counter[str]] = {}
        self._lengths: dict[str, int] = {}
        document_frequency: Counter[str] = Counter()
        for name, text in documents.items():
            tokens = tokenize(text)
            counts = Counter(tokens)
            self._terms[name] = counts
            self._lengths[name] = len(tokens)
            document_frequency.update(counts.keys())
        self._document_count = len(documents)
        self._average_length = sum(self._lengths.values()) / self._document_count
        self._idf = {
            term: math.log(1 + (self._document_count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def score(self, query: str, name: str) -> float:
        """Return the BM25 score of one document for one query."""

        counts = self._terms[name]
        length = self._lengths[name]
        total = 0.0
        for term in tokenize(query):
            frequency = counts.get(term)
            if not frequency:
                continue
            denominator = frequency + self.k1 * (1 - self.b + self.b * length / self._average_length)
            total += self._idf[term] * frequency * (self.k1 + 1) / denominator
        return total

    def top_k(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return the best ``k`` documents, ties broken by ascending name."""

        if k <= 0:
            raise ValueError("k must be positive")
        ranked = [(name, self.score(query, name)) for name in self._terms]
        ranked.sort(key=lambda row: (-row[1], row[0]))
        return ranked[:k]
