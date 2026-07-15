"""Duplicate / near-duplicate detection over the approved clip registry (#39).

Exact duplicates share a content-addressed ``asset_id`` (byte-identical media).
Near-duplicates share a perceptual ``embedding_ref`` (an optional provider
hash); clips without an embedding are never perceptually grouped. Both are
derived read-only projections — never a stored verdict.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from kinocut.contracts._common import ValueObject
from kinocut.contracts.registry import ClipRecord
from kinocut.projectstore import Project, read_records


class DuplicateGroup(ValueObject):
    """A cluster of >= 2 clips that are byte- or perceptually-identical."""

    clip_count: int = Field(ge=2)
    asset_ids: tuple[str, ...]
    embedding_ref: str | None = None


class DuplicateReport(ValueObject):
    """Read-only duplicate projection over the active clip registry."""

    exact: tuple[DuplicateGroup, ...] = ()
    perceptual: tuple[DuplicateGroup, ...] = ()


def _active_clips(project: Project) -> list[ClipRecord]:
    rows = [item for item in read_records(project, "clip_record") if type(item) is ClipRecord]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def duplicate_clip_groups(project: Project) -> DuplicateReport:
    """Group active approved clips by exact asset id and by perceptual embedding."""

    clips = _active_clips(project)

    exact_buckets: dict[str, int] = defaultdict(int)
    perceptual_buckets: dict[str, list[str]] = defaultdict(list)
    for clip in clips:
        exact_buckets[clip.asset_id] += 1
        if clip.embedding_ref is not None:
            perceptual_buckets[clip.embedding_ref].append(clip.asset_id)

    exact = tuple(
        DuplicateGroup(clip_count=count, asset_ids=(asset_id,))
        for asset_id, count in sorted(exact_buckets.items())
        if count >= 2
    )
    perceptual = tuple(
        DuplicateGroup(
            clip_count=len(assets),
            asset_ids=tuple(sorted(set(assets))),
            embedding_ref=embedding_ref,
        )
        for embedding_ref, assets in sorted(perceptual_buckets.items())
        if len(assets) >= 2
    )
    return DuplicateReport(exact=exact, perceptual=perceptual)


__all__ = ["DuplicateGroup", "DuplicateReport", "duplicate_clip_groups"]
