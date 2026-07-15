"""Internal approved-asset registry primitives (backlog #36, #38, #41).

This package is **internal-only**. It is not re-exported through
``kinocut.contracts``, never registered as MCP/CLI tools, and carries no public
client surface. The controller layer will join later to wire these primitives
into the editor loop.

Public-ish surface (within the package):

* Record contracts: :class:`ClipRecord`, :class:`BedRecord`, :class:`LineageLink`.
* Technical metadata: :class:`ClipTechnicalMetadata`, :class:`BedTechnicalMetadata`.
* Lineage graph: :class:`LineageGraph`.
* Write layer: :func:`register_clip`, :func:`register_bed`, :func:`register_lineage`.
* Query layer: :func:`query_approved_clips`, :func:`query_reusable_beds`, :class:`QueryPage`.
"""

from __future__ import annotations

from kinocut.registry._duplicate import DuplicateGroup, DuplicateReport, duplicate_clip_groups
from kinocut.registry._lineage import LineageGraph
from kinocut.registry._query import QueryPage, query_approved_clips, query_reusable_beds
from kinocut.contracts.registry import (
    BedRecord,
    BedTechnicalMetadata,
    ClipRecord,
    ClipTechnicalMetadata,
    LineageLink,
    LineageRelation,
)
from kinocut.registry._store import register_bed, register_clip, register_lineage

__all__ = [
    "BedRecord",
    "BedTechnicalMetadata",
    "ClipRecord",
    "ClipTechnicalMetadata",
    "DuplicateGroup",
    "DuplicateReport",
    "LineageGraph",
    "LineageLink",
    "LineageRelation",
    "QueryPage",
    "duplicate_clip_groups",
    "query_approved_clips",
    "query_reusable_beds",
    "register_bed",
    "register_clip",
    "register_lineage",
]
