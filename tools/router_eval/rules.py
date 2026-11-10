"""The two deterministic baselines: shipped discovery (R1) and BM25 (R2)."""

from __future__ import annotations

from functools import lru_cache

from .bm25 import BM25Index
from .catalog import load_operations


@lru_cache(maxsize=1)
def _discovery_catalog() -> tuple[dict[str, object], ...]:
    from kinocut.tool_registry import discovery_catalog

    return tuple(discovery_catalog())


def r1_rank(request: str) -> list[str]:
    """R1: the shipped ``discover_tools`` ordering over the shipped catalog."""

    from kinocut.tool_discovery import discover_tools

    result = discover_tools(request, _discovery_catalog())
    return [str(tool["name"]) for tool in result["tools"]]


@lru_cache(maxsize=1)
def _bm25_index() -> BM25Index:
    operations = load_operations()
    documents = {
        operation.name: (f"{operation.name} {operation.verb} {operation.family} {operation.description}")
        for operation in operations
    }
    return BM25Index(documents)


def r2_rank(request: str, k: int = 5) -> list[tuple[str, float]]:
    """R2: BM25 over name + verb + family + summary, deterministic tie-break."""

    return _bm25_index().top_k(request, k)
