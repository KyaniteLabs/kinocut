"""Append-only, lock-guarded record store (Plan 00 Task 3).

Records are appended to ``.kinocut/records/<kind>.jsonl`` one canonical JSON
line at a time, under an exclusive project lock, via a securely-created
same-directory temp file (``mkstemp`` → ``fsync`` → :func:`os.replace`). Because
the temp name is unpredictable and the swap is atomic on a POSIX filesystem, a
failed write can never truncate the prior file, and a pre-planted symlink can
never redirect the write outside the store.

History is **append-only**: a correction is a new record that *supersedes* an
earlier one by ``record_id``; the earlier record is never edited or removed.
Supersession is validated (exactly one existing, same-project, not-yet-superseded
target) and must not form a cycle. Every record is re-validated through its
``record_kind``-bound concrete model at the write boundary, so a tampered or
wrong-subclass record cannot be persisted. Every public boundary maps raw
filesystem/JSON errors to a stable, privacy-safe :class:`MCPVideoError`.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts._errors import (
    INVALID_RECORD,
    RECORD_SUPERSESSION_CYCLE,
    contract_error,
)
from kinocut.contracts._paths import location_violation
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.adapter import parse_record_json, validate_record
from kinocut.contracts.asset import AssetRecord
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.editorial import BeatMap, ContinuityPlan
from kinocut.contracts.learning import (
    CostEvent,
    PromptOutcome,
    UsageEvent,
    WorkflowRecipe,
)
from kinocut.contracts.protection import ProtectedElement
from kinocut.contracts.registry import BedRecord, ClipRecord, LineageLink
from kinocut.contracts.review import ApprovalState, KnownLimitation, ReviewDecision
from kinocut.contracts.verdict import ClipVerdict
from kinocut.contracts.trusted_execution import (
    CASManifestRecord,
    EditProjectRecord,
    EditRevisionRecord,
    KernelEventRecord,
    RenderJobRecord,
)
from kinocut.errors import MCPVideoError
from kinocut.projectstore import layout
from kinocut.projectstore._migrations import migrate_raw

# Streaming chunk for copying prior record files during an atomic append.
_COPY_CHUNK = 1 << 20
_PROJECT_ID_RE = re.compile(r"^project:[0-9a-f]{64}$")
_PROJECT_METADATA_FIELDS = frozenset({"schema_version", "project_id"})

# Record fields that carry a filesystem location. The store re-checks these at
# the write boundary — independently of any model validator — so a record
# smuggled past validation (e.g. via ``model_copy``) still cannot persist an
# absolute, traversing, URL, or control-char path.
_PATH_FIELDS = ("original_location", "usage_rights_evidence_ref", "blob_location")

# Every canonical record kind maps to the model that reads it back with full
# strict validation. Adding a record kind means adding one registry entry.
_RECORD_REGISTRY: dict[str, type[RecordBase]] = {
    "generation_acceptance_spec": GenerationAcceptanceSpec,
    "asset_record": AssetRecord,
    "clip_verdict": ClipVerdict,
    "defect_finding": DefectFinding,
    "protected_element": ProtectedElement,
    "review_decision": ReviewDecision,
    "known_limitation": KnownLimitation,
    "approval_state": ApprovalState,
    "prompt_outcome": PromptOutcome,
    "usage_event": UsageEvent,
    "cost_event": CostEvent,
    "workflow_recipe": WorkflowRecipe,
    "clip_record": ClipRecord,
    "bed_record": BedRecord,
    "lineage_link": LineageLink,
    "beat_map": BeatMap,
    "continuity_plan": ContinuityPlan,
    "edit_project": EditProjectRecord,
    "edit_revision": EditRevisionRecord,
    "render_job": RenderJobRecord,
    "cas_manifest": CASManifestRecord,
    "kernel_event": KernelEventRecord,
}


@dataclass(frozen=True)
class Project:
    """A handle to an opened project store, rooted at an absolute directory."""

    root: Path
    project_id: str


def open_project(project_dir: str | Path) -> Project:
    """Open (creating if needed) the private store under ``project_dir``.

    The project directory and the ``.kinocut/`` scaffold — records, assets,
    indexes, and locks subtrees — are created idempotently. The returned
    :class:`Project` carries the *resolved* absolute root so every later path is
    containment-checked against a stable base.
    """

    with _mapped_os_errors():
        root = Path(project_dir).resolve()
        for rel in (
            layout.records_dir(),
            layout.assets_dir(),
            layout.artifacts_dir(),
            layout.blobs_dir(),
            layout.index_dir(),
            layout.lock_dir(),
        ):
            layout.contained_path(root, rel).mkdir(parents=True, exist_ok=True)
    provisional = Project(root=root, project_id="")
    with _project_lock(provisional):
        metadata_path = safe_target(provisional, layout.project_metadata_path())
        if not metadata_path.exists():
            if _has_legacy_store_content(provisional):
                raise contract_error(
                    "initialized legacy store has no durable project identity",
                    INVALID_RECORD,
                )
            payload = _canonical_line({"project_id": f"project:{secrets.token_hex(32)}", "schema_version": 1})
            _atomic_write(metadata_path, payload + "\n")
        project_id = _read_project_id(provisional)
    return Project(root=root, project_id=project_id)


def _has_legacy_store_content(project: Project) -> bool:
    """Return whether identity-less state already contains canonical data."""

    with _mapped_os_errors():
        for relative in (
            layout.records_dir(),
            layout.assets_dir(),
            layout.artifacts_dir(),
            layout.blobs_dir(),
            layout.index_dir(),
        ):
            directory = safe_target(project, relative)
            if directory.exists() and any(directory.iterdir()):
                return True
    return False


def _read_project_id(project: Project) -> str:
    """Strictly read the durable identity without leaking filesystem details."""

    path = safe_target(project, layout.project_metadata_path())
    with _mapped_os_errors():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise contract_error("project identity metadata is malformed", INVALID_RECORD) from exc
    if (
        not isinstance(payload, dict)
        or frozenset(payload) != _PROJECT_METADATA_FIELDS
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("project_id"), str)
        or _PROJECT_ID_RE.fullmatch(payload["project_id"]) is None
    ):
        raise contract_error("project identity metadata is invalid", INVALID_RECORD)
    return payload["project_id"]


def _validate_project_identity(project: Project) -> None:
    """Fail closed if a handle no longer matches its durable store identity."""

    if not project.project_id or _read_project_id(project) != project.project_id:
        raise contract_error("project identity does not match the opened store", INVALID_RECORD)


def safe_target(project: Project, rel: Any) -> Path:
    """Return the literal in-store path for ``rel``, refusing symlink components.

    ``rel`` is always a project-relative ``.kinocut/...`` path (no traversal), so
    ``root / rel`` is inside the store by construction. We then reject the path
    if *any* existing component along it is a symlink — a symlinked store
    directory or file must never be written through (arbitrary-overwrite
    defense), independently of the resolve-based containment check.
    """

    root = project.root
    literal = root / rel
    with _mapped_os_errors():  # an is_symlink (lstat) OSError must not leak a raw path
        current = root
        for part in Path(rel).parts:
            current = current / part
            if current.is_symlink():
                raise contract_error("refusing to use a symlinked store component", INVALID_RECORD)
    return literal


@contextmanager
def _project_lock(project: Project) -> Iterator[None]:
    """Hold an exclusive advisory lock for the whole project during a mutation.

    Lock acquisition (mkdir/open/flock) is mapped to a stable, privacy-safe
    :class:`MCPVideoError`; release (unlock/close) is best-effort so a cleanup
    failure never masks the primary error or leaks a raw ``OSError``.
    """

    with _mapped_os_errors():
        lock_path = layout.contained_path(project.root, layout.lock_dir() / "project.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            os.close(fd)
            raise
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(fd)


def _canonical_line(payload: dict[str, Any]) -> str:
    """Serialize one record payload as a single canonical JSON line."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_raw_records(path: Path) -> list[dict[str, Any]]:
    """Read raw record dicts, mapping any read/parse failure to a stable error.

    Used for cheap, tolerant supersession checks that must run even against a
    partially-corrupt store — but a malformed line or unreadable file surfaces
    as a privacy-safe :class:`MCPVideoError`, never a raw ``JSONDecodeError`` or
    ``OSError``.
    """

    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with _mapped_os_errors(), path.open("r", encoding="utf-8") as handle:
        for line in handle:  # streamed: never loads the whole file at once
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise contract_error("the record store contains malformed JSON", INVALID_RECORD) from exc
            if not isinstance(obj, dict):
                raise contract_error("each record line must be a JSON object", INVALID_RECORD)
            records.append(obj)
    return records


def _reject_supersession_cycle(record_id: str, supersedes: str | None, existing: list[dict[str, Any]]) -> None:
    """Raise ``record_supersession_cycle`` if the new link closes a loop."""

    supersedes_of: dict[str, str | None] = {
        rid: obj.get("supersedes") for obj in existing if isinstance((rid := obj.get("record_id")), str)
    }
    supersedes_of[record_id] = supersedes
    seen: set[str] = set()
    node: str | None = record_id
    while node is not None:
        if node in seen:
            raise contract_error(f"supersession chain forms a cycle at {node}", RECORD_SUPERSESSION_CYCLE)
        seen.add(node)
        node = supersedes_of.get(node)


def _validate_supersedes_integrity(record: RecordBase, existing: list[dict[str, Any]]) -> None:
    """Require exactly one existing, same-project, not-yet-superseded target.

    Guards against dangling (no such target), duplicate (target already
    superseded), cross-kind (target absent from this kind's file), and
    cross-project supersession links.
    """

    target_id = record.supersedes
    if target_id is None:
        return
    targets = [obj for obj in existing if obj.get("record_id") == target_id]
    if len(targets) != 1:
        raise contract_error("supersedes must reference exactly one existing record", INVALID_RECORD)
    if targets[0].get("project_id") != record.project_id:
        raise contract_error("supersedes must target a same-project record", INVALID_RECORD)
    if any(obj.get("supersedes") == target_id for obj in existing):
        raise contract_error("the target record is already superseded", INVALID_RECORD)


def _with_record_id(record: RecordBase) -> tuple[RecordBase, str]:
    """Return the record with its canonical ``record_id`` populated, plus that id.

    Identity is always *recomputed* from content — a supplied ``record_id`` is
    never trusted. If one is present and disagrees with the canonical digest the
    record is rejected; otherwise the recomputed id is used exclusively.
    """

    canonical = canonical_record_id(record)
    if record.record_id is not None and record.record_id != canonical:
        raise contract_error("supplied record_id does not match canonical digest", INVALID_RECORD)
    if record.record_id is None:
        record = record.model_copy(update={"record_id": canonical})
    return record, canonical


def _reject_unsafe_record_paths(record: RecordBase) -> None:
    """Reject a record whose path-bearing fields are not safe, project-relative."""

    for field in _PATH_FIELDS:
        value = getattr(record, field, None)
        if isinstance(value, str):
            reason = location_violation(value)
            if reason is not None:
                raise contract_error(f"{field} {reason}", INVALID_RECORD)


def _revalidate_at_boundary(record: RecordBase, line: str) -> type[RecordBase]:
    """Re-parse the serialized record through its kind-bound concrete model.

    A record reaching the store may have been constructed and then mutated via
    ``model_copy`` (which skips validation) or carry a mismatched
    ``record_kind``. Re-validating the exact serialized bytes through the
    registered model rejects both — a tampered field fails the model's own
    validators, an unknown/wrong kind has no registered model.
    """

    model = _RECORD_REGISTRY.get(record.record_kind)
    if model is None:
        raise contract_error(f"unknown record kind: {record.record_kind!r}", INVALID_RECORD)
    if type(record) is not model:
        # A subclass "lookalike" (same record_kind, extra behaviour) is refused —
        # only the exact registered concrete type may persist.
        raise contract_error(f"record type is not the registered {model.__name__}", INVALID_RECORD)
    parse_record_json(model, line)  # raises a stable MCPVideoError on any mismatch
    return model


def append_record(project: Project, record: RecordBase) -> RecordBase:
    """Append ``record`` to its kind's JSONL under the project lock."""

    with _project_lock(project):
        return append_record_locked(project, record)


def append_record_locked(project: Project, record: RecordBase) -> RecordBase:
    """Append a record assuming the caller already holds the project lock.

    Derives the canonical ``record_id``, re-validates at the write boundary,
    enforces supersession integrity (no cycle, exactly-one same-project target),
    and writes atomically. Used directly by ingest so the digest check, asset
    copy, and record append form one lock transaction without re-entering it.
    """

    _validate_project_identity(project)
    if record.project_id != project.project_id:
        raise contract_error("record belongs to another project store", INVALID_RECORD)
    stored, rid = _with_record_id(record)
    _reject_unsafe_record_paths(stored)
    rel = layout.records_relative_path(stored.record_kind)
    line = _canonical_line(stored.model_dump(mode="json"))
    _revalidate_at_boundary(stored, line)
    path = safe_target(project, rel)
    existing = _read_raw_records(path)
    if any(obj.get("record_id") == rid for obj in existing):
        raise contract_error("a record with this id already exists", INVALID_RECORD)
    _reject_supersession_cycle(rid, stored.supersedes, existing)
    _validate_supersedes_integrity(stored, existing)
    _atomic_append(path, line)
    return stored


def _fsync_dir(directory: Path) -> None:
    """``fsync`` a directory so a rename/creation is durable across a crash."""

    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _mapped_os_errors() -> Iterator[None]:
    """Map any raw filesystem error to a privacy-safe stable contract error.

    A raw ``OSError`` message can embed an absolute host path; the boundary must
    never surface it. ``MCPVideoError`` is re-raised unchanged.
    """

    try:
        yield
    except MCPVideoError:
        raise
    except (OSError, UnicodeError) as exc:
        # UnicodeError covers invalid UTF-8 bytes in a record file; both it and
        # OSError can embed a host path, so neither text ever reaches the caller.
        raise contract_error("a project-store filesystem operation failed", INVALID_RECORD) from exc


def _write_atomically(path: Path, fill: Any, *, binary: bool = False) -> None:
    """Create a secure same-dir temp, fill it as text or bytes, then swap.

    The temp file is created with :func:`tempfile.mkstemp` (unpredictable name,
    ``O_EXCL``, ``0600``) so no pre-planted symlink is ever followed; the content
    is flushed and ``fsync``-ed, then swapped in with an atomic :func:`os.replace`
    followed by a parent-directory ``fsync`` for durability. The write is
    all-or-nothing: the prior file is moved aside first, and if *any* step —
    including the post-replace directory ``fsync`` — fails, the prior bytes are
    restored so a reported failure never leaves a partially-advanced file. Every
    raw OS error is mapped to a privacy-safe :class:`MCPVideoError`.
    """

    with _mapped_os_errors():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        backup: Path | None = None
        try:
            mode = "wb" if binary else "w"
            open_kwargs = {} if binary else {"encoding": "utf-8"}
            with os.fdopen(fd, mode, **open_kwargs) as handle:
                fill(handle)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                backup = path.with_name(f".{path.name}.bak.{os.getpid()}")
                if backup.exists():
                    backup.unlink()
                os.replace(path, backup)  # move prior bytes aside for rollback
            installed = False
            try:
                os.replace(tmp, path)
                installed = True
                _fsync_dir(path.parent)
            except BaseException:
                if backup is not None and backup.exists():
                    os.replace(backup, path)  # restore prior bytes on any failure
                    backup = None
                elif installed:
                    # First create: no prior bytes — remove the just-installed file
                    # so a reported failure never leaves a stray partial record file.
                    with contextlib.suppress(OSError):
                        path.unlink()
                with contextlib.suppress(OSError):
                    _fsync_dir(path.parent)
                raise
        finally:
            with contextlib.suppress(OSError):
                if tmp.exists():
                    tmp.unlink()
            with contextlib.suppress(OSError):
                if backup is not None and backup.exists():
                    backup.unlink()


def _atomic_append(path: Path, line: str) -> None:
    """Append one JSONL ``line`` by streaming the prior file into a new temp copy."""

    def _fill(writer: Any) -> None:
        if path.exists():
            with path.open("r", encoding="utf-8") as reader:
                shutil.copyfileobj(reader, writer, _COPY_CHUNK)
        writer.write(line + "\n")

    _write_atomically(path, _fill)


def _atomic_write(path: Path, content: str) -> None:
    """Atomically (over)write ``path`` with ``content``."""

    _write_atomically(path, lambda writer: writer.write(content))


def read_records(project: Project, record_kind: str) -> list[RecordBase]:
    """Return every record of ``record_kind`` in append order, strictly parsed.

    A missing file yields an empty list. Each JSONL line round-trips through the
    registered model via the public adapter, so unknown fields, malformed JSON,
    or unreadable files surface as a stable :class:`MCPVideoError`.
    """

    _validate_project_identity(project)
    model = _RECORD_REGISTRY.get(record_kind)
    if model is None:
        raise contract_error(f"unknown record kind: {record_kind!r}", INVALID_RECORD)
    path = safe_target(project, layout.records_relative_path(record_kind))
    if not path.exists():
        return []
    records: list[RecordBase] = []
    with _mapped_os_errors(), path.open("r", encoding="utf-8") as handle:
        for line in handle:  # streamed line-by-line, not whole-file
            stripped = line.strip()
            if stripped:
                record = _read_one(model, record_kind, stripped)
                if record.project_id != project.project_id:
                    raise contract_error("stored record belongs to another project", INVALID_RECORD)
                records.append(record)
    return records


def _decode_record_line(line: str) -> dict[str, Any]:
    """Decode one JSONL line to a record dict, mapping malformed input to a stable error."""

    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise contract_error("the record store contains malformed JSON", INVALID_RECORD) from exc
    if not isinstance(obj, dict):
        raise contract_error("each record line must be a JSON object", INVALID_RECORD)
    return obj


def _read_one(model: type[RecordBase], record_kind: str, line: str) -> RecordBase:
    """Decode, migrate on read, then strictly validate one stored record line."""

    raw = _decode_record_line(line)
    migrated = migrate_raw(record_kind, raw)
    return validate_record(model, migrated)


def rebuild_indexes(project: Project) -> None:
    """Delete and rebuild ``.kinocut/indexes/`` purely from canonical records.

    Indexes are disposable derived state regenerated from the append-only record
    files. The index directory is refused if symlinked, and each index file is
    written through the same hardened atomic writer used for records.
    """

    with _project_lock(project):
        index_root = safe_target(project, layout.index_dir())  # refuses a symlinked dir
        _reject_symlinked_index_entries(index_root)
        records_root = safe_target(project, layout.records_dir())
        # Build phase: read and validate every kind first. A failure here (e.g.
        # a corrupt record file) aborts before the existing index set is touched.
        payloads: dict[str, str] = {}
        for record_file in sorted(records_root.glob("*.jsonl")):
            kind = record_file.stem
            if kind not in _RECORD_REGISTRY:
                continue
            ids = [record.record_id for record in read_records(project, kind)]
            payloads[kind] = _canonical_line({"record_kind": kind, "record_ids": ids})
        _commit_index_set(index_root, payloads)


def _reject_symlinked_index_entries(index_root: Path) -> None:
    """Reject a symlinked index root or any symlinked entry inside it."""

    with _mapped_os_errors():
        if index_root.is_symlink():
            raise contract_error("refusing a symlinked index directory", INVALID_RECORD)
        entries = list(index_root.iterdir()) if index_root.exists() else []
        for entry in entries:
            if entry.is_symlink():
                raise contract_error("refusing a symlinked index entry", INVALID_RECORD)


def _commit_index_set(index_root: Path, payloads: dict[str, str]) -> None:
    """Build the whole index set in a staging dir, then install it as a transaction.

    The prior real set is first stashed to a backup, the new set is staged and
    fsync-ed, then installed with a rename + parent fsync. If *any* step —
    including the post-install parent fsync, or an attacker planting a symlink at
    the index root mid-commit — fails, the previous real set is restored
    byte-identical and no staging/backup artifacts are left behind.
    """

    parent = index_root.parent
    backup = index_root.with_name(index_root.name + ".bak")
    staging: Path | None = None
    committed = False
    try:
        with _mapped_os_errors():
            parent.mkdir(parents=True, exist_ok=True)
            _stash_old_index(index_root, backup, parent)
            staging = Path(tempfile.mkdtemp(dir=parent, prefix=".indexes.stage."))
            for kind, payload in payloads.items():
                _atomic_write(staging / f"{kind}.json", payload)
            _fsync_dir(staging)
            _install_index(index_root, staging, parent)
            committed = True
            staging = None  # consumed by the install rename
    finally:
        _finalize_index_commit(index_root, backup, parent, staging, committed)


def _remove_index_path(path: Path) -> None:
    """Remove a path (symlink, file, or directory tree) without following links."""

    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _stash_old_index(index_root: Path, backup: Path, parent: Path) -> None:
    """Move the existing real index set aside so it survives any later failure."""

    _remove_index_path(backup)
    if index_root.is_symlink():
        index_root.unlink()  # a pre-existing symlink is not a real set to preserve
    elif index_root.exists():
        os.rename(index_root, backup)
        _fsync_dir(parent)


def _install_index(index_root: Path, staging: Path, parent: Path) -> None:
    """Install the staged set, refusing a symlink planted at the root mid-commit."""

    if index_root.is_symlink():  # TOCTOU: attacker symlink between stash and install
        index_root.unlink()
        raise contract_error("refusing a symlinked index directory at commit", INVALID_RECORD)
    if index_root.exists():
        _remove_index_path(index_root)
    os.rename(staging, index_root)
    _fsync_dir(parent)


def _finalize_index_commit(index_root: Path, backup: Path, parent: Path, staging: Path | None, committed: bool) -> None:
    """Drop the backup on success; otherwise restore the old real set (best-effort)."""

    if staging is not None and staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    if committed:
        # A post-commit backup-cleanup failure is NOT silently swallowed: it
        # surfaces as a stable MCPVideoError rather than leaving a stray backup
        # while reporting success.
        with _mapped_os_errors():
            _remove_index_path(backup)
        return
    with contextlib.suppress(OSError):  # rollback must never mask the primary error
        _remove_index_path(index_root)
        if backup.exists():
            os.rename(backup, index_root)
            _fsync_dir(parent)
