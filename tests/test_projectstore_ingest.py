"""Tests for byte-hash-first idempotent asset ingest (Plan 00 Task 3).

Ingest hashes the *source bytes first*, so a re-ingest of identical content
returns the existing :class:`AssetRecord` and never duplicates the stored file.
The asset is copied into the content-addressed store before any normalization,
and the produced record carries a project-relative ``original_location`` — never
a home path, username, or absolute host path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from kinocut.contracts.asset import AssetRecord, MediaKind
from kinocut.projectstore import ingest_asset, open_project, read_records


def _write_clip(path: Path, payload: bytes = b"\x00\x01clip-bytes\x02\x03") -> Path:
    path.write_bytes(payload)
    return path


def test_ingest_returns_asset_record_with_byte_hash_id(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip01.mp4")
    rec = ingest_asset(proj, src)
    assert isinstance(rec, AssetRecord)
    expected = "sha256:" + hashlib.sha256(src.read_bytes()).hexdigest()
    assert rec.asset_id == expected
    assert rec.byte_size == src.stat().st_size
    assert rec.media_kind == MediaKind.VIDEO


def test_ingest_is_idempotent_by_digest(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip01.mp4")
    a = ingest_asset(proj, src)
    b = ingest_asset(proj, src)
    assert a.asset_id == b.asset_id
    stored = list((proj.root / ".kinocut" / "assets" / "sha256").glob("*/*"))
    assert len(stored) == 1  # content copied exactly once, never duplicated


def test_ingest_copies_bytes_into_content_addressed_store(tmp_path):
    proj = open_project(tmp_path / "proj")
    payload = b"\x09\x08distinct-video-bytes"
    src = _write_clip(tmp_path / "movie.mp4", payload)
    rec = ingest_asset(proj, src)
    digest = rec.asset_id.split(":", 1)[1]
    stored = proj.root / ".kinocut" / "assets" / "sha256" / digest / "movie.mp4"
    assert stored.is_file()
    assert stored.read_bytes() == payload


def test_ingest_original_location_is_project_relative(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip01.mp4")
    rec = ingest_asset(proj, src)
    loc = rec.original_location
    assert not loc.startswith(("/", "~", "\\"))
    assert loc.startswith(".kinocut/assets/sha256/")


def test_ingest_record_has_no_home_or_username(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip01.mp4")
    rec = ingest_asset(proj, src)
    dumped = rec.model_dump_json()
    assert str(Path.home()) not in dumped
    assert str(tmp_path) not in dumped  # no absolute host path leaks into the record


def test_ingest_appends_asset_record_once(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip01.mp4")
    ingest_asset(proj, src)
    ingest_asset(proj, src)  # re-ingest must not append a second canonical record
    records = read_records(proj, "asset_record")
    assert len(records) == 1
    assert isinstance(records[0], AssetRecord)


def test_ingest_infers_media_kind_from_extension(tmp_path):
    proj = open_project(tmp_path / "proj")
    audio = _write_clip(tmp_path / "voice.wav", b"RIFFxxxxWAVE")
    rec = ingest_asset(proj, audio)
    assert rec.media_kind == MediaKind.AUDIO
