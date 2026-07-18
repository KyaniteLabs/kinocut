"""Bounded CAS reachability accounting and garbage collection (G008 slice 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import EditProjectRecord
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_record,
    append_revision,
    create_edit_project,
    fork_revision,
    compile_repurpose_slice,
    get_edit_project,
    ingest_asset,
    ingest_blob,
    open_project,
    read_records,
    resolve_blob,
)
from kinocut.projectstore.cas_gc import DEFAULT_GC_BUDGET_BYTES, collect_cas_garbage


def _ingest(project, tmp_path: Path, name: str, data: bytes):
    source = tmp_path / name
    source.write_bytes(data)
    return ingest_blob(project, source)


def _head(project, *op_digests):
    ep = create_edit_project(project)
    return append_revision(project, ep.edit_project_id, operation_ids=tuple(op_digests))


def test_reopen_keeps_reachable_and_drops_unreachable(tmp_path):
    project = open_project(tmp_path / "project")
    keep = _ingest(project, tmp_path, "keep.bin", b"reachable payload")
    drop = _ingest(project, tmp_path, "drop.bin", b"stale payload")
    _head(project, keep.digest)
    receipt = collect_cas_garbage(project, budget_bytes=0)
    assert receipt is not None and drop.digest in receipt.deleted_digests
    assert keep.digest not in receipt.deleted_digests
    reopened = open_project(project.root)
    assert resolve_blob(reopened, keep.digest).read_bytes() == b"reachable payload"
    with pytest.raises(MCPVideoError, match="garbage collection"):
        resolve_blob(reopened, drop.digest)


def test_reachable_blob_is_never_evicted_under_pressure(tmp_path):
    project = open_project(tmp_path / "project")
    reach = _ingest(project, tmp_path, "reach.bin", b"head-referenced")
    stale = _ingest(project, tmp_path, "stale.bin", b"unreferenced")
    _head(project, reach.digest)
    receipt = collect_cas_garbage(project, budget_bytes=0)  # maximal pressure
    assert receipt is not None
    assert reach.digest not in receipt.deleted_digests  # reachable never deleted
    assert stale.digest in receipt.deleted_digests
    assert receipt.retained_reachable == 1
    assert resolve_blob(open_project(project.root), reach.digest).read_bytes() == b"head-referenced"
    with pytest.raises(MCPVideoError):
        resolve_blob(open_project(project.root), stale.digest)


def test_eviction_is_oldest_unreachable_first_and_deterministic(tmp_path):
    project = open_project(tmp_path / "project")
    a = _ingest(project, tmp_path, "a.bin", b"a" * 100)
    b = _ingest(project, tmp_path, "b.bin", b"b" * 200)
    c = _ingest(project, tmp_path, "c.bin", b"c" * 50)  # reachable; never evicted
    _head(project, c.digest)
    receipt = collect_cas_garbage(project, budget_bytes=300)
    assert receipt is not None
    assert receipt.deleted_digests == (a.digest, b.digest)  # oldest-first, deterministic
    assert receipt.deleted_bytes == 300
    assert c.digest not in receipt.deleted_digests
    with pytest.raises(MCPVideoError):
        resolve_blob(open_project(project.root), a.digest)
    assert resolve_blob(open_project(project.root), c.digest).read_bytes() == b"c" * 50


def test_under_budget_is_a_noop(tmp_path):
    project = open_project(tmp_path / "project")
    a = _ingest(project, tmp_path, "a.bin", b"a" * 10)
    b = _ingest(project, tmp_path, "b.bin", b"b" * 20)
    receipt = collect_cas_garbage(project, budget_bytes=DEFAULT_GC_BUDGET_BYTES)
    assert receipt is None
    assert read_records(project, "cas_gc") == []
    assert resolve_blob(project, a.digest).read_bytes() == b"a" * 10
    assert resolve_blob(project, b.digest).read_bytes() == b"b" * 20


def test_corrupt_head_fails_closed(tmp_path):
    project = open_project(tmp_path / "project")
    _ingest(project, tmp_path, "blob.bin", b"blob")
    ep = create_edit_project(project)
    append_revision(project, ep.edit_project_id, operation_ids=())
    head = get_edit_project(project, ep.edit_project_id)
    dangling = "sha256:" + "d" * 64
    corrupt = validate_record(
        EditProjectRecord,
        {
            "edit_project_id": ep.edit_project_id,
            "revision_number": head.revision_number + 1,
            "head_revision_id": dangling,
            "project_id": project.project_id,
            "created_by": "agent",
            "supersedes": head.record_id,
        },
    )
    append_record(project, corrupt)  # active head now points to a missing revision
    with pytest.raises(MCPVideoError):
        collect_cas_garbage(project, budget_bytes=DEFAULT_GC_BUDGET_BYTES)


def test_ambiguous_head_fails_closed(tmp_path):
    project = open_project(tmp_path / "project")
    _ingest(project, tmp_path, "blob.bin", b"blob")
    ep = create_edit_project(project)
    extra = validate_record(
        EditProjectRecord,
        {
            "edit_project_id": ep.edit_project_id,
            "revision_number": 9,
            "head_revision_id": "sha256:" + "e" * 64,
            "project_id": project.project_id,
            "created_by": "agent",
        },
    )
    append_record(project, extra)  # a second unsuperseded head -> ambiguous
    with pytest.raises(MCPVideoError):
        collect_cas_garbage(project, budget_bytes=DEFAULT_GC_BUDGET_BYTES)


def test_legacy_assets_are_not_touched_by_cas_gc(tmp_path):
    project = open_project(tmp_path / "project")
    source = tmp_path / "legacy.mov"
    source.write_bytes(b"legacy media")
    asset = ingest_asset(project, source)
    cas = _ingest(project, tmp_path, "cas.bin", b"cas blob")  # unreachable -> evicted
    collect_cas_garbage(project, budget_bytes=0)
    assert (project.root / asset.original_location).exists()  # legacy asset untouched
    with pytest.raises(MCPVideoError):  # only the CAS blob was garbage-collected
        resolve_blob(project, cas.digest)


def test_branch_only_blob_survives_gc_pressure(tmp_path):
    project = open_project(tmp_path / "project")
    shared = _ingest(project, tmp_path, "shared.bin", b"shared")
    branch_only = _ingest(project, tmp_path, "branch.bin", b"branch-only")
    stale = _ingest(project, tmp_path, "stale.bin", b"stale")
    edit = create_edit_project(project)
    first = append_revision(project, edit.edit_project_id, operation_ids=(shared.digest,))
    fork_revision(project, edit.edit_project_id, "alternate", revision_id=first.record_id)
    append_revision(
        project,
        edit.edit_project_id,
        branch_name="alternate",
        operation_ids=(branch_only.digest,),
        base_revision_id=first.record_id,
    )
    receipt = collect_cas_garbage(project, budget_bytes=0)
    assert receipt is not None
    assert branch_only.digest not in receipt.deleted_digests
    assert stale.digest in receipt.deleted_digests
    assert resolve_blob(project, branch_only.digest).read_bytes() == b"branch-only"


def test_compiled_operation_sources_survive_gc_pressure(tmp_path):
    project = open_project(tmp_path / "project")
    source = _ingest(project, tmp_path, "source.mp4", b"compiled source")
    stale = _ingest(project, tmp_path, "stale.bin", b"stale")
    edit = create_edit_project(project)
    compile_repurpose_slice(
        project,
        edit.edit_project_id,
        ({"kind": "trim", "source": source.digest, "start": 0, "end": 1},),
    )
    receipt = collect_cas_garbage(project, budget_bytes=0)
    assert receipt is not None
    assert source.digest not in receipt.deleted_digests
    assert stale.digest in receipt.deleted_digests
    assert resolve_blob(project, source.digest).read_bytes() == b"compiled source"


def test_global_head_is_gc_root_during_branch_write_crash_window(tmp_path):
    project = open_project(tmp_path / "project")
    first_blob = _ingest(project, tmp_path, "first.bin", b"first")
    newest_blob = _ingest(project, tmp_path, "newest.bin", b"newest")
    stale = _ingest(project, tmp_path, "stale.bin", b"stale")
    edit = create_edit_project(project)
    first = append_revision(project, edit.edit_project_id, operation_ids=(first_blob.digest,))
    append_revision(
        project,
        edit.edit_project_id,
        operation_ids=(newest_blob.digest,),
        base_revision_id=first.record_id,
    )
    branch_path = project.root / ".kinocut" / "records" / "branch.jsonl"
    lines = branch_path.read_text().splitlines()
    branch_path.write_text("\n".join(lines[:-1]) + "\n")
    receipt = collect_cas_garbage(project, budget_bytes=0)
    assert receipt is not None
    assert newest_blob.digest not in receipt.deleted_digests
    assert stale.digest in receipt.deleted_digests
    assert resolve_blob(project, newest_blob.digest).read_bytes() == b"newest"


def test_legacy_opaque_operation_ids_conservatively_retain_all_blobs(tmp_path):
    project = open_project(tmp_path / "project")
    first = _ingest(project, tmp_path, "first.bin", b"first")
    second = _ingest(project, tmp_path, "second.bin", b"second")
    edit = create_edit_project(project)
    append_revision(
        project,
        edit.edit_project_id,
        operation_ids=("sha256:" + "f" * 64,),
    )
    assert collect_cas_garbage(project, budget_bytes=0) is None
    assert resolve_blob(project, first.digest).read_bytes() == b"first"
    assert resolve_blob(project, second.digest).read_bytes() == b"second"
