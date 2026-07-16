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
"""

from __future__ import annotations

from kinocut.projectstore.cas import ingest_blob, resolve_blob
from kinocut.projectstore.ingest import ingest_asset
from kinocut.projectstore.store import (
    Project,
    append_record,
    open_project,
    read_records,
    rebuild_indexes,
)

__all__ = [
    "Project",
    "append_record",
    "ingest_asset",
    "ingest_blob",
    "open_project",
    "read_records",
    "rebuild_indexes",
    "resolve_blob",
]
