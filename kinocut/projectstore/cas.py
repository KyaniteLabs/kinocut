"""Immutable content-addressed blob ingest and resolution."""

from __future__ import annotations

import hashlib
import os
import sys
from threading import Lock
from pathlib import Path
from typing import cast

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import CASManifestRecord
from kinocut.projectstore import layout, store
from kinocut.projectstore.cas_lifecycle import cleanup_backups, restore_blob, unavailable_digests
from kinocut.projectstore.ingest import _best_effort_unlink, _hash_copy_to_temp

_CHUNK = 1 << 20
_TRUSTED_LINUX_FSTYPES = frozenset(
    {b"ext2", b"ext3", b"ext4", b"xfs", b"btrfs", b"tmpfs", b"zfs", b"overlay", b"overlayfs"}
)
_TRUSTED_DARWIN_FSTYPES = frozenset({b"apfs", b"hfs"})
_TRUSTED_WINDOWS_FSTYPES = frozenset({"NTFS", "REFS"})
_VERIFIED: dict[tuple[int, ...], str] = {}
_CACHE_LOCK = Lock()


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _unescape_mount_path(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="surrogateescape")
    for octal, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        text = text.replace(octal, char)
    return text


def _darwin_has_trusted_ctime(path: Path | None) -> bool:
    """Confirm APFS/HFS+ on macOS via libc statfs while rejecting network/FAT/FUSE mounts."""
    if path is None:
        return False
    try:
        import ctypes
        import ctypes.util

        libc_path = ctypes.util.find_library("c")
        if not libc_path:
            return False
        libc = ctypes.CDLL(libc_path)

        # Darwin 64-bit struct statfs: f_fstypename is char[16] at offset 64 (or 88 on 64-bit inode ABI).
        class _DarwinStatfs64(ctypes.Structure):
            _fields_ = [
                ("f_bsize", ctypes.c_uint32),
                ("f_iosize", ctypes.c_int32),
                ("f_blocks", ctypes.c_uint64),
                ("f_bfree", ctypes.c_uint64),
                ("f_bavail", ctypes.c_uint64),
                ("f_files", ctypes.c_uint64),
                ("f_ffree", ctypes.c_uint64),
                ("f_fsid", ctypes.c_int32 * 2),
                ("f_owner", ctypes.c_uint32),
                ("f_type", ctypes.c_uint32),
                ("f_flags", ctypes.c_uint32),
                ("f_fssubtype", ctypes.c_uint32),
                ("f_fstypename", ctypes.c_char * 16),
                ("f_mntonname", ctypes.c_char * 1024),
                ("f_mntfromname", ctypes.c_char * 1024),
                ("f_flags_ext", ctypes.c_uint32),
                ("f_reserved", ctypes.c_uint32 * 7),
            ]

        buf = _DarwinStatfs64()
        fn = getattr(libc, "statfs$INODE64", None) or libc.statfs
        fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(_DarwinStatfs64)]
        fn.restype = ctypes.c_int
        if fn(os.fsencode(os.path.realpath(path)), ctypes.byref(buf)) != 0:
            return False
        fstype = bytes(buf.f_fstypename).split(b"\x00", 1)[0].lower()
        return fstype in _TRUSTED_DARWIN_FSTYPES
    except Exception:
        return False


def _windows_has_trusted_ctime(path: Path | None) -> bool:
    """Confirm local NTFS/ReFS on Windows while rejecting UNC shares and FAT/exFAT volumes."""
    if path is None:
        return False
    try:
        resolved = os.path.realpath(path)
        if resolved.startswith("\\\\"):
            return False
        drive, _ = os.path.splitdrive(resolved)
        if not drive:
            return False
        root = drive + "\\"
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fs_buf = ctypes.create_unicode_buffer(64)
        ok = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            None,
            0,
            None,
            None,
            None,
            fs_buf,
            len(fs_buf),
        )
        if not ok:
            return False
        return fs_buf.value.upper() in _TRUSTED_WINDOWS_FSTYPES
    except Exception:
        return False


def _device_has_trusted_ctime(dev: int, path: Path | None = None) -> bool:
    """Return True only when the device/mount is confirmed as a local filesystem with reliable ctime."""
    if os.name == "nt":
        return _windows_has_trusted_ctime(path)
    if sys.platform == "darwin":
        return _darwin_has_trusted_ctime(path)
    if os.name != "posix" or not hasattr(os, "major") or not hasattr(os, "minor"):
        return False
    dev_id = f"{os.major(dev)}:{os.minor(dev)}".encode("ascii")
    resolved_path = os.path.realpath(path) if path is not None else None
    best_mount_len = -1
    best_mount_fstype: bytes | None = None
    try:
        with open("/proc/self/mountinfo", "rb") as handle:
            for line in handle:
                parts = line.split(b" - ", 1)
                if len(parts) != 2:
                    continue
                head = parts[0].split()
                tail = parts[1].split()
                if len(head) < 5 or not tail:
                    continue
                if head[2] == dev_id:
                    return tail[0] in _TRUSTED_LINUX_FSTYPES
                if resolved_path is not None:
                    mount_point = _unescape_mount_path(head[4])
                    prefix = mount_point if mount_point == "/" else mount_point.rstrip("/")
                    if (
                        resolved_path == prefix or resolved_path.startswith("/" if prefix == "/" else prefix + "/")
                    ) and len(prefix) > best_mount_len:
                        best_mount_len = len(prefix)
                        best_mount_fstype = tail[0]
    except OSError:
        return False
    if best_mount_fstype is not None:
        return best_mount_fstype in _TRUSTED_LINUX_FSTYPES
    return False


def _cacheable_identity(info: os.stat_result, path: Path | None = None) -> tuple[int, ...] | None:
    """Return a cache key only when the backing filesystem reliably advances ctime on rewrites."""
    if info.st_ino == 0 or info.st_ctime_ns <= 0:
        return None
    try:
        trusted = _device_has_trusted_ctime(info.st_dev, path=path)
    except TypeError:
        trusted = _device_has_trusted_ctime(info.st_dev)
    if not trusted:
        return None
    return _identity(info)


def _manifest(project: store.Project, digest: str) -> CASManifestRecord | None:
    matches = [
        r
        for r in store.read_records(project, "cas_manifest")
        if isinstance(r, CASManifestRecord) and r.digest == digest
    ]
    if len(matches) > 1:
        raise contract_error("CAS digest has multiple manifest records", INVALID_RECORD)
    return matches[0] if matches else None


def ingest_blob(project: store.Project, source_path: str | Path, *, media_type: str | None = None) -> CASManifestRecord:
    """Hash and atomically install one immutable blob, idempotently by digest."""

    with store._project_lock(project):
        digest, byte_size, temporary = _hash_copy_to_temp(project, Path(source_path))
        try:
            if existing := _manifest(project, digest):
                if byte_size != existing.byte_size:
                    raise contract_error("CAS manifest byte size disagrees with its source digest", INVALID_RECORD)
                target = store.safe_target(project, existing.blob_location)
                if digest in unavailable_digests(project) or not _blob_matches(target, existing):
                    restore_blob(project, existing, temporary)
                else:
                    cleanup_backups(project, digest)
                return existing
            relative = layout.blob_relative_path(digest)
            target = store.safe_target(project, relative)
            record = validate_record(
                CASManifestRecord,
                {
                    "project_id": project.project_id,
                    "created_by": "tool",
                    "digest": digest,
                    "byte_size": byte_size,
                    "blob_location": str(relative),
                    "media_type": media_type,
                },
            )
            try:
                with store._mapped_os_errors():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(temporary, target)
                    store._fsync_dir(target.parent)
                return cast(CASManifestRecord, store.append_record_locked(project, record))
            except BaseException:
                _best_effort_unlink(target)
                raise
        finally:
            _best_effort_unlink(temporary)


def resolve_blob(project: store.Project, digest: str, *, verify_content: bool = True) -> Path:
    """Resolve and integrity-check a recorded blob; set verify_content=False to opt into cached reuse."""

    with store._project_lock(project):
        manifest = _manifest(project, digest)
        if manifest is None:
            raise contract_error("CAS digest is not recorded in this project", INVALID_RECORD)
        if digest in _deleted_digests(project):
            raise contract_error(
                "CAS blob is unavailable after garbage collection or interrupted restoration", INVALID_RECORD
            )
        target = store.safe_target(project, manifest.blob_location)
        if not _blob_matches(target, manifest, verify_content=verify_content):
            raise contract_error("CAS blob is unavailable or failed its manifest integrity check", INVALID_RECORD)
        return target


def _blob_matches(target: Path, manifest: CASManifestRecord, *, verify_content: bool = True) -> bool:
    try:
        if not target.is_file():
            return False
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as reader:
            before = os.fstat(fd)
            if before.st_size != manifest.byte_size:
                return False
            key = _identity(before)
            cache_key = _cacheable_identity(before, path=target)
            if not verify_content and cache_key is not None:
                with _CACHE_LOCK:
                    if cache_key in _VERIFIED:
                        return _VERIFIED[cache_key] == manifest.digest
            actual = hashlib.sha256()
            while chunk := reader.read(_CHUNK):
                actual.update(chunk)
            if key != _identity(os.fstat(fd)):
                return False
            digest = "sha256:" + actual.hexdigest()
            if cache_key is not None:
                with _CACHE_LOCK:
                    if len(_VERIFIED) >= 1024:
                        _VERIFIED.pop(next(iter(_VERIFIED)))
                    _VERIFIED[cache_key] = digest
            return digest == manifest.digest
    except OSError:
        return False


def _deleted_digests(project: store.Project) -> set[str]:
    """Return unavailable digests, honoring recorded restoration generations."""
    return unavailable_digests(project)


__all__ = ["ingest_blob", "resolve_blob"]
