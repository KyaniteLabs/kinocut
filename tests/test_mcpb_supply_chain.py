"""Supply-chain contracts for self-contained, target-specific MCPB builds."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.mcpb.manifest import generate_target_manifest
from scripts.mcpb.model import (
    ArchiveFormat,
    ArchiveLayout,
    RuntimeArtifact,
    RuntimeLock,
    Target,
    TargetArch,
    TargetOS,
)
from scripts.mcpb.supply_chain import (
    MCPBSupplyChainError,
    download_verified,
    extract_locked_artifact,
    safe_extract_archive,
)


def _artifact(payload: bytes, *, url: str = "https://downloads.example.test/python-3.12.10.tar.gz") -> RuntimeArtifact:
    return RuntimeArtifact(
        name="python",
        version="3.12.10",
        url=url,
        sha256=hashlib.sha256(payload).hexdigest(),
        archive_format=ArchiveFormat.TAR_GZ,
        archive_layout=ArchiveLayout.SINGLE_DIRECTORY,
        expected_executables=("bin/python3",),
        os=TargetOS.DARWIN,
        arch=TargetArch.ARM64,
        license_id="PSF-2.0",
        source_url="https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tar.xz",
        source_sha256="b" * 64,
        notice_paths=("LICENSE",),
        max_download_bytes=1024,
        max_expanded_bytes=4096,
    )


def test_runtime_lock_parses_a_typed_target_and_pinned_artifacts() -> None:
    lock = RuntimeLock.from_dict(
        {
            "target": {"os": "darwin", "arch": "arm64"},
            "artifacts": [
                {
                    "name": "python",
                    "version": "3.12.10",
                    "url": "https://downloads.example.test/python-3.12.10.tar.gz",
                    "sha256": "a" * 64,
                    "archive_format": "tar.gz",
                    "archive_layout": "single-directory",
                    "expected_executables": ["bin/python3"],
                    "os": "darwin",
                    "arch": "arm64",
                    "license_id": "PSF-2.0",
                    "source_url": "https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tar.xz",
                    "source_sha256": "b" * 64,
                    "notice_paths": ["LICENSE"],
                    "max_download_bytes": 1024,
                    "max_expanded_bytes": 4096,
                }
            ],
        }
    )

    assert lock.target == Target(TargetOS.DARWIN, TargetArch.ARM64)
    assert lock.target.key == "darwin-arm64"
    assert lock.target.is_initial_build_target is True
    assert lock.artifact("python").archive_format is ArchiveFormat.TAR_GZ


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"url": "http://downloads.example.test/runtime.zip"}, "HTTPS"),
        ({"sha256": "not-a-digest"}, "SHA-256"),
        ({"name": "../python"}, "name"),
    ],
)
def test_runtime_artifact_rejects_unpinned_or_unsafe_identity(mutation: dict[str, str], match: str) -> None:
    values = {
        "name": "python",
        "version": "3.12.10",
        "url": "https://downloads.example.test/runtime-3.12.10.zip",
        "sha256": "a" * 64,
        "archive_format": ArchiveFormat.ZIP,
        "archive_layout": ArchiveLayout.ROOT,
        "expected_executables": ("python.exe",),
        "os": TargetOS.WINDOWS,
        "arch": TargetArch.X64,
        "license_id": "PSF-2.0",
        "source_url": "https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tar.xz",
        "source_sha256": "b" * 64,
        "notice_paths": ("LICENSE",),
        "max_download_bytes": 1024,
        "max_expanded_bytes": 4096,
    }
    values.update(mutation)

    with pytest.raises(MCPBSupplyChainError, match=match):
        RuntimeArtifact(**values)


def test_runtime_lock_rejects_duplicate_artifact_names() -> None:
    artifact = _artifact(b"runtime")

    with pytest.raises(MCPBSupplyChainError, match="duplicate runtime artifact"):
        RuntimeLock(Target(TargetOS.DARWIN, TargetArch.ARM64), (artifact, artifact))


@pytest.mark.parametrize(
    "mutation",
    [
        {"expected_executables": "bin/python3"},
        {"max_download_bytes": True},
        {"notice_paths": []},
        {"source_url": "https://github.com/python/cpython/tree/3.12"},
        {"source_url": "https://downloads.example.test/current-2026/Python3.tar.xz"},
        {"source_url": "https://downloads.example.test/nightly-2026/Python3.tar.xz"},
        {"surprise": "field"},
    ],
)
def test_runtime_artifact_lock_rejects_malformed_or_mutable_entries(mutation: dict[str, object]) -> None:
    value = {
        "name": "python",
        "version": "3.12.10",
        "url": "https://downloads.example.test/python-3.12.10.tar.gz",
        "sha256": "a" * 64,
        "archive_format": "tar.gz",
        "archive_layout": "single-directory",
        "expected_executables": ["bin/python3"],
        "os": "darwin",
        "arch": "arm64",
        "license_id": "PSF-2.0",
        "source_url": "https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tar.xz",
        "source_sha256": "b" * 64,
        "notice_paths": ["LICENSE"],
        "max_download_bytes": 1024,
        "max_expanded_bytes": 4096,
    }
    value.update(mutation)

    with pytest.raises(MCPBSupplyChainError, match=r"invalid runtime artifact lock entry|mutable|notice"):
        RuntimeArtifact.from_dict(value)


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, *, url: str, content_length: int | None = None) -> None:
        super().__init__(payload)
        self.url = url
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def geturl(self) -> str:
        return self.url


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout: float):
        self.request = request
        self.timeout = timeout
        return self.response


def test_download_verified_streams_https_to_an_atomic_digest_checked_file(tmp_path: Path) -> None:
    payload = b"verified runtime payload"
    opener = _Opener(_Response(payload, url="https://cdn.example.test/python.tar.gz", content_length=len(payload)))
    destination = tmp_path / "cache" / "python.tar.gz"

    result = download_verified(_artifact(payload), destination, max_bytes=1024, timeout=7, opener=opener)

    assert result == destination
    assert destination.read_bytes() == payload
    assert opener.timeout == 7
    assert opener.request.full_url.startswith("https://")
    assert not (destination.parent / f".{destination.name}.part").exists()


@pytest.mark.parametrize(
    ("response", "artifact", "max_bytes", "match"),
    [
        (_Response(b"payload", url="http://cdn.example.test/runtime"), _artifact(b"payload"), 1024, "HTTPS"),
        (_Response(b"payload", url="https://cdn.example.test/runtime"), _artifact(b"different"), 1024, "SHA-256"),
        (
            _Response(b"too-large", url="https://cdn.example.test/runtime", content_length=9),
            _artifact(b"too-large"),
            4,
            "size limit",
        ),
    ],
)
def test_download_verified_rejects_downgrades_digest_mismatch_and_oversize(
    tmp_path: Path,
    response: _Response,
    artifact: RuntimeArtifact,
    max_bytes: int,
    match: str,
) -> None:
    destination = tmp_path / "runtime.archive"

    with pytest.raises(MCPBSupplyChainError, match=match):
        download_verified(artifact, destination, max_bytes=max_bytes, timeout=3, opener=_Opener(response))

    assert not destination.exists()
    assert not (tmp_path / ".runtime.archive.part").exists()


def _tar(path: Path, entries: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for info, payload in entries:
            archive.addfile(info, io.BytesIO(payload) if info.isreg() else None)


def _tar_file(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o755
    return info, payload


def test_safe_extract_archive_extracts_regular_tar_and_safe_relative_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    symlink = tarfile.TarInfo("python/bin/python3")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "python3.12"
    _tar(archive, [_tar_file("python/bin/python3.12", b"python"), (symlink, b"")])

    destination = tmp_path / "out"
    safe_extract_archive(archive, destination, ArchiveFormat.TAR_GZ, max_entry_bytes=16, max_total_bytes=32)

    assert (destination / "python/bin/python3.12").read_bytes() == b"python"
    assert (destination / "python/bin/python3").is_symlink()
    assert (destination / "python/bin/python3").readlink() == Path("python3.12")


@pytest.mark.parametrize("member_name", ["/absolute/file", "../escape", "dir/../../escape"])
def test_safe_extract_archive_rejects_absolute_and_traversal_tar_members(tmp_path: Path, member_name: str) -> None:
    archive = tmp_path / "bad.tar.gz"
    _tar(archive, [_tar_file(member_name, b"bad")])

    with pytest.raises(MCPBSupplyChainError, match="unsafe archive path"):
        safe_extract_archive(archive, tmp_path / "out", ArchiveFormat.TAR_GZ)


def test_safe_extract_archive_rejects_device_unsafe_symlink_duplicate_and_oversized_tar(tmp_path: Path) -> None:
    cases: list[tuple[list[tuple[tarfile.TarInfo, bytes]], str]] = []
    device = tarfile.TarInfo("device")
    device.type = tarfile.CHRTYPE
    cases.append(([(device, b"")], "unsupported archive member"))
    symlink = tarfile.TarInfo("bin/python")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "../../outside"
    cases.append(([(symlink, b"")], "unsafe symlink"))
    cases.append(([_tar_file("same", b"one"), _tar_file("./same", b"two")], "duplicate archive member"))
    cases.append(([_tar_file("large", b"12345")], "entry size limit"))

    for index, (entries, match) in enumerate(cases):
        archive = tmp_path / f"bad-{index}.tar.gz"
        _tar(archive, entries)
        with pytest.raises(MCPBSupplyChainError, match=match):
            safe_extract_archive(
                archive,
                tmp_path / f"out-{index}",
                ArchiveFormat.TAR_GZ,
                max_entry_bytes=4,
                max_total_bytes=8,
            )


def test_safe_extract_archive_rejects_unsafe_zip_members(tmp_path: Path) -> None:
    cases = [
        ("../escape", b"bad", 0, "unsafe archive path"),
        ("large", b"12345", 0, "entry size limit"),
        ("link", b"..", stat.S_IFLNK << 16, "unsafe symlink"),
    ]
    for index, (name, payload, external_attr, match) in enumerate(cases):
        archive = tmp_path / f"bad-{index}.zip"
        with zipfile.ZipFile(archive, "w") as output:
            info = zipfile.ZipInfo(name)
            info.external_attr = external_attr
            output.writestr(info, payload)
        with pytest.raises(MCPBSupplyChainError, match=match):
            safe_extract_archive(
                archive,
                tmp_path / f"zip-out-{index}",
                ArchiveFormat.ZIP,
                max_entry_bytes=4,
                max_total_bytes=8,
            )


@pytest.mark.parametrize(
    "member",
    [
        "CON.txt",
        "aux",
        "dir/NUL.json",
        "bad:name",
        "bad<name",
        'bad"name',
        "bad|name",
        "bad?name",
        "bad*name",
        "trail. ",
        "nul\x00name",
    ],
)
@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_safe_extract_archive_rejects_nonportable_windows_paths(tmp_path: Path, member: str, kind: str) -> None:
    if kind == "tar":
        archive = tmp_path / "bad.tar.gz"
        _tar(archive, [_tar_file(member, b"bad")])
        archive_format = ArchiveFormat.TAR_GZ
    else:
        archive = tmp_path / "bad.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr(member, b"bad")
        archive_format = ArchiveFormat.ZIP

    with pytest.raises(MCPBSupplyChainError, match="unsafe archive path"):
        safe_extract_archive(archive, tmp_path / "out", archive_format)


def test_safe_extract_archive_enforces_metadata_bounds_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for index in range(4):
            output.writestr(f"root/entry-{index}", b"")

    with pytest.raises(MCPBSupplyChainError, match="member count"):
        safe_extract_archive(archive, tmp_path / "count-out", ArchiveFormat.ZIP, max_members=3)
    with pytest.raises(MCPBSupplyChainError, match="path depth"):
        safe_extract_archive(archive, tmp_path / "depth-out", ArchiveFormat.ZIP, max_path_depth=1)
    with pytest.raises(MCPBSupplyChainError, match="name bytes"):
        safe_extract_archive(archive, tmp_path / "names-out", ArchiveFormat.ZIP, max_total_name_bytes=12)


def test_extract_locked_artifact_normalizes_single_directory_and_checks_inventory(tmp_path: Path) -> None:
    archive = tmp_path / "python.tar.gz"
    _tar(
        archive,
        [
            _tar_file("python-runtime/bin/python3", b"python"),
            _tar_file("python-runtime/LICENSE", b"license"),
        ],
    )
    artifact = _artifact(archive.read_bytes())

    result = extract_locked_artifact(artifact, archive, tmp_path / "runtime")

    assert result == tmp_path / "runtime"
    assert (result / "bin/python3").read_bytes() == b"python"
    assert (result / "LICENSE").read_bytes() == b"license"


def test_extract_locked_artifact_rejects_missing_inventory(tmp_path: Path) -> None:
    archive = tmp_path / "python.tar.gz"
    _tar(archive, [_tar_file("python-runtime/LICENSE", b"license")])

    with pytest.raises(MCPBSupplyChainError, match="expected executable"):
        extract_locked_artifact(_artifact(archive.read_bytes()), archive, tmp_path / "runtime")


def test_extract_locked_artifact_rechecks_the_locked_archive_digest(tmp_path: Path) -> None:
    archive = tmp_path / "python.tar.gz"
    _tar(archive, [_tar_file("python-runtime/bin/python3", b"python")])
    artifact = _artifact(archive.read_bytes())
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(MCPBSupplyChainError, match="SHA-256"):
        extract_locked_artifact(artifact, archive, tmp_path / "runtime")


def test_extract_locked_artifact_rejects_notice_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "python.tar.gz"
    notice = tarfile.TarInfo("python-runtime/LICENSE")
    notice.type = tarfile.SYMTYPE
    notice.linkname = "bin/python3"
    _tar(archive, [_tar_file("python-runtime/bin/python3", b"python"), (notice, b"")])

    with pytest.raises(MCPBSupplyChainError, match="unsafe notice"):
        extract_locked_artifact(_artifact(archive.read_bytes()), archive, tmp_path / "runtime")


def test_extract_locked_artifact_rejects_notice_ancestor_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "python.tar.gz"
    licenses = tarfile.TarInfo("python-runtime/licenses")
    licenses.type = tarfile.SYMTYPE
    licenses.linkname = "bin"
    _tar(
        archive,
        [
            _tar_file("python-runtime/bin/python3", b"python"),
            _tar_file("python-runtime/bin/LICENSE", b"not the declared notice"),
            (licenses, b""),
        ],
    )
    artifact = _artifact(archive.read_bytes())
    object.__setattr__(artifact, "notice_paths", ("licenses/LICENSE",))

    with pytest.raises(MCPBSupplyChainError, match="unsafe notice"):
        extract_locked_artifact(artifact, archive, tmp_path / "runtime")


def test_safe_extract_archive_rejects_duplicate_and_total_oversized_zip(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as output:
        output.writestr("same", b"one")
        output.writestr("./same", b"two")
    with pytest.raises(MCPBSupplyChainError, match="duplicate archive member"):
        safe_extract_archive(duplicate, tmp_path / "dup-out", ArchiveFormat.ZIP)

    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as output:
        output.writestr("one", b"123")
        output.writestr("two", b"456")
    with pytest.raises(MCPBSupplyChainError, match="total size limit"):
        safe_extract_archive(oversized, tmp_path / "size-out", ArchiveFormat.ZIP, max_total_bytes=5)


@pytest.mark.parametrize(
    ("target", "node"),
    [
        (
            Target(TargetOS.DARWIN, TargetArch.ARM64),
            "${__dirname}/runtime/node/bin/node",
        ),
        (
            Target(TargetOS.WINDOWS, TargetArch.X64),
            "${__dirname}/runtime/node/node.exe",
        ),
    ],
)
def test_generate_target_manifest_uses_only_bundled_target_runtimes(
    target: Target,
    node: str,
) -> None:
    base = json.loads((Path(__file__).parents[1] / "mcpb" / "manifest.json").read_text(encoding="utf-8"))

    manifest = generate_target_manifest(base, target)

    assert manifest["manifest_version"] == "0.4"
    assert manifest["compatibility"] == {"claude_desktop": ">=1.0.0", "platforms": [target.mcpb_platform]}
    assert manifest["server"]["mcp_config"] == {
        "command": node,
        "args": ["${__dirname}/server/native-launcher.js"],
    }
    assert manifest["server"]["entry_point"] == "server/native-launcher.js"
    assert "user_config" not in manifest
    assert "does not bundle" not in manifest["long_description"]
    assert "bundled target runtimes" in manifest["long_description"]
    assert base["compatibility"]["platforms"] == ["darwin", "linux", "win32"]


def test_target_model_exposes_only_the_four_initial_build_slugs() -> None:
    initial = {
        Target(TargetOS.DARWIN, TargetArch.ARM64).key,
        Target(TargetOS.DARWIN, TargetArch.X64).key,
        Target(TargetOS.LINUX, TargetArch.X64).key,
        Target(TargetOS.WINDOWS, TargetArch.X64).key,
    }

    assert initial == {"darwin-arm64", "darwin-x64", "linux-x64", "windows-x64"}
    assert Target(TargetOS.LINUX, TargetArch.ARM64).is_initial_build_target is False
