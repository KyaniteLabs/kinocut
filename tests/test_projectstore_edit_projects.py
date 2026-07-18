"""Behavior tests for the Phase-1 durable edit-project repository."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

import kinocut.projectstore.store as store
from kinocut.contracts._common import canonical_record_id
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_revision,
    checkout,
    create_edit_project,
    diff_revisions,
    fork_revision,
    get_branch,
    get_edit_project,
    list_branches,
    open_project,
    read_records,
    undo,
)

_OP1 = "sha256:" + "1" * 64
_OP2 = "sha256:" + "2" * 64


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _raise_oserror_with(secret):
    raise OSError(13, "Permission denied", secret)


def test_create_get_round_trip_and_unknown_fails_closed(project):
    ep = create_edit_project(project)
    assert ep.revision_number == 0 and ep.head_revision_id is None and ep.edit_project_id.startswith("edit_project:")
    assert get_edit_project(project, ep.edit_project_id).record_id == ep.record_id
    with pytest.raises(MCPVideoError):
        get_edit_project(project, "edit_project:" + "b" * 64)


def test_identity_and_revisions_survive_reopen(tmp_path):
    project = open_project(tmp_path / "proj")
    ep = create_edit_project(project)
    r1 = append_revision(project, ep.edit_project_id, operation_ids=(_OP1,))
    reopened = open_project(project.root)
    head = get_edit_project(reopened, ep.edit_project_id)
    assert head.revision_number == 1 and head.head_revision_id == r1.record_id
    assert [r.record_id for r in read_records(reopened, "edit_revision")] == [r1.record_id]


def test_two_linear_revisions_advance_head_and_parent_chain(project):
    ep = create_edit_project(project)
    r1 = append_revision(project, ep.edit_project_id, operation_ids=(_OP1,))
    r2 = append_revision(project, ep.edit_project_id, operation_ids=(_OP2,), base_revision_id=r1.record_id)
    assert r1.revision_number == 1 and r1.parent_revision_id is None
    assert r2.revision_number == 2 and r2.parent_revision_id == r1.record_id
    head = get_edit_project(project, ep.edit_project_id)
    assert head.revision_number == 2 and head.head_revision_id == r2.record_id
    projects = read_records(project, "edit_project")
    superseded = {p.supersedes for p in projects if p.supersedes}
    assert [p.record_id for p in projects if p.record_id not in superseded] == [head.record_id]


def test_stale_base_is_rejected_and_appends_nothing(project):
    ep = create_edit_project(project)
    append_revision(project, ep.edit_project_id, operation_ids=(_OP1,))
    for bad in (None, "sha256:" + "0" * 64):
        with pytest.raises(MCPVideoError):
            append_revision(project, ep.edit_project_id, operation_ids=(_OP2,), base_revision_id=bad)
    assert len(read_records(project, "edit_revision")) == len(read_records(project, "kernel_event")) == 1
    assert get_edit_project(project, ep.edit_project_id).revision_number == 1


def test_first_revision_rejects_non_null_base(project):
    ep = create_edit_project(project)
    with pytest.raises(MCPVideoError):
        append_revision(project, ep.edit_project_id, operation_ids=(_OP1,), base_revision_id="sha256:" + "9" * 64)


def test_create_is_idempotent_on_supplied_identity(project):
    identity = "edit_project:" + "a" * 64
    first = create_edit_project(project, edit_project_id=identity)
    second = create_edit_project(project, edit_project_id=identity)
    assert first.record_id == second.record_id
    assert len(read_records(project, "edit_project")) == 1


def test_each_revision_appends_exactly_one_ordered_event(project):
    ep = create_edit_project(project)
    r1 = append_revision(project, ep.edit_project_id, operation_ids=(_OP1,))
    r2 = append_revision(project, ep.edit_project_id, operation_ids=(_OP2,), base_revision_id=r1.record_id)
    events = read_records(project, "kernel_event")
    assert (
        len(events) == 2
        and [e.event_id for e in events] == [1, 2]
        and {e.event_kind for e in events} == {"revision.created"}
    )
    assert [e.revision_id for e in events] == [r1.record_id, r2.record_id] and events[
        0
    ].subject_record_id == r1.record_id


@pytest.mark.parametrize("fail_at_call", [1, 2, 3, 4, 5])
def test_failed_write_rolls_back_the_whole_transaction(project, monkeypatch, fail_at_call):
    ep = create_edit_project(project)
    real_append = store._atomic_append
    calls = {"n": 0}

    def flaky(path, line):
        calls["n"] += 1
        if calls["n"] == fail_at_call:  # revision, event, sources, edit-project head, branch head
            raise MCPVideoError("simulated write failure")
        return real_append(path, line)

    monkeypatch.setattr(store, "_atomic_append", flaky)
    with pytest.raises(MCPVideoError):
        append_revision(project, ep.edit_project_id, operation_ids=(_OP1,), source_digests=(_OP1,))
    assert read_records(project, "edit_revision") == []
    assert read_records(project, "kernel_event") == []
    assert read_records(project, "revision_sources") == []
    assert read_records(project, "branch") == []
    assert get_edit_project(project, ep.edit_project_id).revision_number == 0
    assert len(read_records(project, "edit_project")) == 1


def test_concurrent_appends_with_same_base_serialize_one_wins(project):
    ep = create_edit_project(project)
    results = {"ok": 0, "stale": 0}
    lock = threading.Lock()

    def worker():
        try:
            append_revision(project, ep.edit_project_id, operation_ids=(_OP1,))
        except MCPVideoError:
            with lock:
                results["stale"] += 1
            return
        with lock:
            results["ok"] += 1

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results["ok"] == 1 and results["stale"] == 5
    assert (
        len(read_records(project, "edit_revision")) == 1
        and get_edit_project(project, ep.edit_project_id).revision_number == 1
    )


def test_edit_project_state_is_isolated_per_project_store(tmp_path):
    one = open_project(tmp_path / "one")
    two = open_project(tmp_path / "two")
    ep = create_edit_project(one)
    append_revision(one, ep.edit_project_id, operation_ids=(_OP1,))
    with pytest.raises(MCPVideoError):
        get_edit_project(two, ep.edit_project_id)
    assert read_records(two, "edit_project") == read_records(two, "edit_revision") == []
    for record in read_records(one, "edit_project"):
        assert record.project_id == one.project_id


def test_canonical_record_id_is_content_derived_and_records_are_frozen(project):
    ep = create_edit_project(project)
    stored_ep = read_records(project, "edit_project")[0]
    assert stored_ep.record_id == canonical_record_id(stored_ep)
    rev = append_revision(project, ep.edit_project_id, operation_ids=(_OP1,))
    stored_rev = read_records(project, "edit_revision")[0]
    assert stored_rev.record_id == canonical_record_id(stored_rev) == rev.record_id
    with pytest.raises(ValidationError):
        stored_rev.revision_number = 99  # records are frozen


def test_snapshot_read_oserror_is_mapped_without_host_path_leak(project, monkeypatch):
    host_path_marker = "/secret/SNAPSHOT-MARKER/edit_project.jsonl"
    monkeypatch.setattr(Path, "read_bytes", lambda self: _raise_oserror_with(host_path_marker))
    with pytest.raises(MCPVideoError) as exc:
        append_revision(project, create_edit_project(project).edit_project_id, operation_ids=(_OP1,))
    assert "SNAPSHOT-MARKER" not in str(exc.value) and host_path_marker not in str(exc.value)


def test_rollback_unlink_oserror_is_mapped_without_host_path_leak(project, monkeypatch):
    ep = create_edit_project(project)
    real_append, calls = store._atomic_append, {"n": 0}

    def flaky(path, line):
        calls["n"] += 1
        if calls["n"] == 2:  # event write fails after the revision file commits
            raise MCPVideoError("simulated write failure")
        return real_append(path, line)

    monkeypatch.setattr(store, "_atomic_append", flaky)
    host_path_marker = "/secret/ROLLBACK-MARKER/edit_revision.jsonl"
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: _raise_oserror_with(host_path_marker))
    with pytest.raises(MCPVideoError) as exc:
        append_revision(project, ep.edit_project_id, operation_ids=(_OP1,))
    assert "ROLLBACK-MARKER" not in str(exc.value) and host_path_marker not in str(exc.value)


def test_legacy_history_synthesizes_main_without_writing(project):
    edit = create_edit_project(project)
    revision = append_revision(project, edit.edit_project_id, operation_ids=(_OP1,))
    before = list(read_records(project, "branch"))
    branch = get_branch(project, edit.edit_project_id)
    assert branch.branch_name == "main"
    assert branch.head_revision_id == revision.record_id
    assert list(read_records(project, "branch")) == before


def test_fork_append_checkout_diff_and_global_numbering(project):
    edit = create_edit_project(project)
    first = append_revision(project, edit.edit_project_id, operation_ids=(_OP1,))
    fork_revision(project, edit.edit_project_id, "alternate", revision_id=first.record_id)
    main_second = append_revision(
        project, edit.edit_project_id, operation_ids=(_OP2,), base_revision_id=first.record_id
    )
    alternate_op = "sha256:" + "3" * 64
    alternate = append_revision(
        project,
        edit.edit_project_id,
        branch_name="alternate",
        operation_ids=(alternate_op,),
        base_revision_id=first.record_id,
    )
    assert main_second.revision_number == 2
    assert alternate.revision_number == 3
    assert checkout(project, edit.edit_project_id, "alternate") == alternate
    assert {branch.branch_name for branch in list_branches(project, edit.edit_project_id)} == {
        "alternate",
        "main",
    }
    assert diff_revisions(project, main_second.record_id, alternate.record_id) == {
        "added": (alternate_op,),
        "removed": (_OP2,),
    }


def test_feature_append_does_not_move_implicit_main(project):
    edit = create_edit_project(project)
    first = append_revision(project, edit.edit_project_id, operation_ids=(_OP1,))
    fork_revision(project, edit.edit_project_id, "alternate", revision_id=first.record_id)
    alternate = append_revision(
        project,
        edit.edit_project_id,
        branch_name="alternate",
        operation_ids=(_OP2,),
        base_revision_id=first.record_id,
    )
    assert get_branch(project, edit.edit_project_id, "main").head_revision_id == first.record_id
    assert get_branch(project, edit.edit_project_id, "alternate").head_revision_id == alternate.record_id


def test_fork_rejects_revision_from_another_edit_project(project):
    first_project = create_edit_project(project)
    revision = append_revision(project, first_project.edit_project_id, operation_ids=(_OP1,))
    second_project = create_edit_project(project)
    with pytest.raises(MCPVideoError):
        fork_revision(
            project,
            second_project.edit_project_id,
            "invalid",
            revision_id=revision.record_id,
        )


def test_branch_stale_head_and_revision_event_vocabulary(project):
    edit = create_edit_project(project)
    first = append_revision(project, edit.edit_project_id, operation_ids=(_OP1,))
    fork_revision(project, edit.edit_project_id, "alternate", revision_id=first.record_id)
    append_revision(
        project,
        edit.edit_project_id,
        branch_name="alternate",
        operation_ids=(_OP2,),
        base_revision_id=first.record_id,
    )
    with pytest.raises(MCPVideoError):
        append_revision(
            project,
            edit.edit_project_id,
            branch_name="alternate",
            operation_ids=(_OP2,),
            base_revision_id=first.record_id,
        )
    assert {event.event_kind for event in read_records(project, "kernel_event")} == {"revision.created"}


def test_undo_appends_compensating_delta(project):
    edit = create_edit_project(project)
    first = append_revision(project, edit.edit_project_id, operation_ids=(_OP1,))
    compensating = "sha256:" + "4" * 64
    undone = undo(
        project,
        edit.edit_project_id,
        compensating_operation_ids=(compensating,),
        base_revision_id=first.record_id,
    )
    assert undone.parent_revision_id == first.record_id
    assert undone.operation_ids == (compensating,)
