"""Focused tests for trusted-execution Phase-1 contracts."""

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.trusted_execution import (
    CASManifestRecord,
    EditProjectRecord,
    EditRevisionRecord,
    KernelEventRecord,
    ReceiptLineage,
    RenderJobRecord,
    RenderJobStatus,
    can_transition_job,
)

_SHA, _SHA_B = "sha256:" + "a" * 64, "sha256:" + "b" * 64
_PROJECT, _JOB = "edit_project:" + "c" * 64, "job:" + "d" * 64
_BASE = {"project_id": "project:" + "e" * 64, "created_by": "tool"}


def test_edit_project_and_linear_revision_invariants():
    project = EditProjectRecord(**_BASE, edit_project_id=_PROJECT, revision_number=0)
    first = EditRevisionRecord(**_BASE, edit_project_id=_PROJECT, revision_number=1)
    later = EditRevisionRecord(**_BASE, edit_project_id=_PROJECT, revision_number=2, parent_revision_id=_SHA)
    assert canonical_record_id(project).startswith("sha256:")
    assert first.parent_revision_id is None and later.parent_revision_id == _SHA
    for model, kwargs in (
        (EditProjectRecord, {"edit_project_id": _PROJECT, "revision_number": 0, "head_revision_id": _SHA}),
        (EditRevisionRecord, {"edit_project_id": _PROJECT, "revision_number": 2}),
    ):
        with pytest.raises(ValidationError):
            model(**_BASE, **kwargs)


def test_render_job_lifecycle_is_closed_and_records_are_frozen():
    assert can_transition_job(RenderJobStatus.QUEUED, RenderJobStatus.RUNNING)
    assert can_transition_job(RenderJobStatus.FAILED, RenderJobStatus.QUEUED)
    assert not can_transition_job(RenderJobStatus.SUCCEEDED, RenderJobStatus.RUNNING)
    job = RenderJobRecord(
        **_BASE,
        job_id=_JOB,
        edit_project_id=_PROJECT,
        revision_id=_SHA,
        status=RenderJobStatus.QUEUED,
        workflow_spec_digest=_SHA_B,
    )
    with pytest.raises(ValidationError):
        job.status = RenderJobStatus.RUNNING
    with pytest.raises(ValidationError):
        RenderJobRecord(
            **_BASE,
            job_id=_JOB,
            edit_project_id=_PROJECT,
            revision_id=_SHA,
            status="unknown",
            workflow_spec_digest=_SHA_B,
        )


def test_cas_manifest_location_matches_digest():
    CASManifestRecord(**_BASE, digest=_SHA, byte_size=7, blob_location=f".kinocut/blobs/sha256/{'a' * 64}")
    with pytest.raises(ValidationError):
        CASManifestRecord(**_BASE, digest=_SHA, byte_size=7, blob_location=f".kinocut/blobs/sha256/{'b' * 64}")


def test_receipt_lineage_is_frozen_and_digest_typed():
    lineage = ReceiptLineage(
        edit_project_id=_PROJECT,
        revision_id=_SHA,
        job_id=_JOB,
        source_digests=(_SHA,),
        output_digest=_SHA_B,
        toolchain_fingerprint="ffmpeg:8.1",
    )
    with pytest.raises(ValidationError):
        lineage.job_id = "job:" + "f" * 64
    with pytest.raises(ValidationError):
        ReceiptLineage(**(lineage.model_dump() | {"source_digests": ("bad",)}))


def test_event_contract_allows_only_phase_one_kinds():
    for kind in ("revision.created", "render.completed", "quality.gate.failed"):
        KernelEventRecord(**_BASE, event_id=1, event_kind=kind, edit_project_id=_PROJECT, subject_record_id=_SHA)
    with pytest.raises(ValidationError):
        KernelEventRecord(
            **_BASE, event_id=1, event_kind="render.started", edit_project_id=_PROJECT, subject_record_id=_SHA
        )
