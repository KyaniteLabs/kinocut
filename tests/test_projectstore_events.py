"""Behavior tests for the durable internal event kernel (Phase-1, linear only).

Exercises ``append_event`` / ``event_poll`` and the render-job success
integration: the three admitted kinds, strict project-scoped monotonic event
ids, exclusive ``after_event_id`` filtering, allowed-kind validation, bounded
positive limits, reopen persistence, fail-closed duplicate/non-monotonic stored
ids, serialized concurrent appends, and exactly-one ``render.completed``.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import KernelEventRecord
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_event,
    append_revision,
    create_edit_project,
    event_poll,
    open_project,
    submit_render_job,
)
from kinocut.projectstore import render_jobs
import kinocut.projectstore.edit_projects as edit_projects
from kinocut.projectstore.store import append_record, read_records

_EP = "edit_project:" + "c" * 64
_JOB = "job:" + "d" * 64
_REV = "sha256:" + "a" * 64


def _sub(n: int) -> str:
    return "sha256:" + f"{n:064x}"


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "proj")


def _seed(project) -> None:
    """Append one of each kind plus repeats so ordering/filtering/limit are exercisable."""
    append_event(project, "revision.created", edit_project_id=_EP, subject_record_id=_sub(1), revision_id=_REV)
    append_event(
        project, "render.completed", edit_project_id=_EP, subject_record_id=_sub(2), revision_id=_REV, job_id=_JOB
    )
    append_event(project, "quality.gate.failed", edit_project_id=_EP, subject_record_id=_sub(3), job_id=_JOB)
    append_event(
        project, "render.completed", edit_project_id=_EP, subject_record_id=_sub(4), revision_id=_REV, job_id=_JOB
    )
    other_rev = "sha256:" + "9" * 64
    append_event(project, "revision.created", edit_project_id=_EP, subject_record_id=_sub(5), revision_id=other_rev)


def _inject(project, event_id: int, *, subject: str) -> None:
    """Bypass the event kernel to plant a chosen event_id directly (corruption fixture)."""
    append_record(
        project,
        validate_record(
            KernelEventRecord,
            {
                "event_id": event_id,
                "event_kind": "quality.gate.failed",
                "edit_project_id": _EP,
                "job_id": _JOB,
                "subject_record_id": subject,
                "project_id": project.project_id,
                "created_by": "tool",
            },
        ),
    )


def _write_spec(project, *, name="spec.json"):
    spec = {
        "schema_version": 1,
        "name": "two-stage",
        "sources": {"src1": {"path": "in.mp4"}},
        "outputs": {"out1": {"path": "out.mp4"}},
        "steps": [
            {"id": "s1", "op": "probe", "inputs": {"src": "@sources.src1"}},
            {"id": "s2", "op": "convert", "inputs": {"src": "@sources.src1"}, "output": "@outputs.out1"},
        ],
    }
    path = project.root / name
    path.write_text(json.dumps(spec))
    return path


def test_event_api_exported_from_projectstore():
    """Smoke: the approved Phase-1 event API is importable from the package surface."""
    import kinocut.projectstore as projectstore

    assert "append_event" in projectstore.__all__
    assert "event_poll" in projectstore.__all__
    assert projectstore.append_event is append_event
    assert projectstore.event_poll is event_poll


def test_append_each_kind_assigns_strictly_monotonic_ids(project):
    rev = append_event(project, "revision.created", edit_project_id=_EP, subject_record_id=_sub(1), revision_id=_REV)
    rnd = append_event(
        project, "render.completed", edit_project_id=_EP, subject_record_id=_sub(2), revision_id=_REV, job_id=_JOB
    )
    qgf = append_event(project, "quality.gate.failed", edit_project_id=_EP, subject_record_id=_sub(3), job_id=_JOB)
    assert (rev.event_id, rnd.event_id, qgf.event_id) == (1, 2, 3)
    assert rev.event_kind == "revision.created" and rev.job_id is None and rev.revision_id == _REV
    assert rnd.event_kind == "render.completed" and rnd.job_id == _JOB and rnd.revision_id == _REV
    assert qgf.event_kind == "quality.gate.failed" and qgf.job_id == _JOB and qgf.revision_id is None


def test_poll_returns_stable_event_id_order_and_survives_reopen(tmp_path):
    project = open_project(tmp_path / "proj")
    _seed(project)
    assert [e.event_id for e in event_poll(project)] == [1, 2, 3, 4, 5]
    assert [e.event_kind for e in event_poll(project)] == [
        "revision.created",
        "render.completed",
        "quality.gate.failed",
        "render.completed",
        "revision.created",
    ]
    reopened = open_project(project.root)  # persistence: the log is durable on disk
    assert [e.record_id for e in event_poll(reopened)] == [e.record_id for e in event_poll(project)]


def test_poll_after_event_id_is_exclusive(project):
    _seed(project)
    assert [e.event_id for e in event_poll(project, after_event_id=2)] == [3, 4, 5]
    assert [e.event_id for e in event_poll(project, after_event_id=5)] == []
    assert [e.event_id for e in event_poll(project, after_event_id=1)] == [2, 3, 4, 5]


def test_poll_filters_by_allowed_kinds(project):
    _seed(project)
    renders = event_poll(project, event_kinds=("render.completed",))
    assert [e.event_id for e in renders] == [2, 4]
    assert {e.event_kind for e in renders} == {"render.completed"}
    assert event_poll(project, event_kinds=()) == []  # no kinds selected -> empty
    both = event_poll(project, event_kinds=("revision.created", "quality.gate.failed"))
    assert [e.event_id for e in both] == [1, 3, 5]


def test_poll_limit_is_bounded_and_positive(project):
    _seed(project)
    assert [e.event_id for e in event_poll(project, limit=2)] == [1, 2]
    assert [e.event_id for e in event_poll(project, after_event_id=2, limit=1)] == [3]
    assert [e.event_id for e in event_poll(project, limit=100)] == [1, 2, 3, 4, 5]  # over-large is clamped


def test_poll_rejects_unsupported_or_malformed_kinds(project):
    _seed(project)
    with pytest.raises(MCPVideoError):
        event_poll(project, event_kinds=("render.started",))
    with pytest.raises(MCPVideoError):
        event_poll(project, event_kinds="render.completed")  # a bare string is not a kind iterable


def test_poll_rejects_non_positive_after_and_limit(project):
    _seed(project)
    for bad in (0, -1, 1.0, True):
        with pytest.raises(MCPVideoError):
            event_poll(project, after_event_id=bad)
    for bad in (0, -5, 2.0, True):
        with pytest.raises(MCPVideoError):
            event_poll(project, limit=bad)


def test_append_rejects_unsupported_kind(project):
    for bad in ("render.started", "RENDER.completed", "render.completed "):
        with pytest.raises(MCPVideoError):
            append_event(project, bad, edit_project_id=_EP, subject_record_id=_sub(1), revision_id=_REV)
    assert event_poll(project) == []  # nothing persisted on rejection


def test_required_identities_per_kind(project):
    # revision.created requires revision_id and forbids job_id
    with pytest.raises(MCPVideoError):
        append_event(project, "revision.created", edit_project_id=_EP, subject_record_id=_sub(1))
    with pytest.raises(MCPVideoError):
        append_event(
            project, "revision.created", edit_project_id=_EP, subject_record_id=_sub(1), revision_id=_REV, job_id=_JOB
        )
    # render.completed requires both job_id and revision_id
    with pytest.raises(MCPVideoError):
        append_event(project, "render.completed", edit_project_id=_EP, subject_record_id=_sub(1), revision_id=_REV)
    with pytest.raises(MCPVideoError):
        append_event(project, "render.completed", edit_project_id=_EP, subject_record_id=_sub(1), job_id=_JOB)
    # quality.gate.failed requires job_id; revision_id is optional
    with pytest.raises(MCPVideoError):
        append_event(project, "quality.gate.failed", edit_project_id=_EP, subject_record_id=_sub(1))
    ok = append_event(project, "quality.gate.failed", edit_project_id=_EP, subject_record_id=_sub(1), job_id=_JOB)
    assert ok.revision_id is None and ok.event_id == 1


def test_fail_closed_on_duplicate_stored_event_id(project):
    _inject(project, 1, subject=_sub(1))
    _inject(project, 1, subject=_sub(2))  # same event_id, distinct record id
    with pytest.raises(MCPVideoError):
        event_poll(project)
    with pytest.raises(MCPVideoError):  # append also recomputes the next id and fails closed
        append_event(project, "quality.gate.failed", edit_project_id=_EP, subject_record_id=_sub(3), job_id=_JOB)


def test_fail_closed_on_non_monotonic_stored_event_id(project):
    _inject(project, 5, subject=_sub(1))
    _inject(project, 3, subject=_sub(2))  # 3 regresses below the prior 5
    with pytest.raises(MCPVideoError):
        event_poll(project)


def test_concurrent_appends_are_serialized_monotonic_and_unique(tmp_path):
    project = open_project(tmp_path / "proj")
    n = 40

    def _one(i):
        return append_event(project, "quality.gate.failed", edit_project_id=_EP, subject_record_id=_sub(i), job_id=_JOB)

    with ThreadPoolExecutor(max_workers=8) as ex:
        appended = list(ex.map(_one, range(n)))
    assert sorted(e.event_id for e in appended) == list(range(1, n + 1))  # no gaps, no duplicates
    assert len({e.record_id for e in appended}) == n
    assert [e.event_id for e in event_poll(project)] == list(range(1, n + 1))


def test_mark_succeeded_appends_exactly_one_ordered_render_completed(tmp_path):
    project = open_project(tmp_path / "proj")
    ep = create_edit_project(project)
    rev = append_revision(project, ep.edit_project_id, operation_ids=("sha256:" + "1" * 64,))
    job = submit_render_job(
        project, edit_project_id=ep.edit_project_id, revision_id=rev.record_id, spec_path=str(_write_spec(project))
    )
    render_jobs.mark_running(project, job.job_id, 4242)

    head = render_jobs.mark_succeeded(
        project,
        job.job_id,
        {"steps": [{"id": "s1", "status": "completed", "output_hash": "sha256:" + "a" * 64}]},
    )

    events = event_poll(project)
    # the revision event precedes the render event: one strictly-ordered pair
    assert [e.event_kind for e in events] == ["revision.created", "render.completed"]
    rnd = events[1]
    assert rnd.job_id == job.job_id and rnd.revision_id == rev.record_id
    assert rnd.subject_record_id == head.record_id  # the event ties to the SUCCEEDED successor

    # a repeat call fails closed on the illegal transition and emits no second event
    with pytest.raises(MCPVideoError):
        render_jobs.mark_succeeded(project, job.job_id, {"steps": []})
    assert [e for e in event_poll(project) if e.event_kind == "render.completed"] == [rnd]
    assert len(read_records(project, "render_job")) == 3  # queued + running + succeeded chain intact


def test_mark_succeeded_rolls_back_event_append_then_retry_emits_one(tmp_path, monkeypatch):
    """A fault on the second (kernel_event) append leaves both record logs at their
    pre-call bytes — no SUCCEEDED head, no render.completed — and a retry then appends
    exactly one succeeded head and one render.completed. Exception-atomic, not
    crash-atomic: a raised second append is fully rolled back, a process crash is not."""
    project = open_project(tmp_path / "proj")
    ep = create_edit_project(project)
    rev = append_revision(project, ep.edit_project_id, operation_ids=("sha256:" + "1" * 64,))
    job = submit_render_job(
        project, edit_project_id=ep.edit_project_id, revision_id=rev.record_id, spec_path=str(_write_spec(project))
    )
    render_jobs.mark_running(project, job.job_id, 4242)

    # pre-call state of both record logs, captured after RUNNING is durable
    render_job_ids_before = [r.record_id for r in read_records(project, "render_job")]
    event_ids_before = [e.event_id for e in event_poll(project)]

    real_append = edit_projects.append_record_locked

    def _fault_on_kernel_event(project, record):
        # the event is the second record committed by the success transaction
        if isinstance(record, KernelEventRecord):
            raise MCPVideoError("injected fault on kernel_event append")
        return real_append(project, record)

    monkeypatch.setattr(edit_projects, "append_record_locked", _fault_on_kernel_event)

    with pytest.raises(MCPVideoError):
        render_jobs.mark_succeeded(
            project,
            job.job_id,
            {"steps": [{"id": "s1", "status": "completed", "output_hash": "sha256:" + "a" * 64}]},
        )

    # rollback: both record logs are restored to their pre-call state
    assert [r.record_id for r in read_records(project, "render_job")] == render_job_ids_before
    assert [e.event_id for e in event_poll(project)] == event_ids_before
    # neither a SUCCEEDED head nor a render.completed event survives
    assert render_jobs.get_render_job(project, job.job_id).status.value == "running"
    assert [e for e in event_poll(project) if e.event_kind == "render.completed"] == []

    # the fault cleared, a retry produces exactly one succeeded head and one event
    monkeypatch.undo()

    head = render_jobs.mark_succeeded(
        project,
        job.job_id,
        {"steps": [{"id": "s1", "status": "completed", "output_hash": "sha256:" + "a" * 64}]},
    )
    completed = [e for e in event_poll(project) if e.event_kind == "render.completed"]
    assert len(completed) == 1
    assert completed[0].subject_record_id == head.record_id  # event ties to the one succeeded head
    assert render_jobs.get_render_job(project, job.job_id).status.value == "succeeded"
    assert len(read_records(project, "render_job")) == 3  # queued + running + one succeeded head
