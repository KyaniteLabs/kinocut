from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_revision,
    create_edit_project,
    find_moments,
    load_semantic_index,
    open_project,
    persist_semantic_index,
    read_records,
    resolve_blob,
)
from kinocut.projectstore.cas_gc import collect_cas_garbage
from kinocut.semantic.index import build_semantic_index
from kinocut.semantic.models import AnalyzerProvenance, SemanticTimeline, SourceMedia, WordSpan
from kinocut.server_tools_intent import video_find_moments


def _index():
    source = SourceMedia.create(content_sha256="sha256:" + "1" * 64, duration_seconds=4)
    provenance = AnalyzerProvenance(
        analyzer_id="fixture.semantic",
        analyzer_version="1",
        model_id="local-fixture",
        model_sha256="sha256:" + "2" * 64,
        determinism_scope="fixture",
    )
    words = (
        WordSpan.create(
            source=source,
            start_seconds=1,
            end_seconds=1.4,
            confidence=0.95,
            provenance=provenance,
            text="red",
        ),
        WordSpan.create(
            source=source,
            start_seconds=1.5,
            end_seconds=2,
            confidence=0.9,
            provenance=provenance,
            text="bicycle",
        ),
    )
    return build_semantic_index(SemanticTimeline.create(source=source, words=words))


def _revision(project):
    edit = create_edit_project(project)
    revision = append_revision(project, edit.edit_project_id, operation_ids=())
    return edit, revision


def test_semantic_index_round_trip_is_revision_bound_and_idempotent(tmp_path: Path):
    project = open_project(tmp_path / "project")
    edit, revision = _revision(project)
    index = _index()

    first = persist_semantic_index(project, edit.edit_project_id, revision.record_id, index)
    second = persist_semantic_index(project, edit.edit_project_id, revision.record_id, index)

    assert first.record_id == second.record_id
    assert len(read_records(project, "semantic_index_artifact")) == 1
    assert load_semantic_index(project, edit.edit_project_id, revision.record_id, first.index_digest) == index
    assert find_moments(
        project,
        edit.edit_project_id,
        revision.record_id,
        first.index_digest,
        text="red bicycle",
    )


def test_semantic_index_rejects_cross_project_or_revision_access(tmp_path: Path):
    project = open_project(tmp_path / "project")
    edit, revision = _revision(project)
    other, other_revision = _revision(project)
    record = persist_semantic_index(project, edit.edit_project_id, revision.record_id, _index())

    with pytest.raises(MCPVideoError, match="not bound"):
        load_semantic_index(project, other.edit_project_id, other_revision.record_id, record.index_digest)


def test_semantic_index_cas_reachability_follows_revision(tmp_path: Path):
    project = open_project(tmp_path / "project")
    edit, revision = _revision(project)
    record = persist_semantic_index(project, edit.edit_project_id, revision.record_id, _index())
    stale = tmp_path / "stale.bin"
    stale.write_bytes(b"stale")
    from kinocut.projectstore import ingest_blob

    stale_record = ingest_blob(project, stale)

    receipt = collect_cas_garbage(project, budget_bytes=0)

    assert receipt is not None
    assert record.index_digest not in receipt.deleted_digests
    assert stale_record.digest in receipt.deleted_digests
    assert resolve_blob(project, record.index_digest).is_file()


def test_public_find_moments_persists_then_reuses_local_index(tmp_path: Path):
    project = open_project(tmp_path / "project")
    edit, revision = _revision(project)

    created = video_find_moments(
        str(project.root),
        edit.edit_project_id,
        revision.record_id,
        text="red",
        semantic_artifact=_index().model_dump(mode="json"),
    )
    reused = video_find_moments(
        str(project.root),
        edit.edit_project_id,
        revision.record_id,
        text="bicycle",
        index_digest=created["index_digest"],
    )

    assert created["success"] is True and reused["success"] is True
    assert created["index_digest"] == reused["index_digest"]
    assert created["results"][0]["source_text"] == "red"
    assert reused["results"][0]["source_text"] == "bicycle"
