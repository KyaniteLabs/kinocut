"""Shared internal source-identity and verified-snapshot primitives."""

from __future__ import annotations

import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - unavailable on Windows
    fcntl = None

from kinocut.defaults import DEFAULT_BODY_SWAP_HASH_BUFFER_BYTES
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path


@dataclass(frozen=True)
class SourceIdentity:
    """One content identity bound to its canonical byte count."""

    asset_id: str
    byte_size: int


@dataclass
class VerifiedSource:
    """Held anonymous read-only source inherited by trusted subprocesses."""

    fd: int
    identity: SourceIdentity

    @property
    def path(self) -> str:
        path = f"/dev/fd/{self.fd}"
        if not os.path.isdir("/dev/fd") or not os.path.exists(path):
            raise _identity_error("descriptor-backed sources are unavailable")
        return path

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return (self.fd,)

    def close(self) -> None:
        if self.fd < 0:
            return
        fd, self.fd = self.fd, -1
        try:
            os.close(fd)
        except OSError:
            raise _identity_error("verified source descriptor cleanup failed") from None

    def verify(self) -> SourceIdentity:
        """Re-hash the held descriptor and require its bound identity."""

        observed = _stream_fd_identity(self.fd)
        if observed != self.identity:
            raise _identity_error("verified source descriptor changed")
        return observed


def _identity_error(message: str) -> MCPVideoError:
    return MCPVideoError(
        message,
        error_type="validation_error",
        code="source_identity_changed",
    )


def stream_source_identity(path: str) -> SourceIdentity:
    """Hash one stable source stream and bind its byte count."""

    try:
        validated = _validate_input_path(path)
    except MCPVideoError as exc:
        raise _identity_error("source identity cannot be verified") from exc
    digest = hashlib.sha256()
    size = 0
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(validated, flags)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            while chunk := source.read(DEFAULT_BODY_SWAP_HASH_BUFFER_BYTES):
                digest.update(chunk)
                size += len(chunk)
            after = os.fstat(source.fileno())
    except OSError:
        raise _identity_error("source identity cannot be verified") from None
    markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in markers):
        raise _identity_error("source changed while verifying identity")
    return SourceIdentity(asset_id="sha256:" + digest.hexdigest(), byte_size=size)


def assert_source_identity(path: str, expected: SourceIdentity) -> None:
    """Require current bytes to equal an earlier verified identity."""

    if stream_source_identity(path) != expected:
        raise _identity_error("verified source identity changed")


def _stream_fd_identity(fd: int) -> SourceIdentity:
    """Hash the exact held descriptor and restore its offset for consumers."""

    digest = hashlib.sha256()
    size = 0
    try:
        before = os.fstat(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        while chunk := os.read(fd, DEFAULT_BODY_SWAP_HASH_BUFFER_BYTES):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(fd)
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        raise _identity_error("verified source descriptor cannot be read") from None
    markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in markers):
        raise _identity_error("verified source descriptor changed")
    return SourceIdentity("sha256:" + digest.hexdigest(), size)


def immutable_verified_snapshot_available() -> bool:
    """Return whether this host can make a kernel-immutable verified snapshot."""
    os_names = ("memfd_create", "MFD_ALLOW_SEALING")
    fcntl_names = ("F_ADD_SEALS", "F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")
    return fcntl is not None and all(hasattr(os, name) for name in os_names) and all(
        hasattr(fcntl, name) for name in fcntl_names
    )


def _sealed_snapshot_fd(source_fd: int) -> int:
    """Copy one descriptor into an immutable memfd when the kernel supports it."""

    if not immutable_verified_snapshot_available():
        raise _identity_error("immutable verified source snapshots are unavailable")

    flags = os.MFD_ALLOW_SEALING | getattr(os, "MFD_CLOEXEC", 0)
    sealed_fd = os.memfd_create("kinocut-verified-source", flags)
    try:
        os.lseek(source_fd, 0, os.SEEK_SET)
        while chunk := os.read(source_fd, DEFAULT_BODY_SWAP_HASH_BUFFER_BYTES):
            remaining = memoryview(chunk)
            while remaining:
                written = os.write(sealed_fd, remaining)
                if written <= 0:
                    raise OSError("verified source snapshot write failed")
                remaining = remaining[written:]
        os.fchmod(sealed_fd, 0o400)
        seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        fcntl.fcntl(sealed_fd, fcntl.F_ADD_SEALS, seals)
        os.lseek(sealed_fd, 0, os.SEEK_SET)
        return sealed_fd
    except OSError:
        with suppress(OSError):
            os.close(sealed_fd)
        raise


def copy_verified_snapshot(source_path: str, destination: Path, expected: SourceIdentity) -> VerifiedSource:
    """Copy, verify, reopen read-only, unlink, and return a held descriptor."""

    try:
        source = _validate_input_path(source_path)
    except MCPVideoError as exc:
        raise _identity_error("verified source snapshot cannot be created") from exc
    digest = hashlib.sha256()
    size = 0
    held_fd = -1
    try:
        source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            target_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            os.close(source_fd)
            raise
        with os.fdopen(source_fd, "rb") as reader, os.fdopen(target_fd, "wb") as writer:
            before = os.fstat(reader.fileno())
            while chunk := reader.read(DEFAULT_BODY_SWAP_HASH_BUFFER_BYTES):
                writer.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            after = os.fstat(reader.fileno())
        copied = SourceIdentity("sha256:" + digest.hexdigest(), size)
        stable = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        snapshot_fd = os.open(destination, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            held_fd = _sealed_snapshot_fd(snapshot_fd)
        finally:
            os.close(snapshot_fd)
        completed = _stream_fd_identity(held_fd)
        if not stable or copied != expected or completed != expected:
            raise _identity_error("source changed while creating verified snapshot")
        os.fchmod(held_fd, 0o400)
        destination.unlink()
        handle = VerifiedSource(fd=held_fd, identity=completed)
        _ = handle.path
        held_fd = -1
        return handle
    except OSError:
        raise _identity_error("verified source snapshot cannot be created") from None
    finally:
        if held_fd >= 0:
            with suppress(OSError):
                os.close(held_fd)
        with suppress(OSError):
            destination.unlink(missing_ok=True)
