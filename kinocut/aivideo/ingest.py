"""Project ingest facade: immutable originals + generation lineage + rights.

This is a thin facade over the public :func:`kinocut.projectstore.ingest_asset`
— it adds **no parallel store** and holds **no** ingest logic of its own. The
public store owns the single-pass hash-and-copy, the content-addressed install,
the append-under-one-lock transaction, and the generation-lineage + rights
metadata boundary (validated up front, idempotent on identical metadata, plain
prior assets enriched by an append-only superseding record, conflicts rejected).
Every filesystem failure still surfaces as a stable, privacy-safe
:class:`~kinocut.errors.MCPVideoError` from the underlying store.
"""

from __future__ import annotations

from pathlib import Path

from kinocut.contracts.asset import AssetRecord, GenerationLineage, UsageRightsStatus
from kinocut.projectstore import Project, ingest_asset


def ingest_project_asset(
    project: Project,
    source_path: str | Path,
    *,
    lineage: GenerationLineage | None = None,
    usage_rights_status: UsageRightsStatus = UsageRightsStatus.UNKNOWN,
    usage_rights_evidence_ref: str | None = None,
) -> AssetRecord:
    """Ingest ``source_path`` as an immutable original with lineage and rights.

    A thin delegation to :func:`kinocut.projectstore.ingest_asset`, which runs the
    hash+copy, digest existence check, content-addressed install, and enriched
    record append under one project lock. Rights default to *unverified*
    (:attr:`UsageRightsStatus.UNKNOWN`); a re-ingest of identical bytes returns the
    already-stored record unchanged.
    """

    return ingest_asset(
        project,
        source_path,
        lineage=lineage,
        usage_rights_status=usage_rights_status,
        usage_rights_evidence_ref=usage_rights_evidence_ref,
    )
