"""Explicit reader migrations for the project store (Plan 00 Task 4).

Documented older records migrate up to the current model *only on read*; current
writes stay strict (unknown fields are rejected even on the read path); unknown
older versions and unknown kinds fail closed via the stable adapter error codes;
and a migration never mutates its input dict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kinocut.contracts._errors import INVALID_RECORD, UNKNOWN_RECORD_FIELD
from kinocut.contracts.verdict import ClipVerdict
from kinocut.errors import MCPVideoError
from kinocut.projectstore import _migrations, append_record, open_project, read_records
from tests.contracts_fixtures import verdict_kwargs

_SHA = "sha256:" + "a" * 64


def _verdict(**overrides) -> ClipVerdict:
    return ClipVerdict(**verdict_kwargs(acceptance_spec_id=_SHA, **overrides))


def _write_lines(path: Path, dicts: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(d) for d in dicts) + "\n", encoding="utf-8")


def _current_verdict_dict(**overrides) -> dict:
    data = {
        "schema_version": 1,
        "record_kind": "clip_verdict",
        "project_id": "proj",
        "created_by": "human",
        "asset_hash": _SHA,
        "disposition": "approved",
        "acceptance_spec_id": _SHA,
        "reviewer": "editor",
        "rationale": "ok",
    }
    data.update(overrides)
    return data


def _legacy_v0_dict(project_id: str = "proj") -> dict:
    # A hypothetical v0 record that named the field ``editorial_disposition``.
    return {
        "schema_version": 0,
        "record_kind": "clip_verdict",
        "project_id": project_id,
        "created_by": "human",
        "asset_hash": _SHA,
        "editorial_disposition": "approved",
        "acceptance_spec_id": _SHA,
        "reviewer": "editor",
        "rationale": "ok",
    }


def _v0_to_v1(raw: dict) -> dict:
    out = dict(raw)
    out["schema_version"] = 1
    out["disposition"] = out.pop("editorial_disposition")
    return out


def test_current_version_records_read_without_migration(tmp_path):
    proj = open_project(tmp_path / "proj")
    stored = append_record(proj, _verdict(project_id=proj.project_id))
    got = read_records(proj, "clip_verdict")
    assert [r.record_id for r in got] == [stored.record_id]


def test_documented_old_record_migrates_on_read(tmp_path, monkeypatch):
    monkeypatch.setitem(_migrations.MIGRATIONS, ("clip_verdict", 0), _v0_to_v1)
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    _write_lines(path, [_legacy_v0_dict(proj.project_id)])
    got = read_records(proj, "clip_verdict")
    assert len(got) == 1
    assert got[0].disposition.value == "approved"
    assert got[0].schema_version == 1


def test_migrate_raw_does_not_mutate_input(monkeypatch):
    monkeypatch.setitem(_migrations.MIGRATIONS, ("clip_verdict", 0), _v0_to_v1)
    raw = _legacy_v0_dict()
    original = dict(raw)
    migrated = _migrations.migrate_raw("clip_verdict", raw)
    assert raw == original  # caller's dict untouched
    assert migrated["schema_version"] == 1
    assert "editorial_disposition" not in migrated


def test_migrate_raw_deepcopies_nested_input(monkeypatch):
    import copy

    def _mutating(raw: dict) -> dict:
        raw["nested"]["items"].append("MUTATED")  # mutate a NESTED structure
        out = _v0_to_v1(raw)
        return out

    monkeypatch.setitem(_migrations.MIGRATIONS, ("clip_verdict", 0), _mutating)
    raw = _legacy_v0_dict()
    raw["nested"] = {"items": ["orig"]}
    baseline = copy.deepcopy(raw)
    _migrations.migrate_raw("clip_verdict", raw)
    assert raw == baseline  # caller's nested structure is untouched


def test_migrator_returning_non_dict_maps_to_contract_error(monkeypatch):
    monkeypatch.setitem(_migrations.MIGRATIONS, ("clip_verdict", 0), lambda raw: None)
    with pytest.raises(MCPVideoError) as excinfo:
        _migrations.migrate_raw("clip_verdict", _legacy_v0_dict())
    assert excinfo.value.code == INVALID_RECORD


def test_migrator_raising_is_mapped_and_logged_without_leak(monkeypatch, caplog):
    def _boom(raw: dict) -> dict:
        raise ValueError("secret path /private/secret/x")

    monkeypatch.setitem(_migrations.MIGRATIONS, ("clip_verdict", 0), _boom)
    with (
        caplog.at_level("WARNING", logger="kinocut.projectstore._migrations"),
        pytest.raises(MCPVideoError) as excinfo,
    ):
        _migrations.migrate_raw("clip_verdict", _legacy_v0_dict())
    assert excinfo.value.code == INVALID_RECORD
    assert "/private/secret" not in str(excinfo.value)
    # A warning was logged with the exception TYPE only — no raw text/path.
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "ValueError" in logged
    assert "/private/secret" not in logged


def test_unknown_old_version_fails_closed(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    _write_lines(path, [_legacy_v0_dict()])  # v0 with NO registered migration
    with pytest.raises(MCPVideoError) as excinfo:
        read_records(proj, "clip_verdict")
    assert excinfo.value.code == INVALID_RECORD


def test_future_version_fails_closed(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    _write_lines(path, [_current_verdict_dict(schema_version=2)])
    with pytest.raises(MCPVideoError):
        read_records(proj, "clip_verdict")


def test_current_read_still_rejects_unknown_fields(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    _write_lines(path, [_current_verdict_dict(surprise=True)])
    with pytest.raises(MCPVideoError) as excinfo:
        read_records(proj, "clip_verdict")
    assert excinfo.value.code == UNKNOWN_RECORD_FIELD


def test_unknown_kind_fails_closed(tmp_path):
    proj = open_project(tmp_path / "proj")
    with pytest.raises(MCPVideoError) as excinfo:
        read_records(proj, "not_a_real_kind")
    assert excinfo.value.code == INVALID_RECORD
