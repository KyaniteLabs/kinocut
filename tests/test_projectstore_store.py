"""Tests for the append-only, lock-guarded record store (Plan 00 Task 3).

Records are appended to ``.kinocut/records/<kind>.jsonl`` under a project lock
via a temp-file + :func:`os.replace`, so a failed write can never truncate the
prior file. History is append-only: corrections *supersede* by ``record_id``
and the earlier record is never rewritten. Supersession chains that form a
cycle are rejected. Stored records carry project-relative paths only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kinocut.contracts._errors import RECORD_SUPERSESSION_CYCLE
from kinocut.contracts.verdict import ClipVerdict
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_record,
    open_project,
    read_records,
)
from tests.contracts_fixtures import verdict_kwargs


def _verdict(**overrides) -> ClipVerdict:
    return ClipVerdict(**verdict_kwargs(**overrides))


def test_open_project_creates_scaffold(tmp_path):
    proj = open_project(tmp_path / "proj")
    assert proj.root == (tmp_path / "proj").resolve()
    assert (proj.root / ".kinocut" / "records").is_dir()


def test_append_populates_record_id_from_canonical_digest(tmp_path):
    proj = open_project(tmp_path / "proj")
    stored = append_record(proj, _verdict(project_id=proj.project_id, record_id=None))
    assert stored.record_id is not None
    assert stored.record_id.startswith("sha256:")


def test_append_is_atomic_and_supersede_only(tmp_path):
    proj = open_project(tmp_path / "proj")
    v1 = append_record(proj, _verdict(project_id=proj.project_id, record_id=None, reviewer="a"))
    v2 = append_record(proj, _verdict(project_id=proj.project_id, reviewer="b", supersedes=v1.record_id))
    records = read_records(proj, "clip_verdict")
    # History intact and ordered: the earlier record is never rewritten.
    assert [r.record_id for r in records] == [v1.record_id, v2.record_id]
    assert records[1].supersedes == v1.record_id


def test_read_records_returns_typed_models(tmp_path):
    proj = open_project(tmp_path / "proj")
    append_record(proj, _verdict(project_id=proj.project_id, record_id=None))
    records = read_records(proj, "clip_verdict")
    assert len(records) == 1
    assert isinstance(records[0], ClipVerdict)


def test_read_missing_kind_is_empty(tmp_path):
    proj = open_project(tmp_path / "proj")
    assert read_records(proj, "clip_verdict") == []


def test_supersession_cycle_is_rejected(tmp_path):
    # Honestly content-addressed records cannot form a natural supersession
    # cycle, so the guard is defense-in-depth against a tampered/corrupt store.
    # Seed a raw X<->Y cycle on disk, then append a record superseding X: the
    # append-time chain walk must revisit a node and reject the write.
    proj = open_project(tmp_path / "proj")
    x_id = "sha256:" + "1" * 64
    y_id = "sha256:" + "2" * 64
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    lines = [
        json.dumps({"record_id": x_id, "supersedes": y_id, "record_kind": "clip_verdict"}),
        json.dumps({"record_id": y_id, "supersedes": x_id, "record_kind": "clip_verdict"}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(MCPVideoError) as excinfo:
        append_record(proj, _verdict(project_id=proj.project_id, reviewer="c", supersedes=x_id))
    assert excinfo.value.code == RECORD_SUPERSESSION_CYCLE


def test_failed_write_leaves_prior_file_intact(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    v1 = append_record(proj, _verdict(project_id=proj.project_id, record_id=None, reviewer="a"))
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    before = path.read_text(encoding="utf-8")

    import os as _os

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(_os, "replace", _boom)
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id, reviewer="b", supersedes=v1.record_id))
    # Prior file byte-identical; the atomic replace never partially applied.
    assert path.read_text(encoding="utf-8") == before


def test_stored_records_carry_no_home_or_absolute_paths(tmp_path):
    proj = open_project(tmp_path / "proj")
    append_record(proj, _verdict(project_id=proj.project_id, record_id=None))
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    text = path.read_text(encoding="utf-8")
    assert str(Path.home()) not in text
    # Every JSONL line is valid canonical JSON.
    for line in text.splitlines():
        json.loads(line)
