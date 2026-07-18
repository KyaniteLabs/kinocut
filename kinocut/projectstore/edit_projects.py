"""Durable edit-project repository with append-only global and per-branch heads.

Revision appends use exception-atomic multi-file rollback. They are not cross-file
crash-atomic; GC therefore treats both global and branch heads as reachability roots.
"""

from __future__ import annotations

import contextlib
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import (
    BranchRecord,
    EditProjectRecord,
    EditRevisionRecord,
    RevisionSourcesRecord,
)
from kinocut.projectstore import layout
from kinocut.projectstore.events import _build_event_locked
from kinocut.projectstore.store import (
    Project,
    _mapped_os_errors,
    _project_lock,
    _with_record_id,
    _write_atomically,
    append_record_locked,
    read_records,
    safe_target,
)

__all__ = [
    "append_revision",
    "checkout",
    "create_edit_project",
    "diff_revisions",
    "fork_revision",
    "get_branch",
    "get_edit_project",
    "list_branches",
    "undo",
]

_EDIT_PROJECT_ID_RE = re.compile(r"^edit_project:[0-9a-f]{64}$")


def _now() -> str:
    """Informational UTC timestamp (excluded from the canonical id)."""
    return datetime.now(UTC).isoformat()


def _require_edit_project_id(value: Any) -> None:
    if not isinstance(value, str) or _EDIT_PROJECT_ID_RE.fullmatch(value) is None:
        raise contract_error("edit_project_id is not a valid identity", INVALID_RECORD)


def _find_edit_project(project: Project, edit_project_id: str) -> EditProjectRecord | None:
    """Return the current linear head: the record no other supersedes (one per chain)."""
    matching = [r for r in read_records(project, "edit_project") if r.edit_project_id == edit_project_id]
    if not matching:
        return None
    superseded = {r.supersedes for r in matching if r.supersedes}
    heads = [r for r in matching if r.record_id not in superseded]
    if len(heads) != 1:
        raise contract_error("edit project has an ambiguous head", INVALID_RECORD)
    return heads[0]


def _restore_bytes(path, prior: bytes | None) -> None:
    """Restore ``path`` to its pre-transaction bytes, or remove it if absent then."""
    if prior is None:
        with _mapped_os_errors(), contextlib.suppress(FileNotFoundError):
            path.unlink()
    else:
        _write_atomically(path, lambda writer: writer.write(prior), binary=True)


def _append_transaction(project: Project, records: list) -> None:
    """Append records with exception-atomic rollback; duplicate target kinds are supported."""
    targets = [safe_target(project, layout.records_relative_path(r.record_kind)) for r in records]
    with _mapped_os_errors():
        snapshots = [(t, (t.read_bytes() if t.exists() else None)) for t in targets]
    written = 0
    try:
        for record in records:
            append_record_locked(project, record)
            written += 1
    except BaseException:
        for index in range(written):
            target, prior = snapshots[index]
            _restore_bytes(target, prior)
        raise


def create_edit_project(
    project: Project,
    *,
    edit_project_id: str | None = None,
    created_by: str = "agent",
) -> EditProjectRecord:
    """Create one durable edit-project identity (revision 0, no head); re-creating returns its head unchanged."""
    if edit_project_id is not None:
        _require_edit_project_id(edit_project_id)
    identity = edit_project_id or f"edit_project:{secrets.token_hex(32)}"
    with _project_lock(project):
        existing = _find_edit_project(project, identity)
        if existing is not None:
            return existing
        record = validate_record(
            EditProjectRecord,
            {
                "edit_project_id": identity,
                "revision_number": 0,
                "head_revision_id": None,
                "project_id": project.project_id,
                "created_by": created_by,
                "created_at": _now(),
            },
        )
        return append_record_locked(project, record)


def get_edit_project(project: Project, edit_project_id: str) -> EditProjectRecord:
    """Return the current linear head for ``edit_project_id``."""
    _require_edit_project_id(edit_project_id)
    head = _find_edit_project(project, edit_project_id)
    if head is None:
        raise contract_error("edit project not found", INVALID_RECORD)
    return head


def _branch_records(project: Project, edit_project_id: str) -> list[BranchRecord]:
    return [record for record in read_records(project, "branch") if record.edit_project_id == edit_project_id]


def _find_branch_record(project: Project, edit_project_id: str, branch_name: str) -> BranchRecord | None:
    matching = [record for record in _branch_records(project, edit_project_id) if record.branch_name == branch_name]
    if not matching:
        return None
    superseded = {record.supersedes for record in matching if record.supersedes}
    heads = [record for record in matching if record.record_id not in superseded]
    if len(heads) != 1:
        raise contract_error("branch has an ambiguous head", INVALID_RECORD)
    return heads[0]


def get_branch(project: Project, edit_project_id: str, branch_name: str = "main") -> BranchRecord:
    """Return a branch head, synthesizing legacy ``main`` without writing records."""
    _require_edit_project_id(edit_project_id)
    branch = _find_branch_record(project, edit_project_id, branch_name)
    if branch is not None:
        return branch
    if branch_name != "main":
        raise contract_error("branch not found", INVALID_RECORD)
    head = get_edit_project(project, edit_project_id)
    return validate_record(
        BranchRecord,
        {
            "edit_project_id": edit_project_id,
            "branch_name": "main",
            "head_revision_id": head.head_revision_id,
            "project_id": project.project_id,
            "created_by": "agent",
        },
    )


def list_branches(project: Project, edit_project_id: str) -> tuple[BranchRecord, ...]:
    names = {record.branch_name for record in _branch_records(project, edit_project_id)}
    names.add("main")
    return tuple(get_branch(project, edit_project_id, name) for name in sorted(names))


def _revision_by_id(project: Project, revision_id: str) -> EditRevisionRecord:
    for revision in read_records(project, "edit_revision"):
        if revision.record_id == revision_id:
            return revision
    raise contract_error("revision not found", INVALID_RECORD)


def fork_revision(
    project: Project,
    edit_project_id: str,
    branch_name: str,
    *,
    revision_id: str | None = None,
    created_by: str = "agent",
) -> BranchRecord:
    """Create a new branch at an existing revision without rewriting history."""
    with _project_lock(project):
        if _find_branch_record(project, edit_project_id, branch_name) is not None or branch_name == "main":
            raise contract_error("branch already exists", INVALID_RECORD)
        main = get_branch(project, edit_project_id)
        base = revision_id or main.head_revision_id
        if base is not None and _revision_by_id(project, base).edit_project_id != edit_project_id:
            raise contract_error("revision belongs to a different edit project", INVALID_RECORD)
        record = validate_record(
            BranchRecord,
            {
                "edit_project_id": edit_project_id,
                "branch_name": branch_name,
                "head_revision_id": base,
                "project_id": project.project_id,
                "created_by": created_by,
                "created_at": _now(),
            },
        )
        if _find_branch_record(project, edit_project_id, "main") is None:
            _append_transaction(project, [main, record])
            return get_branch(project, edit_project_id, branch_name)
        return append_record_locked(project, record)


def checkout(project: Project, edit_project_id: str, branch_name: str = "main") -> EditRevisionRecord | None:
    head = get_branch(project, edit_project_id, branch_name).head_revision_id
    return None if head is None else _revision_by_id(project, head)


def _operations_to_root(project: Project, revision_id: str | None) -> tuple[str, ...]:
    revisions = {record.record_id: record for record in read_records(project, "edit_revision")}
    chain: list[EditRevisionRecord] = []
    seen: set[str] = set()
    while revision_id is not None:
        if revision_id in seen or revision_id not in revisions:
            raise contract_error("revision graph is corrupt", INVALID_RECORD)
        seen.add(revision_id)
        revision = revisions[revision_id]
        chain.append(revision)
        revision_id = revision.parent_revision_id
    operations: list[str] = []
    for revision in reversed(chain):
        operations.extend(revision.operation_ids)
    return tuple(operations)


def diff_revisions(
    project: Project, left_revision_id: str | None, right_revision_id: str | None
) -> dict[str, tuple[str, ...]]:
    left = _operations_to_root(project, left_revision_id)
    right = _operations_to_root(project, right_revision_id)
    left_set = set(left)
    right_set = set(right)
    return {
        "added": tuple(operation for operation in right if operation not in left_set),
        "removed": tuple(operation for operation in left if operation not in right_set),
    }


def append_revision(
    project: Project,
    edit_project_id: str,
    *,
    operation_ids: tuple[str, ...] = (),
    branch_name: str = "main",
    base_revision_id: str | None = None,
    source_digests: tuple[str, ...] | None = None,
    created_by: str = "agent",
) -> EditRevisionRecord:
    """Append an immutable operation delta and advance one branch head."""
    _require_edit_project_id(edit_project_id)
    with _project_lock(project):
        head = _find_edit_project(project, edit_project_id)
        if head is None:
            raise contract_error("edit project not found", INVALID_RECORD)
        branch = get_branch(project, edit_project_id, branch_name)
        if base_revision_id != branch.head_revision_id:
            raise contract_error("supplied base revision does not match the branch head", INVALID_RECORD)
        next_number = head.revision_number + 1
        parent = branch.head_revision_id
        revision = validate_record(
            EditRevisionRecord,
            {
                "edit_project_id": edit_project_id,
                "revision_number": next_number,
                "parent_revision_id": parent,
                "operation_ids": operation_ids,
                "project_id": project.project_id,
                "created_by": created_by,
                "created_at": _now(),
            },
        )
        revision, revision_id = _with_record_id(revision)
        event = _build_event_locked(
            project,
            "revision.created",
            edit_project_id=edit_project_id,
            revision_id=revision_id,
            subject_record_id=revision_id,
            created_by=created_by,
        )
        sources = (
            validate_record(
                RevisionSourcesRecord,
                {
                    "revision_id": revision_id,
                    "source_digests": source_digests,
                    "project_id": project.project_id,
                    "created_by": created_by,
                    "created_at": _now(),
                },
            )
            if source_digests is not None
            else None
        )
        new_head = validate_record(
            EditProjectRecord,
            {
                "edit_project_id": edit_project_id,
                "revision_number": next_number,
                "head_revision_id": revision_id,
                "project_id": project.project_id,
                "created_by": created_by,
                "created_at": _now(),
                "supersedes": head.record_id,
            },
        )
        prior_branch = _find_branch_record(project, edit_project_id, branch_name)
        new_branch = validate_record(
            BranchRecord,
            {
                "edit_project_id": edit_project_id,
                "branch_name": branch_name,
                "head_revision_id": revision_id,
                "project_id": project.project_id,
                "created_by": created_by,
                "created_at": _now(),
                **({"supersedes": prior_branch.record_id} if prior_branch is not None else {}),
            },
        )
        records = [revision, event]
        if sources is not None:
            records.append(sources)
        records.extend((new_head, new_branch))
        _append_transaction(project, records)
        return revision


def undo(
    project: Project,
    edit_project_id: str,
    *,
    compensating_operation_ids: tuple[str, ...],
    branch_name: str = "main",
    base_revision_id: str | None = None,
    created_by: str = "agent",
) -> EditRevisionRecord:
    """Append caller-supplied compensating deltas; existing revisions stay immutable."""
    if not compensating_operation_ids:
        raise contract_error("undo requires at least one compensating operation", INVALID_RECORD)
    return append_revision(
        project,
        edit_project_id,
        operation_ids=compensating_operation_ids,
        branch_name=branch_name,
        base_revision_id=base_revision_id,
        created_by=created_by,
    )
