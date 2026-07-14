"""Hostile tests for anonymous verified source handles."""

from __future__ import annotations

import os

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_command


def test_immutable_snapshot_capability_requires_kernel_seals(monkeypatch):
    import kinocut.source_identity as identity

    assert isinstance(identity.immutable_verified_snapshot_available(), bool)
    monkeypatch.setattr(identity, "fcntl", None)
    assert identity.immutable_verified_snapshot_available() is False


def test_verified_snapshot_copy_fails_closed_on_source_race(monkeypatch, tmp_path):
    import kinocut.source_identity as identity

    if not identity.immutable_verified_snapshot_available():
        pytest.skip("immutable verified source snapshots are unavailable")

    source = tmp_path / "source.mp4"
    source.write_bytes(b"verified-source-bytes")
    expected = identity.stream_source_identity(str(source))
    destination = tmp_path / "snapshot.mp4"
    original_fdopen = identity.os.fdopen
    raced = False

    class RacingReader:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def fileno(self):
            return self.wrapped.fileno()

        def read(self, size):
            nonlocal raced
            chunk = self.wrapped.read(size)
            if chunk and not raced:
                raced = True
                source.write_bytes(b"raced-source-bytes")
            return chunk

    def racing_fdopen(fd, mode):
        wrapped = original_fdopen(fd, mode)
        return RacingReader(wrapped) if mode == "rb" else wrapped

    monkeypatch.setattr(identity.os, "fdopen", racing_fdopen)
    monkeypatch.setattr(identity, "DEFAULT_BODY_SWAP_HASH_BUFFER_BYTES", 4)
    with pytest.raises(MCPVideoError, match="changed"):
        identity.copy_verified_snapshot(str(source), destination, expected)

    assert raced is True
    assert not destination.exists()


def test_verified_snapshot_identity_is_bound_to_exact_returned_fd(monkeypatch, tmp_path):
    import kinocut.source_identity as identity

    if not identity.immutable_verified_snapshot_available():
        pytest.skip("immutable verified source snapshots are unavailable")

    source = tmp_path / "source.mp4"
    source.write_bytes(b"declared-source-bytes")
    expected = identity.stream_source_identity(str(source))
    destination = tmp_path / "snapshot.mp4"
    original_open = identity.os.open
    read_opens = 0

    def replace_before_returned_fd_open(path, flags, *args):
        nonlocal read_opens
        if os.fspath(path) == os.fspath(destination) and flags & os.O_ACCMODE == os.O_RDONLY:
            read_opens += 1
            if read_opens == 1:
                destination.write_bytes(b"different-returned-fd-bytes")
        return original_open(path, flags, *args)

    monkeypatch.setattr(identity.os, "open", replace_before_returned_fd_open)
    with pytest.raises(MCPVideoError, match="changed"):
        identity.copy_verified_snapshot(str(source), destination, expected)

    assert read_opens == 1
    assert not destination.exists()


def test_verified_snapshot_fails_closed_without_kernel_seals(monkeypatch, tmp_path):
    import kinocut.source_identity as identity

    source = tmp_path / "source.mp4"
    source.write_bytes(b"verified-source-bytes")
    expected = identity.stream_source_identity(str(source))
    destination = tmp_path / "snapshot.mp4"
    monkeypatch.setattr(identity, "fcntl", None)

    with pytest.raises(MCPVideoError) as excinfo:
        identity.copy_verified_snapshot(str(source), destination, expected)

    assert excinfo.value.code == "source_identity_changed"
    assert not destination.exists()


def test_verified_snapshot_is_kernel_write_sealed(tmp_path):
    import kinocut.source_identity as identity

    if not identity.immutable_verified_snapshot_available():
        pytest.skip("kernel write seals are unavailable")

    fcntl = pytest.importorskip("fcntl")

    source = tmp_path / "source.mp4"
    source.write_bytes(b"sealed-source-bytes")
    expected = identity.stream_source_identity(str(source))
    handle = identity.copy_verified_snapshot(str(source), tmp_path / "snapshot.mp4", expected)
    try:
        seals = fcntl.fcntl(handle.fd, fcntl.F_GET_SEALS)
        assert seals & fcntl.F_SEAL_WRITE
        assert seals & fcntl.F_SEAL_GROW
        assert seals & fcntl.F_SEAL_SHRINK
    finally:
        handle.close()


def test_verified_snapshot_fd_starts_at_zero_and_remains_inheritable(tmp_path):
    import kinocut.source_identity as identity

    if not identity.immutable_verified_snapshot_available():
        pytest.skip("immutable verified source snapshots are unavailable")

    payload = b"anonymous-descriptor-payload"
    source = tmp_path / "source.mp4"
    source.write_bytes(payload)
    expected = identity.stream_source_identity(str(source))
    handle = identity.copy_verified_snapshot(str(source), tmp_path / "snapshot.mp4", expected)
    fd = handle.fd
    try:
        assert os.read(fd, len(payload)) == payload
        os.lseek(fd, 0, os.SEEK_SET)
        result = _run_command(["cat", handle.path], timeout=10, pass_fds=handle.pass_fds)
        assert result.stdout.encode() == payload
        assert handle.identity == expected
    finally:
        handle.close()

    with pytest.raises(OSError):
        os.fstat(fd)
