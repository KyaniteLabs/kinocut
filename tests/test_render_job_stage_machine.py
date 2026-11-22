"""The render-job stage machine: one named stage set, one gate for every write.

``RenderJobRecord.stage`` used to be free text written in eight places
(``"queued"``, ``"running"``, ``"cancellation_requested"``, ...).  These tests
pin the explicit table in ``kinocut.contracts.trusted_execution``, prove the
projectstore routes every write through it, and drive random walks through the
real append-only store checking the invariants after every step.
"""

from __future__ import annotations

import json
import random

import pytest

from kinocut.contracts import trusted_execution as te
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import (
    STAGE_STATUS,
    STOP_REQUEST_STAGES,
    RenderJobRecord,
    RenderJobStage,
    RenderJobStatus,
    can_transition_job,
    can_transition_stage,
    render_job_stage,
)
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_revision,
    create_edit_project,
    get_render_job,
    open_project,
    render_job_status,
    resume_render_job,
    submit_render_job,
)
from kinocut.projectstore import render_jobs
from kinocut.projectstore.render_control import CANCELLATION_REQUESTED, TERMINATION_REQUESTED
from kinocut.projectstore.store import _project_lock, append_record_locked

S = RenderJobStage

# The intended machine, written out independently of the implementation.
EXPECTED: dict[RenderJobStage, set[RenderJobStage]] = {
    S.QUEUED: {S.RUNNING, S.CANCELLED},
    S.RUNNING: {S.COMPLETED, S.FAILED, S.CANCELLATION_REQUESTED, S.TERMINATION_REQUESTED},
    S.TERMINATION_REQUESTED: {S.TERMINATION_REQUESTED, S.CANCELLATION_REQUESTED, S.FAILED},
    S.CANCELLATION_REQUESTED: {S.CANCELLATION_REQUESTED, S.CANCELLED},
    S.COMPLETED: set(),
    S.FAILED: {S.QUEUED},
    S.CANCELLED: {S.QUEUED},
}

STORED_VALUES = {
    "queued",
    "running",
    "cancellation_requested",
    "termination_requested",
    "completed",
    "failed",
    "cancelled",
}


# --------------------------------------------------------------------------- contract table


def test_stage_values_are_the_stored_strings():
    assert {stage.value for stage in RenderJobStage} == STORED_VALUES
    assert CANCELLATION_REQUESTED == "cancellation_requested"
    assert TERMINATION_REQUESTED == "termination_requested"


def test_every_stage_is_handled_by_every_table():
    stages = set(RenderJobStage)
    assert set(STAGE_STATUS) == stages
    assert set(te._STAGE_TRANSITIONS) == stages
    assert set(EXPECTED) == stages
    assert set(te._DEFAULT_STAGE) == set(RenderJobStatus)
    assert set(STAGE_STATUS.values()) == set(RenderJobStatus)
    for status, stage in te._DEFAULT_STAGE.items():
        assert STAGE_STATUS[stage] is status


@pytest.mark.parametrize("current", list(RenderJobStage))
@pytest.mark.parametrize("target", list(RenderJobStage))
def test_stage_transition_table(current, target):
    assert can_transition_stage(current, target) is (target in EXPECTED[current])


@pytest.mark.parametrize("current", list(RenderJobStage))
def test_stage_moves_agree_with_status_moves(current):
    for target in EXPECTED[current]:
        before, after = STAGE_STATUS[current], STAGE_STATUS[target]
        if before is after:
            assert before is RenderJobStatus.RUNNING  # only RUNNING has inner stages
        else:
            assert can_transition_job(before, after)


def test_stop_request_stages_are_running_stages():
    assert {STAGE_STATUS[stage] for stage in STOP_REQUEST_STAGES} == {RenderJobStatus.RUNNING}


@pytest.mark.parametrize("stage", list(RenderJobStage))
def test_stored_stage_reads_as_itself(stage):
    assert render_job_stage(STAGE_STATUS[stage], stage.value) is stage


@pytest.mark.parametrize(
    ("status", "stored", "expected"),
    [
        (RenderJobStatus.QUEUED, None, S.QUEUED),  # a resumed job before this change
        (RenderJobStatus.RUNNING, None, S.RUNNING),
        (RenderJobStatus.RUNNING, "rendering", S.RUNNING),  # unknown text
        (RenderJobStatus.FAILED, "running", S.FAILED),  # stage of another status
        (RenderJobStatus.SUCCEEDED, None, S.COMPLETED),
        (RenderJobStatus.CANCELLED, "queued", S.CANCELLED),
    ],
)
def test_legacy_stage_values_read_tolerantly(status, stored, expected):
    assert render_job_stage(status, stored) is expected


# --------------------------------------------------------------------------- projectstore


def _project(tmp_path):
    project = open_project(tmp_path / "proj")
    ep = create_edit_project(project)
    rev = append_revision(project, ep.edit_project_id, operation_ids=("sha256:" + "1" * 64,))
    spec = {
        "schema_version": 1,
        "name": "one-stage",
        "sources": {"src1": {"path": "in.mp4"}},
        "outputs": {"out1": {"path": "out.mp4"}},
        "steps": [{"id": "s1", "op": "convert", "inputs": {"src": "@sources.src1"}, "output": "@outputs.out1"}],
    }
    (project.root / "spec.json").write_text(json.dumps(spec))
    return project, ep.edit_project_id, rev.record_id


def _submit(project, ep_id, rev_id):
    return submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path="spec.json")


def test_resumed_job_is_stored_queued_like_a_submitted_job(tmp_path):
    """Bug: submit stored ``stage: "queued"`` but resume stored ``stage: null``."""
    project, ep_id, rev_id = _project(tmp_path)
    job = _submit(project, ep_id, rev_id)
    assert job.stage == "queued"
    render_jobs.mark_running(project, job.job_id, 424242)
    render_jobs.mark_failed(project, job.job_id, "boom", "failed")
    resumed = resume_render_job(project, job.job_id)
    assert resumed.status is RenderJobStatus.QUEUED
    assert resumed.stage == "queued"
    assert render_job_status(project, job.job_id)["stage"] == "queued"


def test_legacy_queued_record_without_stage_still_starts(tmp_path):
    project, ep_id, rev_id = _project(tmp_path)
    job = _submit(project, ep_id, rev_id)
    fields = job.model_dump(mode="json")
    fields.update(record_id=None, stage=None, supersedes=job.record_id)
    legacy = validate_record(RenderJobRecord, fields)
    with _project_lock(project):
        append_record_locked(project, legacy)
    head = get_render_job(project, job.job_id)
    assert head.stage is None
    started = render_jobs.mark_running(project, job.job_id, 424242)
    assert (started.status, started.stage) == (RenderJobStatus.RUNNING, "running")


def test_unknown_running_stage_still_honours_stop_rules(tmp_path):
    project, ep_id, rev_id = _project(tmp_path)
    job = _submit(project, ep_id, rev_id)
    running = render_jobs.mark_running(project, job.job_id, 424242)
    fields = running.model_dump(mode="json")
    fields.update(record_id=None, stage="rendering", supersedes=running.record_id)
    with _project_lock(project):
        append_record_locked(project, validate_record(RenderJobRecord, fields))
    failed = render_jobs.mark_failed(project, job.job_id, "boom", "x")
    assert (failed.status, failed.stage) == (RenderJobStatus.FAILED, "failed")


def test_build_refuses_every_illegal_stage_move(tmp_path):
    project, ep_id, rev_id = _project(tmp_path)
    job = _submit(project, ep_id, rev_id)
    for target in RenderJobStage:
        if target in EXPECTED[S.QUEUED]:
            continue
        with pytest.raises(MCPVideoError, match="illegal render-job transition"):
            render_jobs._build_from(project, job, target)
    assert get_render_job(project, job.job_id).record_id == job.record_id


# --------------------------------------------------------------------------- random walks


def _stop(project, job_id, requested):
    with _project_lock(project):
        return render_jobs._request_stop_locked(project, render_jobs._locked_head(project, job_id), requested)


def _unconfirmed(project, job_id):
    with _project_lock(project):
        head = render_jobs._locked_head(project, job_id)
        if not render_jobs._stop_requested(head):
            raise MCPVideoError("not stopping", error_type="validation_error", code="invalid_record")
        return render_jobs._note_unconfirmed_stop_locked(project, head, "runner_stop_timeout")


def _finish(project, job_id):
    with _project_lock(project):
        head = render_jobs._locked_head(project, job_id)
        if not render_jobs._stop_requested(head):
            raise MCPVideoError("not stopping", error_type="validation_error", code="invalid_record")
        return render_jobs._finish_stop_locked(project, head)


def _cancel_queued(project, job_id):
    with _project_lock(project):
        head = render_jobs._locked_head(project, job_id)
        if head.status is not RenderJobStatus.QUEUED:
            raise MCPVideoError("not queued", error_type="validation_error", code="invalid_record")
        return render_jobs._cancel_locked(project, head, with_progress=False)


ACTIONS = {
    "start": lambda p, j: render_jobs.mark_running(p, j, 424242),
    "succeed": lambda p, j: render_jobs.mark_succeeded(p, j, {"steps": []}),
    "fail": lambda p, j: render_jobs.mark_failed(p, j, "boom", "x"),
    "terminate": lambda p, j: _stop(p, j, S.TERMINATION_REQUESTED),
    "cancel_running": lambda p, j: _stop(p, j, S.CANCELLATION_REQUESTED),
    "cancel_queued": _cancel_queued,
    "unconfirmed": _unconfirmed,
    "finish_stop": _finish,
    "resume": lambda p, j: resume_render_job(p, j),
}


def _model(stage: RenderJobStage, action: str) -> RenderJobStage | None:
    """The expected next stage, or ``None`` when the action must be refused."""
    stopping = stage in STOP_REQUEST_STAGES
    if action == "start":
        return S.RUNNING if stage is S.QUEUED else None
    if action == "succeed":
        return S.COMPLETED if stage is S.RUNNING else None
    if action == "fail":
        if stopping:
            return stage  # the stop controller owns the terminal
        return S.FAILED if stage is S.RUNNING else None
    if action == "terminate":
        return {S.RUNNING: S.TERMINATION_REQUESTED}.get(stage, stage if stopping else None)
    if action == "cancel_running":
        return S.CANCELLATION_REQUESTED if stage is S.RUNNING or stopping else None
    if action == "cancel_queued":
        return S.CANCELLED if stage is S.QUEUED else None
    if action == "unconfirmed":
        return stage if stopping else None
    if action == "finish_stop":
        return {S.TERMINATION_REQUESTED: S.FAILED, S.CANCELLATION_REQUESTED: S.CANCELLED}.get(stage)
    if action == "resume":
        return S.QUEUED if stage in (S.FAILED, S.CANCELLED) else None
    raise AssertionError(action)


def _check_invariants(head: RenderJobRecord, expected: RenderJobStage) -> None:
    stage = render_job_stage(head.status, head.stage)
    assert stage is expected
    assert head.stage == expected.value  # every write names its stage
    assert head.status is STAGE_STATUS[expected]
    if head.status is RenderJobStatus.RUNNING:
        assert head.runner_pid is not None
    else:
        assert head.runner_pid is None
    if expected is S.FAILED:
        assert head.error_code
    if expected in (S.QUEUED, S.RUNNING, S.COMPLETED, S.CANCELLED):
        assert head.error_code is None


@pytest.mark.parametrize("seed", range(12))
def test_random_walk_keeps_stage_status_and_pid_consistent(tmp_path, seed):
    rng = random.Random(seed)
    project, ep_id, rev_id = _project(tmp_path)
    job_id = _submit(project, ep_id, rev_id).job_id
    stage = S.QUEUED
    seen = {stage}
    for _ in range(40):
        legal = [name for name in sorted(ACTIONS) if _model(stage, name) is not None]
        # Mostly legal moves so walks go deep; the rest probe refusals.
        action = rng.choice(legal if rng.random() < 0.7 else sorted(ACTIONS))
        expected = _model(stage, action)
        before = get_render_job(project, job_id)
        if expected is None:
            with pytest.raises(MCPVideoError):
                ACTIONS[action](project, job_id)
            assert get_render_job(project, job_id).record_id == before.record_id
        else:
            ACTIONS[action](project, job_id)
            stage = expected
            seen.add(stage)
        _check_invariants(get_render_job(project, job_id), stage)
        if stage is S.COMPLETED:
            break
    assert len(seen) > 2


def test_scripted_walk_visits_every_stage(tmp_path):
    project, ep_id, rev_id = _project(tmp_path)
    job_id = _submit(project, ep_id, rev_id).job_id
    script = [
        "cancel_queued",
        "resume",
        "start",
        "terminate",
        "unconfirmed",
        "cancel_running",
        "finish_stop",
        "resume",
        "start",
        "terminate",
        "finish_stop",
        "resume",
        "start",
        "fail",
        "resume",
        "start",
        "succeed",
    ]
    stage = S.QUEUED
    seen = {stage}
    for action in script:
        stage = _model(stage, action)
        assert stage is not None, action
        ACTIONS[action](project, job_id)
        _check_invariants(get_render_job(project, job_id), stage)
        seen.add(stage)
    assert seen == set(RenderJobStage)
