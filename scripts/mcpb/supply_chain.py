"""Fail-closed runtime download and archive extraction for MCPB builds."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import struct
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol
from urllib.parse import urlsplit

from .defaults import (
    COPY_CHUNK_BYTES,
    DEFAULT_DOWNLOAD_TIMEOUT,
    DEFAULT_MAX_ARCHIVE_MEMBERS,
    DEFAULT_MAX_COMPONENT_CHARS,
    DEFAULT_MAX_ENTRY_BYTES,
    DEFAULT_MAX_EXPANDED_BYTES,
    DEFAULT_MAX_PATH_CHARS,
    DEFAULT_MAX_PATH_DEPTH,
    DEFAULT_MAX_TOTAL_NAME_BYTES,
    DEFAULT_MAX_ZIP_DIRECTORY_BYTES,
)
from .errors import MCPBSupplyChainError
from .model import ArchiveFormat, ArchiveLayout, RuntimeArtifact, TargetOS


_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP_EOCD_SIZE = 22
_ZIP_EOCD_SEARCH = _ZIP_EOCD_SIZE + 65_535


class _Response(Protocol):
    headers: object

    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> object: ...

    def geturl(self) -> str: ...

    def read(self, size: int = -1) -> bytes: ...


class _Opener(Protocol):
    def open(self, request: urllib.request.Request, *, timeout: float) -> _Response: ...


class _HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise MCPBSupplyChainError("runtime download redirect must remain HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _is_https(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def _content_length(response: _Response) -> int | None:
    raw = response.headers.get("Content-Length")  # type: ignore[union-attr]
    if raw is None:
        return None
    try:
        length = int(raw)
    except (TypeError, ValueError) as error:
        raise MCPBSupplyChainError("runtime download returned an invalid Content-Length") from error
    if length < 0:
        raise MCPBSupplyChainError("runtime download returned an invalid Content-Length")
    return length


def _stream_download(response: _Response, output: BinaryIO, max_bytes: int) -> str:
    declared = _content_length(response)
    if declared is not None and declared > max_bytes:
        raise MCPBSupplyChainError("runtime download exceeds its size limit")
    digest = hashlib.sha256()
    total = 0
    while chunk := response.read(min(COPY_CHUNK_BYTES, max_bytes + 1 - total)):
        total += len(chunk)
        if total > max_bytes:
            raise MCPBSupplyChainError("runtime download exceeds its size limit")
        digest.update(chunk)
        output.write(chunk)
    return digest.hexdigest()


def _verify_cached_archive(artifact: RuntimeArtifact, archive_path: Path) -> None:
    digest = hashlib.sha256()
    total = 0
    try:
        with archive_path.open("rb") as source:
            while chunk := source.read(COPY_CHUNK_BYTES):
                total += len(chunk)
                if total > artifact.max_download_bytes:
                    raise MCPBSupplyChainError("cached runtime archive exceeds its size limit")
                digest.update(chunk)
    except OSError as error:
        raise MCPBSupplyChainError("cached runtime archive is unreadable") from error
    if digest.hexdigest().lower() != artifact.sha256.lower():
        raise MCPBSupplyChainError("cached runtime archive SHA-256 does not match the lock")


def download_verified(
    artifact: RuntimeArtifact,
    destination: Path,
    *,
    max_bytes: int | None = None,
    timeout: float = DEFAULT_DOWNLOAD_TIMEOUT,
    opener: _Opener | None = None,
) -> Path:
    """Download an HTTPS runtime atomically and verify its locked SHA-256."""
    limit = artifact.max_download_bytes if max_bytes is None else max_bytes
    if limit <= 0 or timeout <= 0:
        raise MCPBSupplyChainError("runtime download bounds must be positive")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.part"
    request = urllib.request.Request(artifact.url, headers={"User-Agent": "kinocut-mcpb-builder/1"})
    client = opener or urllib.request.build_opener(_HTTPSOnlyRedirect())
    try:
        with client.open(request, timeout=timeout) as response:
            if not _is_https(response.geturl()):
                raise MCPBSupplyChainError("runtime download final URL must remain HTTPS")
            with temporary.open("xb") as output:
                actual_sha256 = _stream_download(response, output, limit)
        if actual_sha256.lower() != artifact.sha256.lower():
            raise MCPBSupplyChainError("runtime download SHA-256 does not match the lock")
        os.replace(temporary, destination)
    except MCPBSupplyChainError:
        temporary.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as error:
        temporary.unlink(missing_ok=True)
        raise MCPBSupplyChainError("runtime download failed") from error
    return destination


def _normalized_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise MCPBSupplyChainError(f"unsafe archive path: {name}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part == ".." for part in path.parts) or not path.parts:
        raise MCPBSupplyChainError(f"unsafe archive path: {name}")
    useful = tuple(part for part in path.parts if part not in {"", "."})
    if not useful:
        raise MCPBSupplyChainError(f"unsafe archive path: {name}")
    for part in useful:
        stem = part.split(".", 1)[0].upper()
        if (
            any(ord(char) < 32 or char in _WINDOWS_FORBIDDEN for char in part)
            or part.endswith((".", " "))
            or stem in _WINDOWS_DEVICES
        ):
            raise MCPBSupplyChainError(f"unsafe archive path: {name}")
    return PurePosixPath(*useful)


def _register_member(
    name: str,
    seen: set[str],
    *,
    count: int,
    total_name_bytes: int,
    max_members: int,
    max_path_depth: int,
    max_component_chars: int,
    max_path_chars: int,
    max_total_name_bytes: int,
) -> tuple[PurePosixPath, int]:
    path = _normalized_member(name)
    if count > max_members:
        raise MCPBSupplyChainError("archive exceeds the member count limit")
    if len(path.parts) > max_path_depth:
        raise MCPBSupplyChainError("archive member exceeds the path depth limit")
    if len(path.as_posix()) > max_path_chars or any(len(part) > max_component_chars for part in path.parts):
        raise MCPBSupplyChainError("archive member path is too long")
    total_name_bytes += len(path.as_posix().encode("utf-8"))
    if total_name_bytes > max_total_name_bytes:
        raise MCPBSupplyChainError("archive exceeds the total name bytes limit")
    identity = path.as_posix().casefold()
    if identity in seen:
        raise MCPBSupplyChainError(f"duplicate archive member: {path}")
    seen.add(identity)
    return path, total_name_bytes


def _validate_size(size: int, total: int, max_entry_bytes: int, max_total_bytes: int) -> int:
    if size < 0 or size > max_entry_bytes:
        raise MCPBSupplyChainError("archive member exceeds the entry size limit")
    total += size
    if total > max_total_bytes:
        raise MCPBSupplyChainError("archive exceeds the total size limit")
    return total


def _validate_symlink(member: PurePosixPath, target: str) -> None:
    normalized = target.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise MCPBSupplyChainError(f"unsafe symlink target: {target}")
    parts = list(member.parent.parts)
    for part in PurePosixPath(normalized).parts:
        if part == "..":
            if not parts:
                raise MCPBSupplyChainError(f"unsafe symlink target: {target}")
            parts.pop()
        elif part not in {"", "."}:
            parts.append(part)
    _normalized_member("/".join(parts))


def _output_path(destination: Path, member: PurePosixPath) -> Path:
    root = destination.resolve()
    output = (root / Path(*member.parts)).resolve()
    if not output.is_relative_to(root):
        raise MCPBSupplyChainError(f"unsafe archive path: {member}")
    return output


def _copy_bounded(source: BinaryIO, output: Path, expected: int, max_entry_bytes: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("xb") as destination:
        while chunk := source.read(min(COPY_CHUNK_BYTES, max_entry_bytes + 1 - written)):
            written += len(chunk)
            if written > max_entry_bytes or written > expected:
                raise MCPBSupplyChainError("archive member exceeds its declared size")
            destination.write(chunk)
    if written != expected:
        raise MCPBSupplyChainError("archive member size does not match its declaration")


def _extract_tar(
    archive_path: Path,
    destination: Path,
    archive_format: ArchiveFormat,
    max_entry_bytes: int,
    max_total_bytes: int,
    metadata_bounds: tuple[int, int, int, int, int],
) -> None:
    mode = "r:gz" if archive_format is ArchiveFormat.TAR_GZ else "r:xz"
    with tarfile.open(archive_path, mode) as archive:
        seen: set[str] = set()
        total = 0
        total_name_bytes = 0
        entries: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        for count, info in enumerate(archive, start=1):
            member, total_name_bytes = _register_member(
                info.name,
                seen,
                count=count,
                total_name_bytes=total_name_bytes,
                max_members=metadata_bounds[0],
                max_path_depth=metadata_bounds[1],
                max_component_chars=metadata_bounds[2],
                max_path_chars=metadata_bounds[3],
                max_total_name_bytes=metadata_bounds[4],
            )
            if info.issym():
                _validate_symlink(member, info.linkname)
            elif not (info.isfile() or info.isdir()):
                raise MCPBSupplyChainError(f"unsupported archive member type: {info.name}")
            total = _validate_size(info.size, total, max_entry_bytes, max_total_bytes)
            entries.append((info, member))
        destination.mkdir(parents=True, exist_ok=True)
        for info, member in entries:
            output = _output_path(destination, member)
            if info.isdir():
                output.mkdir(parents=True, exist_ok=True)
            elif info.issym():
                output.parent.mkdir(parents=True, exist_ok=True)
                output.symlink_to(info.linkname)
            else:
                source = archive.extractfile(info)
                if source is None:
                    raise MCPBSupplyChainError(f"archive member is unreadable: {info.name}")
                with source:
                    _copy_bounded(source, output, info.size, max_entry_bytes)
                output.chmod(info.mode & 0o755)


def _zip_kind(info: zipfile.ZipInfo) -> str:
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        return "symlink"
    if info.is_dir():
        return "directory"
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG}:
        raise MCPBSupplyChainError(f"unsupported archive member type: {info.filename}")
    return "file"


def _preflight_zip(archive_path: Path, max_members: int, max_directory_bytes: int) -> None:
    """Reject oversized/Zip64 central directories before ZipFile retains them."""
    try:
        size = archive_path.stat().st_size
        with archive_path.open("rb") as source:
            source.seek(max(0, size - _ZIP_EOCD_SEARCH))
            tail = source.read(_ZIP_EOCD_SEARCH)
    except OSError as error:
        raise MCPBSupplyChainError("runtime ZIP metadata is unreadable") from error
    offset = tail.rfind(_ZIP_EOCD_SIGNATURE)
    if offset < 0 or len(tail) - offset < _ZIP_EOCD_SIZE:
        raise MCPBSupplyChainError("runtime ZIP has no valid end-of-central-directory record")
    record = struct.unpack_from("<4s4H2LH", tail, offset)
    _, disk, start_disk, entries_disk, entries_total, directory_size, directory_offset, comment_size = record
    if offset + _ZIP_EOCD_SIZE + comment_size != len(tail):
        raise MCPBSupplyChainError("runtime ZIP end-of-central-directory record is malformed")
    if disk != 0 or start_disk != 0 or entries_disk != entries_total:
        raise MCPBSupplyChainError("multi-disk runtime ZIP archives are unsupported")
    if entries_total == 0xFFFF or directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF:
        raise MCPBSupplyChainError("Zip64 runtime archives are unsupported")
    if entries_total > max_members:
        raise MCPBSupplyChainError("archive exceeds the member count limit")
    if directory_size > max_directory_bytes or directory_offset + directory_size > size:
        raise MCPBSupplyChainError("runtime ZIP central directory exceeds its metadata limit")


def _extract_zip(
    archive_path: Path,
    destination: Path,
    max_entry_bytes: int,
    max_total_bytes: int,
    metadata_bounds: tuple[int, int, int, int, int],
    max_directory_bytes: int,
) -> None:
    _preflight_zip(archive_path, metadata_bounds[0], max_directory_bytes)
    with zipfile.ZipFile(archive_path) as archive:
        seen: set[str] = set()
        total = 0
        total_name_bytes = 0
        entries: list[tuple[zipfile.ZipInfo, PurePosixPath, str, str | None]] = []
        for count, info in enumerate(archive.infolist(), start=1):
            member, total_name_bytes = _register_member(
                info.filename,
                seen,
                count=count,
                total_name_bytes=total_name_bytes,
                max_members=metadata_bounds[0],
                max_path_depth=metadata_bounds[1],
                max_component_chars=metadata_bounds[2],
                max_path_chars=metadata_bounds[3],
                max_total_name_bytes=metadata_bounds[4],
            )
            kind = _zip_kind(info)
            total = _validate_size(info.file_size, total, max_entry_bytes, max_total_bytes)
            target = None
            if kind == "symlink":
                if info.file_size > metadata_bounds[3]:
                    raise MCPBSupplyChainError("archive symlink target exceeds the path length limit")
                with archive.open(info) as source:
                    payload = source.read(metadata_bounds[3] + 1)
                if len(payload) != info.file_size:
                    raise MCPBSupplyChainError("archive symlink target exceeds its declared size")
                target = payload.decode("utf-8")
                _validate_symlink(member, target)
            entries.append((info, member, kind, target))
        destination.mkdir(parents=True, exist_ok=True)
        for info, member, kind, target in entries:
            output = _output_path(destination, member)
            if kind == "directory":
                output.mkdir(parents=True, exist_ok=True)
            elif kind == "symlink":
                output.parent.mkdir(parents=True, exist_ok=True)
                output.symlink_to(target)
            else:
                with archive.open(info) as source:
                    _copy_bounded(source, output, info.file_size, max_entry_bytes)
                mode = info.external_attr >> 16
                if mode:
                    output.chmod(mode & 0o755)


def safe_extract_archive(
    archive_path: Path,
    destination: Path,
    archive_format: ArchiveFormat,
    *,
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
    max_total_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
    max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
    max_path_depth: int = DEFAULT_MAX_PATH_DEPTH,
    max_component_chars: int = DEFAULT_MAX_COMPONENT_CHARS,
    max_path_chars: int = DEFAULT_MAX_PATH_CHARS,
    max_total_name_bytes: int = DEFAULT_MAX_TOTAL_NAME_BYTES,
    max_zip_directory_bytes: int = DEFAULT_MAX_ZIP_DIRECTORY_BYTES,
) -> Path:
    """Extract a locked runtime archive after validating every entry."""
    bounds = (
        max_entry_bytes,
        max_total_bytes,
        max_members,
        max_path_depth,
        max_component_chars,
        max_path_chars,
        max_total_name_bytes,
        max_zip_directory_bytes,
    )
    if any(type(bound) is not int or bound <= 0 for bound in bounds):
        raise MCPBSupplyChainError("archive extraction bounds must be positive")
    metadata_bounds = (max_members, max_path_depth, max_component_chars, max_path_chars, max_total_name_bytes)
    archive_path = Path(archive_path)
    destination = Path(destination)
    if destination.exists():
        raise MCPBSupplyChainError("archive extraction destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        if archive_format in {ArchiveFormat.TAR_GZ, ArchiveFormat.TAR_XZ}:
            _extract_tar(archive_path, staging, archive_format, max_entry_bytes, max_total_bytes, metadata_bounds)
        elif archive_format is ArchiveFormat.ZIP:
            _extract_zip(
                archive_path,
                staging,
                max_entry_bytes,
                max_total_bytes,
                metadata_bounds,
                max_zip_directory_bytes,
            )
        else:
            raise MCPBSupplyChainError(f"unsupported archive format: {archive_format}")
        staging.rename(destination)
    except MCPBSupplyChainError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile, UnicodeError) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise MCPBSupplyChainError("runtime archive extraction failed") from error
    return destination


def _contained_file(root: Path, relative: str, label: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    if label == "notice":
        current = root
        for part in PurePosixPath(relative).parts:
            current /= part
            if current.is_symlink():
                raise MCPBSupplyChainError(f"runtime artifact has unsafe {label}: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise MCPBSupplyChainError(f"runtime artifact is missing {label}: {relative}") from error
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise MCPBSupplyChainError(f"runtime artifact has unsafe {label}: {relative}")
    return resolved


def extract_locked_artifact(artifact: RuntimeArtifact, archive_path: Path, destination: Path) -> Path:
    """Extract one locked artifact, normalize its layout, and verify its inventory."""
    destination = Path(destination)
    if destination.exists():
        raise MCPBSupplyChainError("runtime artifact destination already exists")
    archive_path = Path(archive_path)
    _verify_cached_archive(artifact, archive_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    container = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    unpacked = container / "unpacked"
    try:
        safe_extract_archive(
            archive_path,
            unpacked,
            artifact.archive_format,
            max_total_bytes=artifact.max_expanded_bytes,
        )
        root = unpacked
        if artifact.archive_layout is ArchiveLayout.SINGLE_DIRECTORY:
            children = list(unpacked.iterdir())
            if len(children) != 1 or not children[0].is_dir() or children[0].is_symlink():
                raise MCPBSupplyChainError("runtime archive must contain one top-level directory")
            root = children[0]
        for executable in artifact.expected_executables:
            path = _contained_file(root, executable, "expected executable")
            if artifact.os is not TargetOS.WINDOWS and not os.access(path, os.X_OK):
                raise MCPBSupplyChainError(f"runtime artifact expected executable is not executable: {executable}")
        for notice in artifact.notice_paths:
            _contained_file(root, notice, "notice")
        destination.parent.mkdir(parents=True, exist_ok=True)
        root.rename(destination)
    except MCPBSupplyChainError:
        shutil.rmtree(container, ignore_errors=True)
        raise
    except OSError as error:
        shutil.rmtree(container, ignore_errors=True)
        raise MCPBSupplyChainError("runtime artifact assembly failed") from error
    shutil.rmtree(container, ignore_errors=True)
    return destination


__all__ = ["MCPBSupplyChainError", "download_verified", "extract_locked_artifact", "safe_extract_archive"]
