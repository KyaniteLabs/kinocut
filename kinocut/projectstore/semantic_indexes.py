"""Durable semantic indexes bound to projectstore revisions and CAS."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import EditRevisionRecord, SemanticIndexArtifactRecord
from kinocut.projectstore import store
from kinocut.projectstore.cas import ingest_blob, resolve_blob
from kinocut.projectstore.edit_projects import get_edit_project
from kinocut.semantic.index import SemanticIndex, SemanticQueryHit, query_semantic_index


def _owned_revision(project: store.Project, edit_project_id: str, revision_id: str) -> EditRevisionRecord:
    get_edit_project(project, edit_project_id)
    matches = [
        record
        for record in store.read_records(project, "edit_revision")
        if isinstance(record, EditRevisionRecord)
        and record.record_id == revision_id
        and record.edit_project_id == edit_project_id
    ]
    if len(matches) != 1:
        raise contract_error("semantic index revision is not owned by the edit project", INVALID_RECORD)
    return matches[0]


def _index_records(project: store.Project) -> list[SemanticIndexArtifactRecord]:
    return [
        record
        for record in store.read_records(project, "semantic_index_artifact")
        if isinstance(record, SemanticIndexArtifactRecord)
    ]


def persist_semantic_index(
    project: store.Project,
    edit_project_id: str,
    revision_id: str,
    index: SemanticIndex,
) -> SemanticIndexArtifactRecord:
    """Persist canonical index JSON in CAS and bind it to an owned revision."""

    _owned_revision(project, edit_project_id, revision_id)
    payload = index.model_dump_json().encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=project.root, prefix=".semantic-index-", delete=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            temporary = Path(output.name)
        manifest = ingest_blob(project, temporary, media_type="application/vnd.kinocut.semantic-index+json")
    except OSError as error:
        raise contract_error("semantic index could not be persisted", INVALID_RECORD) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    existing = [
        record
        for record in _index_records(project)
        if record.edit_project_id == edit_project_id
        and record.revision_id == revision_id
        and record.index_digest == manifest.digest
    ]
    if existing:
        return existing[0]
    record = validate_record(
        SemanticIndexArtifactRecord,
        {
            "project_id": project.project_id,
            "created_by": "tool",
            "edit_project_id": edit_project_id,
            "revision_id": revision_id,
            "index_digest": manifest.digest,
            "timeline_sha256": index.timeline_sha256,
            "source_id": index.source_id,
        },
    )
    return store.append_record(project, record)


def load_semantic_index(
    project: store.Project,
    edit_project_id: str,
    revision_id: str,
    index_digest: str,
) -> SemanticIndex:
    """Load and revalidate an index only through its owning project/revision."""

    _owned_revision(project, edit_project_id, revision_id)
    matches = [
        record
        for record in _index_records(project)
        if record.edit_project_id == edit_project_id
        and record.revision_id == revision_id
        and record.index_digest == index_digest
    ]
    if len(matches) != 1:
        raise contract_error("semantic index is not bound to this edit revision", INVALID_RECORD)
    try:
        index = SemanticIndex.model_validate_json(resolve_blob(project, index_digest).read_bytes())
    except OSError as error:
        raise contract_error("semantic index could not be loaded", INVALID_RECORD) from error
    if index.timeline_sha256 != matches[0].timeline_sha256 or index.source_id != matches[0].source_id:
        raise contract_error("semantic index metadata does not match its project record", INVALID_RECORD)
    return index


def find_moments(
    project: store.Project,
    edit_project_id: str,
    revision_id: str,
    index_digest: str,
    *,
    text: str | None = None,
    embedding: tuple[float, ...] | None = None,
    limit: int = 10,
    min_confidence: float = 0.0,
) -> tuple[SemanticQueryHit, ...]:
    """Query one revision-bound local index without model or network fallback."""

    index = load_semantic_index(project, edit_project_id, revision_id, index_digest)
    return query_semantic_index(
        index,
        text=text,
        embedding=embedding,
        limit=limit,
        min_confidence=min_confidence,
    )


__all__ = ["find_moments", "load_semantic_index", "persist_semantic_index"]
