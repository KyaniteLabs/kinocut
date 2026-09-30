"""CAS availability across collection, repair and interrupted commits."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import subprocess
import sys
import threading

import pytest

from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import CASBlobLifecycleRecord
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_revision,
    create_edit_project,
    ingest_blob,
    open_project,
    read_records,
    resolve_blob,
    store,
)
from kinocut.projectstore.cas_gc import collect_cas_garbage


def _setup(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"trusted immutable bytes")
    project = open_project(tmp_path / "project")
    manifest = ingest_blob(project, source, media_type="application/octet-stream")
    return project, source, manifest


def test_repeated_gc_restoration_retains_manifest_and_all_generations(tmp_path):
    project, source, manifest = _setup(tmp_path)
    original_bytes = (project.root / ".kinocut/records/cas_manifest.jsonl").read_bytes()
    receipts = []
    for _ in range(3):
        receipt = collect_cas_garbage(project, budget_bytes=0)
        receipts.append(receipt)
        assert receipt.deleted_digests == (manifest.digest,)
        with pytest.raises(MCPVideoError, match="garbage collection"):
            resolve_blob(project, manifest.digest)
        assert ingest_blob(project, source, media_type="ignored/on-restoration") == manifest
        project = open_project(project.root)
        assert resolve_blob(project, manifest.digest).read_bytes() == source.read_bytes()
    assert len({receipt.record_id for receipt in receipts}) == 3
    assert read_records(project, "cas_gc") == receipts
    assert (project.root / ".kinocut/records/cas_manifest.jsonl").read_bytes() == original_bytes
    states = read_records(project, "cas_blob_lifecycle")
    assert [r.state for r in states] == ["restoring", "available"] * 3
    for index, receipt in enumerate(receipts):
        assert states[index * 2 + 1].after_gc_receipt_id == receipt.record_id
    assert collect_cas_garbage(project, budget_bytes=10**6) is None


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_ingest_repairs_damaged_live_blob_with_recorded_completion(tmp_path, damage):
    project, source, manifest = _setup(tmp_path)
    target = resolve_blob(project, manifest.digest)
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"corrupt")
    with pytest.raises(MCPVideoError):
        resolve_blob(project, manifest.digest)
    assert ingest_blob(project, source) == manifest
    assert resolve_blob(open_project(project.root), manifest.digest).read_bytes() == source.read_bytes()
    states = read_records(project, "cas_blob_lifecycle")
    assert [r.state for r in states] == ["restoring", "available"]
    assert all(r.after_gc_receipt_id is None for r in states)
    assert ingest_blob(project, source) == manifest
    assert read_records(project, "cas_blob_lifecycle") == states


@pytest.mark.parametrize("damage", ["gc", "missing", "corrupt"])
def test_failed_completion_restores_prior_bytes_and_remains_retryable(tmp_path, monkeypatch, damage):
    project, source, manifest = _setup(tmp_path)
    target = resolve_blob(project, manifest.digest)
    if damage == "gc":
        collect_cas_garbage(project, budget_bytes=0)
    elif damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"prior corrupted bytes")
    prior = target.read_bytes() if target.exists() else None
    original_append = store.append_record_locked

    def fail_completion(project, record):
        if record.record_kind == "cas_blob_lifecycle" and record.state == "available":
            raise MCPVideoError("injected completion failure", error_type="processing_error")
        return original_append(project, record)

    monkeypatch.setattr(store, "append_record_locked", fail_completion)
    with pytest.raises(MCPVideoError, match="injected"):
        ingest_blob(project, source)
    assert (target.read_bytes() if target.exists() else None) == prior
    assert read_records(project, "cas_blob_lifecycle")[-1].state == "restoring"
    with pytest.raises(MCPVideoError, match="interrupted restoration"):
        resolve_blob(open_project(project.root), manifest.digest)
    monkeypatch.setattr(store, "append_record_locked", original_append)
    assert ingest_blob(project, source) == manifest
    assert resolve_blob(project, manifest.digest).read_bytes() == source.read_bytes()


def test_failed_intent_does_not_install_or_change_prior_state(tmp_path, monkeypatch):
    project, source, manifest = _setup(tmp_path)
    collect_cas_garbage(project, budget_bytes=0)
    original_append = store.append_record_locked

    def fail_intent(project, record):
        if record.record_kind == "cas_blob_lifecycle":
            raise MCPVideoError("injected intent failure", error_type="processing_error")
        return original_append(project, record)

    monkeypatch.setattr(store, "append_record_locked", fail_intent)
    with pytest.raises(MCPVideoError, match="intent failure"):
        ingest_blob(project, source)
    assert not (project.root / manifest.blob_location).exists()
    assert read_records(project, "cas_blob_lifecycle") == []
    assert len(read_records(project, "cas_gc")) == 1


def test_failed_install_directory_fsync_rolls_back_corruption_and_can_retry(tmp_path, monkeypatch):
    project, source, manifest = _setup(tmp_path)
    target = resolve_blob(project, manifest.digest)
    target.write_bytes(b"prior corruption")
    original_fsync = store._fsync_dir
    failed = False

    def fail_installed_directory(directory):
        nonlocal failed
        if directory == target.parent and target.exists() and target.read_bytes() == source.read_bytes() and not failed:
            failed = True
            raise OSError("injected directory fsync failure")
        return original_fsync(directory)

    monkeypatch.setattr(store, "_fsync_dir", fail_installed_directory)
    with pytest.raises(MCPVideoError):
        ingest_blob(project, source)
    assert failed and target.read_bytes() == b"prior corruption"
    assert read_records(project, "cas_blob_lifecycle")[-1].state == "restoring"
    assert not list(target.parent.glob(".cas-repair.*"))
    assert ingest_blob(project, source) == manifest
    assert resolve_blob(project, manifest.digest).read_bytes() == source.read_bytes()


def test_repair_refuses_non_regular_blob_target(tmp_path):
    project, source, manifest = _setup(tmp_path)
    target = resolve_blob(project, manifest.digest)
    target.unlink()
    target.mkdir()
    with pytest.raises(MCPVideoError, match="non-regular"):
        ingest_blob(project, source)
    assert target.is_dir()
    assert read_records(project, "cas_blob_lifecycle") == []


@pytest.mark.parametrize("damage", ["gc", "corrupt"])
@pytest.mark.parametrize("recovery", ["retry", "gc"])
def test_process_death_after_install_does_not_publish_unrecorded_restoration(tmp_path, damage, recovery):
    project, source, manifest = _setup(tmp_path)
    if damage == "gc":
        collect_cas_garbage(project, budget_bytes=0)
    else:
        resolve_blob(project, manifest.digest).write_bytes(b"corrupted")
    script = """
import os, sys
from kinocut.projectstore import ingest_blob, open_project, store
original = store.append_record_locked
def stop_before_completion(project, record):
    if record.record_kind == 'cas_blob_lifecycle' and record.state == 'available':
        os._exit(71)
    return original(project, record)
store.append_record_locked = stop_before_completion
ingest_blob(open_project(sys.argv[1]), sys.argv[2])
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(project.root), str(source)],
        capture_output=True,
        timeout=20,
    )
    assert completed.returncode == 71, completed.stderr
    assert (project.root / manifest.blob_location).read_bytes() == source.read_bytes()
    reopened = open_project(project.root)
    with pytest.raises(MCPVideoError, match="interrupted restoration"):
        resolve_blob(reopened, manifest.digest)
    if recovery == "gc":
        receipt = collect_cas_garbage(reopened, budget_bytes=0)
        assert receipt is not None and receipt.deleted_digests == (manifest.digest,)
        assert receipt.deleted_bytes == len(source.read_bytes()) + (len(b"corrupted") if damage == "corrupt" else 0)
        assert not (project.root / manifest.blob_location).exists()
        assert not list((project.root / manifest.blob_location).parent.glob(".cas-repair.*"))
    assert ingest_blob(reopened, source) == manifest
    assert resolve_blob(reopened, manifest.digest).read_bytes() == source.read_bytes()
    assert not list((project.root / manifest.blob_location).parent.glob(".cas-repair.*"))


def test_gc_accounts_for_backup_after_process_death_before_install(tmp_path):
    project, source, manifest = _setup(tmp_path)
    resolve_blob(project, manifest.digest).write_bytes(b"previous corruption")
    script = """
import os, sys
from pathlib import Path
from kinocut.projectstore import ingest_blob, open_project
original = os.replace
def stop_before_install(source, destination):
    if Path(source).name.startswith('.ingest.'):
        os._exit(72)
    return original(source, destination)
os.replace = stop_before_install
ingest_blob(open_project(sys.argv[1]), sys.argv[2])
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(project.root), str(source)],
        capture_output=True,
        timeout=20,
    )
    assert completed.returncode == 72, completed.stderr
    target = project.root / manifest.blob_location
    assert not target.exists()
    assert len(list(target.parent.glob(".cas-repair.*"))) == 1
    receipt = collect_cas_garbage(open_project(project.root), budget_bytes=0)
    assert receipt is not None and receipt.deleted_bytes == len(b"previous corruption")
    assert not list(target.parent.glob(".cas-repair.*"))
    assert ingest_blob(project, source) == manifest
    assert resolve_blob(project, manifest.digest).read_bytes() == source.read_bytes()


def test_concurrent_ingest_and_gc_serialize_then_allow_repair(tmp_path):
    project, source, manifest = _setup(tmp_path)
    collect_cas_garbage(project, budget_bytes=0)
    start = threading.Barrier(3)

    def restore():
        start.wait(timeout=5)
        return ingest_blob(project, source)

    def collect():
        start.wait(timeout=5)
        return collect_cas_garbage(project, budget_bytes=0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        ingest_result, gc_result = pool.submit(restore), pool.submit(collect)
        start.wait(timeout=5)
        assert ingest_result.result(timeout=10) == manifest
        gc_result.result(timeout=10)
    assert ingest_blob(project, source) == manifest
    assert resolve_blob(project, manifest.digest).read_bytes() == source.read_bytes()
    assert len(read_records(project, "cas_manifest")) == 1


def test_reachable_pending_repair_is_never_collected(tmp_path, monkeypatch):
    project, source, manifest = _setup(tmp_path)
    edit_project = create_edit_project(project)
    append_revision(project, edit_project.edit_project_id, operation_ids=(manifest.digest,))
    target = resolve_blob(project, manifest.digest)
    target.write_bytes(b"corruption")
    original_append = store.append_record_locked

    def fail_completion(project, record):
        if record.record_kind == "cas_blob_lifecycle" and record.state == "available":
            raise MCPVideoError("injected completion failure", error_type="processing_error")
        return original_append(project, record)

    monkeypatch.setattr(store, "append_record_locked", fail_completion)
    with pytest.raises(MCPVideoError):
        ingest_blob(project, source)
    assert read_records(project, "cas_blob_lifecycle")[-1].state == "restoring"
    assert collect_cas_garbage(project, budget_bytes=0) is None
    assert target.read_bytes() == b"corruption"


def test_resolver_waits_for_coherent_restore_completion(tmp_path, monkeypatch):
    project, source, manifest = _setup(tmp_path)
    collect_cas_garbage(project, budget_bytes=0)
    installed, reader_started, release = threading.Event(), threading.Event(), threading.Event()
    original_append = store.append_record_locked

    def pause_completion(project, record):
        if record.record_kind == "cas_blob_lifecycle" and record.state == "available":
            installed.set()
            assert release.wait(timeout=5)
        return original_append(project, record)

    def read():
        reader_started.set()
        return resolve_blob(project, manifest.digest)

    monkeypatch.setattr(store, "append_record_locked", pause_completion)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(ingest_blob, project, source)
        assert installed.wait(timeout=5)
        reader = pool.submit(read)
        assert reader_started.wait(timeout=5)
        try:
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.1)
        finally:
            release.set()
        assert writer.result(timeout=5) == manifest
        assert reader.result(timeout=5).read_bytes() == source.read_bytes()


def test_committed_repair_with_interrupted_cleanup_is_cleaned_by_idempotent_ingest(tmp_path):
    project, source, manifest = _setup(tmp_path)
    resolve_blob(project, manifest.digest).write_bytes(b"corrupted")
    script = """
import os, sys
from kinocut.projectstore import ingest_blob, open_project, store
original = store.append_record_locked
def stop_after_completion(project, record):
    result = original(project, record)
    if record.record_kind == 'cas_blob_lifecycle' and record.state == 'available':
        os._exit(73)
    return result
store.append_record_locked = stop_after_completion
ingest_blob(open_project(sys.argv[1]), sys.argv[2])
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(project.root), str(source)],
        capture_output=True,
        timeout=20,
    )
    assert completed.returncode == 73, completed.stderr
    target = resolve_blob(project, manifest.digest)
    assert len(list(target.parent.glob(".cas-repair.*"))) == 1
    assert ingest_blob(project, source) == manifest
    assert not list(target.parent.glob(".cas-repair.*"))
    assert [r.state for r in read_records(project, "cas_blob_lifecycle")] == ["restoring", "available"]


def test_lifecycle_completion_without_matching_intent_fails_closed(tmp_path):
    project, _source, manifest = _setup(tmp_path)
    record = validate_record(
        CASBlobLifecycleRecord,
        {
            "project_id": project.project_id,
            "created_by": "tool",
            "digest": manifest.digest,
            "manifest_record_id": manifest.record_id,
            "state": "available",
        },
    )
    store.append_record(project, record)
    with pytest.raises(MCPVideoError, match="matching repair intent"):
        resolve_blob(project, manifest.digest)


def test_collection_can_reclaim_bytes_reappearing_after_legacy_tombstone(tmp_path):
    project, source, manifest = _setup(tmp_path)
    first = collect_cas_garbage(project, budget_bytes=0)
    target = project.root / manifest.blob_location
    target.write_bytes(source.read_bytes())
    with pytest.raises(MCPVideoError, match="garbage collection"):
        resolve_blob(project, manifest.digest)
    second = collect_cas_garbage(project, budget_bytes=0)
    assert second is not None and second.record_id != first.record_id
    assert first.record_id in second.source_record_ids
    assert second.deleted_bytes == len(source.read_bytes())
    assert not target.exists()
    assert ingest_blob(project, source) == manifest
    assert resolve_blob(project, manifest.digest).read_bytes() == source.read_bytes()


def test_cross_digest_backup_ownership_fails_closed_before_cleanup(tmp_path):
    project, source_a, manifest_a = _setup(tmp_path)
    source_b = tmp_path / "second.bin"
    source_b.write_bytes(b"second immutable blob")
    manifest_b = ingest_blob(project, source_b)
    backup_location = ".kinocut/blobs/sha256/.cas-repair." + "a" * 32
    backup = project.root / backup_location
    backup.write_bytes(b"second blob prior bytes")
    for manifest in (manifest_b, manifest_a):
        store.append_record(
            project,
            validate_record(
                CASBlobLifecycleRecord,
                {
                    "project_id": project.project_id,
                    "created_by": "tool",
                    "digest": manifest.digest,
                    "manifest_record_id": manifest.record_id,
                    "state": "restoring",
                    "backup_location": backup_location,
                },
            ),
        )
    prior = backup.read_bytes()
    with pytest.raises(MCPVideoError, match="multiple digests"):
        ingest_blob(project, source_a)
    assert backup.read_bytes() == prior
    with pytest.raises(MCPVideoError, match="multiple digests"):
        collect_cas_garbage(project, budget_bytes=0)
    assert backup.read_bytes() == prior
