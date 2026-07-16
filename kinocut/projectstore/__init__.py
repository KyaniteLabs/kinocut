"""Content-addressed, append-only, lock-guarded private project store.

The project store is the durable home for canonical AI-video records and their
content-addressed media assets. Its guarantees:

* **Content-addressed** — assets retain their compatible named layout while
  canonical CAS blobs have exactly one immutable path per sha256 digest.
* **Append-only** — records are never edited or deleted; a correction is a new
  record that supersedes an earlier one by ``record_id``.
* **Lock-guarded & atomic** — every mutation holds an exclusive project lock and
  swaps files with :func:`os.replace`, so a failed write can never corrupt the
  prior state.
* **Private** — records carry project-relative paths only; no home path,
  username, or absolute host path is ever stored.

Public surface: :func:`open_project`, :func:`append_record`,
:func:`read_records`, :func:`ingest_asset`, :func:`ingest_blob`,
:func:`resolve_blob`, :func:`rebuild_indexes`, and the :class:`Project` handle.
The internal Phase-1 edit-project repository adds
:func:`create_edit_project`, :func:`get_edit_project`, and
:func:`append_revision`.
"""

from __future__ import annotations

from kinocut.projectstore.cas import ingest_blob, resolve_blob
from kinocut.projectstore.compat import (
    CAS_PRODUCER_KINDS,
    CLOSED_KINDS,
    NormalizedOperation,
    WorkflowSpecSynthesis,
    compile_operations,
    compile_repurpose_slice,
    materialize_workflow_sources,
    synthesize_workflow_spec,
)
from kinocut.projectstore.edit_projects import (
    append_revision,
    create_edit_project,
    get_edit_project,
)
from kinocut.projectstore.events import append_event, event_poll
from kinocut.projectstore.ingest import ingest_asset
from kinocut.projectstore.render_jobs import (
    cancel_render_job,
    get_render_job,
    job_spec_path,
    reconcile_render_jobs,
    render_job_status,
    resume_render_job,
    submit_render_job,
    terminate_render_job,
)
from kinocut.projectstore.render_runner import start_render_job
from kinocut.projectstore.store import (
    Project,
    append_record,
    open_project,
    read_records,
    rebuild_indexes,
)

__all__ = [
    "CAS_PRODUCER_KINDS",
    "CLOSED_KINDS",
    "NormalizedOperation",
    "Project",
    "WorkflowSpecSynthesis",
    "append_event",
    "append_record",
    "append_revision",
    "cancel_render_job",
    "compile_operations",
    "compile_repurpose_slice",
    "create_edit_project",
    "event_poll",
    "get_edit_project",
    "get_render_job",
    "ingest_asset",
    "ingest_blob",
    "job_spec_path",
    "materialize_workflow_sources",
    "open_project",
    "read_records",
    "rebuild_indexes",
    "reconcile_render_jobs",
    "render_job_status",
    "resolve_blob",
    "resume_render_job",
    "start_render_job",
    "submit_render_job",
    "synthesize_workflow_spec",
    "terminate_render_job",
]
