"""Behavior and fault-injection tests for the immutable CAS blob store."""

from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import ingest_blob, open_project, read_records, resolve_blob


def test_ingest_blob_is_idempotent_by_canonical_digest(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"same canonical bytes")
    project = open_project(tmp_path / "project")
    first = ingest_blob(project, source, media_type="application/octet-stream")
    second = ingest_blob(project, source, media_type="ignored/on-cache-hit")
    assert second == first
    assert first.digest.startswith("sha256:")
    assert len(read_records(project, "cas_manifest")) == 1
    assert resolve_blob(project, first.digest).read_bytes() == source.read_bytes()


def test_invalid_manifest_leaves_no_orphan_blob(tmp_path: Path):
    source, project = tmp_path / "source.bin", open_project(tmp_path / "project")
    source.write_bytes(b"reject before commit")
    with pytest.raises(MCPVideoError):
        ingest_blob(project, source, media_type="")
    assert not any((project.root / ".kinocut/blobs/sha256").iterdir())
    assert read_records(project, "cas_manifest") == []


def test_cas_asset_survives_source_loss_and_project_reopen(tmp_path: Path):
    """Fault injection: the external source disappears between store sessions."""

    project_dir, source = tmp_path / "project", tmp_path / "ephemeral-input.mov"
    payload = b"durable media payload\x00\x01"
    source.write_bytes(payload)
    manifest = ingest_blob(open_project(project_dir), source, media_type="video/quicktime")
    source.unlink()
    reopened = open_project(project_dir)
    assert resolve_blob(reopened, manifest.digest).read_bytes() == payload
    assert read_records(reopened, "cas_manifest") == [manifest]


def test_resolve_blob_fails_closed_after_blob_corruption(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"trusted")
    project = open_project(tmp_path / "project")
    manifest = ingest_blob(project, source)
    resolve_blob(project, manifest.digest).write_bytes(b"tampered")
    with pytest.raises(MCPVideoError, match="integrity"):
        resolve_blob(open_project(project.root), manifest.digest)
