"""Adversarial-review security regressions for the project store (Task 2).

These pin the confirmed defects from the independent adversarial review:

* symlinked store components must never be written through (temp-file/replace
  arbitrary-overwrite defense);
* the write boundary re-validates each record through its ``record_kind``-bound
  concrete model, rejecting tampered or wrong-subclass records;
* concurrent identical ingests collapse to a single ``AssetRecord`` under one
  project-lock transaction;
* supersession requires exactly one existing, same-project, not-yet-superseded
  target (no dangling/duplicate/cross-project/cross-kind links);
* every public boundary maps ``JSONDecodeError``/``FileNotFoundError``/``OSError``
  to a privacy-safe stable :class:`MCPVideoError`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from kinocut.contracts.verdict import ClipVerdict
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_record,
    ingest_asset,
    open_project,
    read_records,
    rebuild_indexes,
)
from tests.contracts_fixtures import verdict_kwargs

_SHA = "sha256:" + "a" * 64


def _verdict(**overrides) -> ClipVerdict:
    return ClipVerdict(**verdict_kwargs(acceptance_spec_id=_SHA, **overrides))


def _write_clip(path: Path, payload: bytes = b"x" * (3 * 1024 * 1024 + 7)) -> Path:
    path.write_bytes(payload)
    return path


# ---- Finding 1: symlink / arbitrary-overwrite defense ---------------------


def test_append_refuses_symlinked_records_directory(tmp_path):
    proj = open_project(tmp_path / "proj")
    records = proj.root / ".kinocut" / "records"
    outside = tmp_path / "outside"
    outside.mkdir()
    records.rmdir()
    records.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id))


def test_append_does_not_write_through_symlinked_target(tmp_path):
    proj = open_project(tmp_path / "proj")
    secret = tmp_path / "secret.txt"
    secret.write_text("original-secret", encoding="utf-8")
    target = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    target.symlink_to(secret)
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id))
    # The outside file was never followed/overwritten.
    assert secret.read_text(encoding="utf-8") == "original-secret"


# ---- Finding 3: write-boundary revalidation -------------------------------


def test_append_rejects_wrong_subclass_record_kind(tmp_path):
    proj = open_project(tmp_path / "proj")
    tampered = _verdict().model_copy(update={"record_kind": "asset_record"})
    with pytest.raises(MCPVideoError):
        append_record(proj, tampered)
    assert read_records(proj, "asset_record") == []


# ---- Finding 4: concurrent ingest is a single transaction -----------------


def test_concurrent_identical_ingest_writes_single_record(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")

    errors: list[Exception] = []

    def _worker() -> None:
        try:
            ingest_asset(proj, src)
        except Exception as exc:  # surface any thread failure to the assertion
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(read_records(proj, "asset_record")) == 1


# ---- Findings 5 & 7: raw errors mapped to stable contract errors -----------


def test_ingest_missing_source_maps_to_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, tmp_path / "does-not-exist.mp4")


def test_append_maps_malformed_existing_json_to_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    path.write_text("{not valid json\n", encoding="utf-8")
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id, supersedes=_SHA))


def test_read_records_maps_invalid_utf8_to_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    path.write_bytes(b"\xff\xfe not utf-8 at all\n")
    with pytest.raises(MCPVideoError):
        read_records(proj, "clip_verdict")


def test_append_maps_invalid_utf8_existing_to_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    path.write_bytes(b"\xff\xfe invalid\n")
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id, supersedes=_SHA))


# ---- Finding 6: supersession integrity ------------------------------------


def test_append_rejects_dangling_supersedes(tmp_path):
    proj = open_project(tmp_path / "proj")
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id, supersedes=_SHA))  # no such target exists


def test_append_rejects_duplicate_supersession(tmp_path):
    proj = open_project(tmp_path / "proj")
    v1 = append_record(proj, _verdict(project_id=proj.project_id, reviewer="a"))
    append_record(proj, _verdict(project_id=proj.project_id, reviewer="b", supersedes=v1.record_id))
    with pytest.raises(MCPVideoError):
        append_record(
            proj, _verdict(project_id=proj.project_id, reviewer="c", supersedes=v1.record_id)
        )  # already superseded


def test_append_rejects_cross_project_supersedes(tmp_path):
    proj = open_project(tmp_path / "proj")
    v1 = append_record(
        proj,
        ClipVerdict(
            **verdict_kwargs(
                acceptance_spec_id=_SHA,
                project_id=proj.project_id,
                reviewer="a",
            )
        ),
    )
    other = ClipVerdict(
        **verdict_kwargs(acceptance_spec_id=_SHA, project_id="proj-b", reviewer="b", supersedes=v1.record_id)
    )
    with pytest.raises(MCPVideoError):
        append_record(proj, other)


# ---- Finding 8: rebuild is symlink-safe and hardened -----------------------


def test_rebuild_indexes_refuses_symlinked_index_dir(tmp_path):
    proj = open_project(tmp_path / "proj")
    ingest_src = _write_clip(tmp_path / "clip.mp4")
    ingest_asset(proj, ingest_src)
    indexes = proj.root / ".kinocut" / "indexes"
    outside = tmp_path / "evil-index"
    outside.mkdir()
    indexes.rmdir()
    indexes.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MCPVideoError):
        rebuild_indexes(proj)


def test_rebuild_indexes_rejects_symlinked_index_entry(tmp_path):
    proj = open_project(tmp_path / "proj")
    append_record(proj, _verdict(project_id=proj.project_id))
    indexes = proj.root / ".kinocut" / "indexes"
    outside = tmp_path / "evil.json"
    outside.write_text("{}", encoding="utf-8")
    (indexes / "clip_verdict.json").symlink_to(outside)
    with pytest.raises(MCPVideoError):
        rebuild_indexes(proj)


def _index_state(indexes: Path) -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in indexes.glob("*.json")}


def _no_index_leftovers(kinocut_dir: Path) -> bool:
    leftovers = list(kinocut_dir.glob(".indexes.stage*")) + list(kinocut_dir.glob("indexes.bak"))
    return not leftovers


def test_rebuild_indexes_refuses_swap_time_symlink(tmp_path, monkeypatch):
    # TOCTOU: attacker swaps indexes/ to a symlink between precheck and swap.
    proj = open_project(tmp_path / "proj")
    append_record(proj, _verdict(project_id=proj.project_id))
    rebuild_indexes(proj)
    kinocut = proj.root / ".kinocut"
    indexes = kinocut / "indexes"
    before = _index_state(indexes)
    outside = tmp_path / "evil"
    outside.mkdir()

    import kinocut.projectstore.store as store_mod

    real_fsync = store_mod._fsync_dir

    def _evil_fsync(directory):
        if directory.name.startswith(".indexes.stage") and not indexes.exists():
            # The real set is already stashed aside; attacker plants a symlink.
            indexes.symlink_to(outside, target_is_directory=True)
        return real_fsync(directory)

    monkeypatch.setattr(store_mod, "_fsync_dir", _evil_fsync)
    with pytest.raises(MCPVideoError):
        rebuild_indexes(proj)
    # Old REAL index set restored byte-identical; no symlink; no .bak/staging leftovers.
    assert not indexes.is_symlink() and indexes.is_dir()
    assert _index_state(indexes) == before
    assert _no_index_leftovers(kinocut)


def test_rebuild_indexes_rolls_back_on_post_swap_fsync_failure(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    append_record(proj, _verdict(project_id=proj.project_id))
    rebuild_indexes(proj)
    kinocut = proj.root / ".kinocut"
    indexes = kinocut / "indexes"
    before = _index_state(indexes)

    import kinocut.projectstore.store as store_mod

    real_fsync = store_mod._fsync_dir
    state = {"failed": False}

    def _flaky_fsync(directory):
        # Fail the parent-dir fsync that runs right AFTER the new set is installed.
        installed_new = (
            not state["failed"]
            and directory == indexes.parent
            and indexes.is_dir()
            and not indexes.is_symlink()
            and _index_state(indexes) != before
        )
        if installed_new:
            state["failed"] = True
            raise OSError("fsync failed: /private/secret")
        return real_fsync(directory)

    monkeypatch.setattr(store_mod, "_fsync_dir", _flaky_fsync)
    # A second append changes the would-be index content so install != before.
    append_record(proj, _verdict(project_id=proj.project_id, reviewer="second"))
    with pytest.raises(MCPVideoError):
        rebuild_indexes(proj)
    # Rolled back to the previous complete set; no leftovers.
    assert _index_state(indexes) == before
    assert _no_index_leftovers(kinocut)


def test_rebuild_indexes_preserves_old_set_on_staging_failure(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    append_record(proj, _verdict(project_id=proj.project_id))
    ingest_asset(proj, _write_clip(tmp_path / "clip.mp4"))
    rebuild_indexes(proj)  # establishes a complete 2-file index set
    indexes = proj.root / ".kinocut" / "indexes"
    before = {p.name: p.read_text(encoding="utf-8") for p in indexes.glob("*.json")}
    assert len(before) == 2

    import kinocut.projectstore.store as store_mod

    real_write = store_mod._atomic_write
    calls = {"n": 0}

    def _flaky(path, content):
        calls["n"] += 1
        if calls["n"] == 2:  # fail after the first staged index is written
            raise OSError("disk full: /private/secret")
        return real_write(path, content)

    monkeypatch.setattr(store_mod, "_atomic_write", _flaky)
    with pytest.raises(MCPVideoError):
        rebuild_indexes(proj)
    # The old complete index set survives byte-identical (transactional rollback).
    after = {p.name: p.read_text(encoding="utf-8") for p in indexes.glob("*.json")}
    assert after == before


def test_rebuild_indexes_writes_ids_from_records(tmp_path):
    proj = open_project(tmp_path / "proj")
    stored = append_record(proj, _verdict(project_id=proj.project_id))
    rebuild_indexes(proj)
    index_file = proj.root / ".kinocut" / "indexes" / "clip_verdict.json"
    data = json.loads(index_file.read_text(encoding="utf-8"))
    assert data["record_ids"] == [stored.record_id]


# ---- Re-review round 2/3: exact type, non-dict lines, dup id, OSError -------


def test_append_rejects_lookalike_subclass(tmp_path):
    # A subclass masquerading as a registered kind must not be persisted.
    class Lookalike(ClipVerdict):
        pass

    proj = open_project(tmp_path / "proj")
    impostor = Lookalike(**verdict_kwargs(acceptance_spec_id=_SHA))
    with pytest.raises(MCPVideoError):
        append_record(proj, impostor)
    assert read_records(proj, "clip_verdict") == []


def test_append_maps_non_dict_json_line_to_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    path.write_text("[]\n", encoding="utf-8")  # valid JSON, but not an object
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id, supersedes=_SHA))


def test_duplicate_record_id_is_rejected(tmp_path):
    proj = open_project(tmp_path / "proj")
    stored = append_record(proj, _verdict(project_id=proj.project_id))
    exact_copy = _verdict().model_copy(update={"record_id": stored.record_id})
    with pytest.raises(MCPVideoError):
        append_record(proj, exact_copy)
    assert len(read_records(proj, "clip_verdict")) == 1


def test_append_rejects_mismatched_supplied_record_id(tmp_path):
    # A regex-valid but wrong supplied record_id must be rejected; identity is
    # always recomputed from content and used exclusively.
    proj = open_project(tmp_path / "proj")
    forged = _verdict().model_copy(update={"record_id": "sha256:" + "9" * 64})
    with pytest.raises(MCPVideoError):
        append_record(proj, forged)
    assert read_records(proj, "clip_verdict") == []


def test_lock_acquisition_failure_maps_to_contract_error(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    import fcntl as _fcntl

    import kinocut.projectstore.store as store_mod

    def _boom(*_a, **_k):
        raise OSError("flock failed: /private/secret/lock")

    monkeypatch.setattr(store_mod.fcntl, "flock", _boom)
    with pytest.raises(MCPVideoError) as excinfo:
        append_record(proj, _verdict(project_id=proj.project_id))
    assert "/private/secret" not in str(excinfo.value)
    _ = _fcntl  # keep import referenced


def test_atomic_append_rolls_back_on_post_replace_fsync_failure(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    v1 = append_record(proj, _verdict(project_id=proj.project_id, reviewer="a"))
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    before = path.read_text(encoding="utf-8")
    assert before.count("\n") == 1

    import kinocut.projectstore.store as store_mod

    real_fsync = store_mod._fsync_dir
    state = {"n": 0}

    def _flaky(directory):
        if directory == path.parent:
            state["n"] += 1
            if state["n"] == 1:  # the durability fsync right after the atomic replace
                raise OSError("fsync failed: /private/secret")
        return real_fsync(directory)

    monkeypatch.setattr(store_mod, "_fsync_dir", _flaky)
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id, reviewer="b", supersedes=v1.record_id))
    # Prior bytes restored; the append did not advance the file; no .bak leftovers.
    assert path.read_text(encoding="utf-8") == before
    assert not list((proj.root / ".kinocut" / "records").glob(".*bak*"))


def test_atomic_first_create_removes_file_on_fsync_failure(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    records = proj.root / ".kinocut" / "records"
    path = records / "clip_verdict.jsonl"
    assert not path.exists()

    import kinocut.projectstore.store as store_mod

    real_fsync = store_mod._fsync_dir
    state = {"failed": False}

    def _flaky(directory):
        if directory == records and not state["failed"]:
            state["failed"] = True
            raise OSError("fsync failed: /private/secret")
        return real_fsync(directory)

    monkeypatch.setattr(store_mod, "_fsync_dir", _flaky)
    with pytest.raises(MCPVideoError):
        append_record(proj, _verdict(project_id=proj.project_id))
    # First-create failure removes the new file; no temp/bak leftovers.
    assert not path.exists()
    assert not list(records.glob(".*"))


def test_rebuild_backup_cleanup_failure_is_not_silent_success(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    append_record(proj, _verdict(project_id=proj.project_id))
    rebuild_indexes(proj)
    append_record(proj, _verdict(project_id=proj.project_id, reviewer="two"))

    import kinocut.projectstore.store as store_mod

    real_remove = store_mod._remove_index_path

    def _flaky_remove(path):
        if path.name == "indexes.bak" and path.exists():  # only the real post-commit cleanup
            raise OSError("cleanup failed: /private/secret")
        return real_remove(path)

    monkeypatch.setattr(store_mod, "_remove_index_path", _flaky_remove)
    with pytest.raises(MCPVideoError):
        rebuild_indexes(proj)  # backup cleanup failure must surface, not be swallowed


def test_symlink_check_oserror_maps_to_contract_error(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")

    import kinocut.projectstore.store as store_mod

    def _boom(self):
        raise OSError("lstat failed: /private/secret")

    monkeypatch.setattr(store_mod.Path, "is_symlink", _boom)
    with pytest.raises(MCPVideoError) as excinfo:
        append_record(proj, _verdict(project_id=proj.project_id))
    assert "/private/secret" not in str(excinfo.value)


def test_append_unserializable_field_maps_to_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    tampered = _verdict().model_copy(update={"reviewer": object()})  # not JSON serializable
    with pytest.raises(MCPVideoError):
        append_record(proj, tampered)
    assert read_records(proj, "clip_verdict") == []


def test_ingest_lone_surrogate_path_maps_to_contract_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, str(tmp_path / "\ud800bad.mp4"))


def test_open_project_lone_surrogate_maps_to_contract_error(tmp_path):
    with pytest.raises(MCPVideoError):
        open_project(str(tmp_path / "\ud800proj"))


def test_open_project_mkdir_failure_maps_to_contract_error(tmp_path, monkeypatch):
    import kinocut.projectstore.store as store_mod

    original = store_mod.Path.mkdir

    def _boom(self, *a, **k):
        raise OSError("mkdir failed: /private/secret/proj")

    monkeypatch.setattr(store_mod.Path, "mkdir", _boom)
    with pytest.raises(MCPVideoError) as excinfo:
        open_project(tmp_path / "proj")
    assert "/private/secret" not in str(excinfo.value)
    monkeypatch.setattr(store_mod.Path, "mkdir", original)


def test_atomic_write_oserror_maps_to_contract_error(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    v1 = append_record(proj, _verdict(project_id=proj.project_id, reviewer="a"))
    path = proj.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    before = path.read_text(encoding="utf-8")

    import os as _os

    def _boom(*_a, **_k):
        raise OSError("disk full: /private/secret/path")

    monkeypatch.setattr(_os, "replace", _boom)
    with pytest.raises(MCPVideoError) as excinfo:
        append_record(proj, _verdict(project_id=proj.project_id, reviewer="b", supersedes=v1.record_id))
    # Raw OSError text (which can embed private paths) never surfaces.
    assert "/private/secret/path" not in str(excinfo.value)
    assert path.read_text(encoding="utf-8") == before
