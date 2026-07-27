from __future__ import annotations

import json
from pathlib import Path

import pytest

from kinocut.aivideo.learning.project_recipes import export_project_recipe, replay_project_recipe
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    compile_repurpose_slice,
    create_edit_project,
    ingest_blob,
    open_project,
    read_records,
)


def _source(project, tmp_path: Path, name: str, payload: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(payload)
    return ingest_blob(project, path, media_type="video/mp4").digest


def test_project_revision_exports_and_replays_a_portable_recipe(tmp_path: Path):
    project = open_project(tmp_path / "project")
    source = _source(project, tmp_path, "source.mp4", b"source")
    edit = create_edit_project(project)
    operations = [
        {"kind": "trim", "source": source, "start": 1, "end": 4},
        {"kind": "reframe", "source": source, "width": 1080, "height": 1920},
    ]
    revision = compile_repurpose_slice(project, edit.edit_project_id, operations)

    exported = export_project_recipe(
        project,
        edit.edit_project_id,
        revision.record_id,
        operations,
        policies=("local-only",),
        required_checks=("source-integrity",),
        review_gates=("human-preview",),
    )
    repeated = export_project_recipe(project, edit.edit_project_id, revision.record_id, operations)

    artifact_text = json.dumps(exported["artifact"])
    assert str(tmp_path) not in artifact_text
    assert source not in artifact_text
    assert exported["portable_sha256"] == repeated["portable_sha256"]
    assert exported["artifact"]["parameter_slots"] == [{"name": "source_1", "type": "cas_digest", "required": True}]

    target_source = _source(project, tmp_path, "target.mp4", b"target")
    target = create_edit_project(project)
    replayed = replay_project_recipe(
        project,
        target.edit_project_id,
        exported["artifact"],
        {"source_1": target_source},
    )

    assert replayed["portable_sha256"] == exported["portable_sha256"]
    revisions = [record for record in read_records(project, "edit_revision") if record.record_id == replayed["replay_revision_id"]]
    assert len(revisions) == 1
    assert len(revisions[0].operation_ids) == 2


def test_project_recipe_export_requires_exact_revision_operations(tmp_path: Path):
    project = open_project(tmp_path / "project")
    source = _source(project, tmp_path, "source.mp4", b"source")
    edit = create_edit_project(project)
    operations = [{"kind": "trim", "source": source, "start": 1, "end": 4}]
    revision = compile_repurpose_slice(project, edit.edit_project_id, operations)

    with pytest.raises(MCPVideoError, match="do not match"):
        export_project_recipe(
            project,
            edit.edit_project_id,
            revision.record_id,
            [{"kind": "trim", "source": source, "start": 1, "end": 3}],
        )


def test_project_recipe_replay_rejects_tampering_and_missing_bindings(tmp_path: Path):
    project = open_project(tmp_path / "project")
    source = _source(project, tmp_path, "source.mp4", b"source")
    edit = create_edit_project(project)
    operations = [{"kind": "trim", "source": source, "start": 0, "end": 1}]
    revision = compile_repurpose_slice(project, edit.edit_project_id, operations)
    artifact = export_project_recipe(project, edit.edit_project_id, revision.record_id, operations)["artifact"]
    target = create_edit_project(project)

    tampered = {**artifact, "portable_sha256": "sha256:" + "0" * 64}
    with pytest.raises(MCPVideoError, match="identity"):
        replay_project_recipe(project, target.edit_project_id, tampered, {"source_1": source})
    with pytest.raises(MCPVideoError, match="binding"):
        replay_project_recipe(project, target.edit_project_id, artifact, {})
