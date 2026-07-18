"""Frozen Phase-1 contracts for Kinocut's trusted execution layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from kinocut.contracts._common import RecordBase, Sha256, ValueObject

EditProjectId = Annotated[str, Field(pattern=r"^edit_project:[0-9a-f]{64}$")]
JobId = Annotated[str, Field(pattern=r"^job:[0-9a-f]{64}$")]


class EditProjectRecord(RecordBase):
    """Durable edit-project identity and current linear revision counter."""

    record_kind: Literal["edit_project"] = "edit_project"
    edit_project_id: EditProjectId
    revision_number: int = Field(ge=0)
    head_revision_id: Sha256 | None = None

    @model_validator(mode="after")
    def _valid_head(self) -> EditProjectRecord:
        if (self.revision_number == 0) != (self.head_revision_id is None):
            raise ValueError("revision zero must have no head; later revisions must have one")
        return self


class BranchRecord(RecordBase):
    """Immutable branch-head snapshot; legacy histories synthesize ``main`` on read."""

    record_kind: Literal["branch"] = "branch"
    edit_project_id: EditProjectId
    branch_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    head_revision_id: Sha256 | None = None


class EditRevisionRecord(RecordBase):
    """One immutable snapshot in an append-only linear edit history."""

    record_kind: Literal["edit_revision"] = "edit_revision"
    edit_project_id: EditProjectId
    revision_number: int = Field(ge=1)
    parent_revision_id: Sha256 | None = None
    operation_ids: tuple[Sha256, ...] = ()

    @model_validator(mode="after")
    def _valid_parent(self) -> EditRevisionRecord:
        if (self.revision_number == 1) != (self.parent_revision_id is None):
            raise ValueError("only the first revision may omit its parent")
        return self


class RevisionSourcesRecord(RecordBase):
    """Source CAS digests used by one revision's opaque operation descriptors."""

    record_kind: Literal["revision_sources"] = "revision_sources"
    revision_id: Sha256
    source_digests: tuple[Sha256, ...] = ()


class RenderJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TRANSITIONS = {
    RenderJobStatus.QUEUED: {RenderJobStatus.RUNNING, RenderJobStatus.CANCELLED},
    RenderJobStatus.RUNNING: {RenderJobStatus.SUCCEEDED, RenderJobStatus.FAILED, RenderJobStatus.CANCELLED},
    RenderJobStatus.SUCCEEDED: set(),
    RenderJobStatus.FAILED: {RenderJobStatus.QUEUED},
    RenderJobStatus.CANCELLED: {RenderJobStatus.QUEUED},
}


def can_transition_job(current: RenderJobStatus, target: RenderJobStatus) -> bool:
    """Return whether an append-only successor may make this lifecycle move."""

    return target in _TRANSITIONS[current]


class RenderJobRecord(RecordBase):
    record_kind: Literal["render_job"] = "render_job"
    job_id: JobId
    edit_project_id: EditProjectId
    revision_id: Sha256
    status: RenderJobStatus
    stage: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_spec_digest: Sha256
    # Phase-1 async-render extensions: optional and backward-compatible. A render-job
    # snapshot carries its frozen workspace-relative spec path, numeric progress, the
    # detached runner pid (liveness/orphan detection), a privacy-safe failure summary,
    # and the ordered output digests of completed stages (progressive artifact metadata
    # reused across resume — the wrapped engine's per-step hashes, never a parallel cursor).
    spec_path: str | None = Field(default=None, max_length=255)
    stage_index: int | None = Field(default=None, ge=0)
    stage_total: int | None = Field(default=None, ge=0)
    runner_pid: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=256)
    completed_artifacts: tuple[Sha256, ...] = ()

    @model_validator(mode="after")
    def _spec_path_is_workspace_relative(self) -> RenderJobRecord:
        path = self.spec_path
        if path is not None:
            if not path or path.startswith("/") or "\x00" in path or "\\" in path:
                raise ValueError("spec_path must be a workspace-relative posix path")
            if any(segment in ("", "..", ".") for segment in path.split("/")):
                raise ValueError("spec_path must not contain traversal or empty segments")
        return self


class CASManifestRecord(RecordBase):
    record_kind: Literal["cas_manifest"] = "cas_manifest"
    digest: Sha256
    byte_size: int = Field(ge=0)
    blob_location: str = Field(pattern=r"^\.kinocut/blobs/sha256/[0-9a-f]{64}$")
    media_type: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _valid_location(self) -> CASManifestRecord:
        if not self.blob_location.endswith(self.digest.removeprefix("sha256:")):
            raise ValueError("blob location must match digest")
        return self


class CASGCReceiptRecord(RecordBase):
    """Append-only receipt for one bounded CAS garbage-collection pass."""

    record_kind: Literal["cas_gc"] = "cas_gc"
    budget_bytes: int = Field(ge=0)
    deleted_digests: tuple[Sha256, ...] = ()
    deleted_bytes: int = Field(ge=0)
    retained_reachable: int = Field(ge=0)


class ReceiptLineage(ValueObject):
    edit_project_id: EditProjectId
    revision_id: Sha256
    job_id: JobId
    source_digests: tuple[Sha256, ...] = Field(min_length=1)
    output_digest: Sha256
    toolchain_fingerprint: str = Field(min_length=1, max_length=256)


class KernelEventRecord(RecordBase):
    record_kind: Literal["kernel_event"] = "kernel_event"
    event_id: int = Field(ge=1)
    event_kind: Literal["revision.created", "render.completed", "quality.gate.failed"]
    edit_project_id: EditProjectId
    revision_id: Sha256 | None = None
    job_id: JobId | None = None
    subject_record_id: Sha256
