"""Typed target and immutable runtime-lock contracts for MCPB builds."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from .errors import MCPBSupplyChainError


_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
_LICENSE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
_VERSIONED_ASSET_RE = re.compile(r"(?:\d+\.\d+|(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{12,})", re.IGNORECASE)
_FLOATING_CHANNELS = ("latest", "current", "nightly", "snapshot", "rolling", "unstable", "head")


class TargetOS(StrEnum):
    DARWIN = "darwin"
    LINUX = "linux"
    WINDOWS = "windows"


class TargetArch(StrEnum):
    X64 = "x64"
    ARM64 = "arm64"


class ArchiveFormat(StrEnum):
    TAR_GZ = "tar.gz"
    TAR_XZ = "tar.xz"
    ZIP = "zip"


class ArchiveLayout(StrEnum):
    ROOT = "root"
    SINGLE_DIRECTORY = "single-directory"


_KNOWN_TARGETS = {
    (TargetOS.DARWIN, TargetArch.ARM64),
    (TargetOS.DARWIN, TargetArch.X64),
    (TargetOS.LINUX, TargetArch.ARM64),
    (TargetOS.LINUX, TargetArch.X64),
    (TargetOS.WINDOWS, TargetArch.X64),
}
_INITIAL_TARGETS = _KNOWN_TARGETS - {(TargetOS.LINUX, TargetArch.ARM64)}


@dataclass(frozen=True, slots=True)
class Target:
    os: TargetOS
    arch: TargetArch

    def __post_init__(self) -> None:
        if not isinstance(self.os, TargetOS) or not isinstance(self.arch, TargetArch):
            raise MCPBSupplyChainError("MCPB target fields must use typed OS and architecture values")
        if (self.os, self.arch) not in _KNOWN_TARGETS:
            raise MCPBSupplyChainError(f"unsupported MCPB target: {self.os.value}-{self.arch.value}")

    @property
    def key(self) -> str:
        return f"{self.os.value}-{self.arch.value}"

    @property
    def mcpb_platform(self) -> str:
        return "win32" if self.os is TargetOS.WINDOWS else self.os.value

    @property
    def is_initial_build_target(self) -> bool:
        return (self.os, self.arch) in _INITIAL_TARGETS


def _https_url(value: str, field: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise MCPBSupplyChainError(f"{field} must be an HTTPS URL without credentials")
    if parsed.query or parsed.fragment:
        raise MCPBSupplyChainError(f"{field} must be an immutable HTTPS URL without query or fragment")
    lowered = parsed.path.lower()
    parts = tuple(part.lower() for part in parsed.path.split("/") if part)
    if any(part in {"main", "master"} or part.startswith(_FLOATING_CHANNELS) for part in parts) or any(
        marker in lowered for marker in ("/refs/heads/", "/tree/")
    ):
        raise MCPBSupplyChainError(f"{field} must not use a mutable latest/current path")
    if not _VERSIONED_ASSET_RE.search(parsed.path.rsplit("/", 1)[-1]):
        raise MCPBSupplyChainError(f"{field} must identify a versioned or digest-named asset")


def _safe_relative_path(value: str, field: str) -> None:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if not value or normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise MCPBSupplyChainError(f"{field} must be a safe relative path")


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    name: str
    version: str
    url: str
    sha256: str
    archive_format: ArchiveFormat
    archive_layout: ArchiveLayout
    expected_executables: tuple[str, ...]
    os: TargetOS
    arch: TargetArch
    license_id: str
    source_url: str
    source_sha256: str
    notice_paths: tuple[str, ...]
    max_download_bytes: int
    max_expanded_bytes: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not str
            for value in (
                self.name,
                self.version,
                self.url,
                self.sha256,
                self.license_id,
                self.source_url,
                self.source_sha256,
            )
        ):
            raise MCPBSupplyChainError("runtime artifact text fields must be strings")
        if not isinstance(self.archive_format, ArchiveFormat) or not isinstance(self.archive_layout, ArchiveLayout):
            raise MCPBSupplyChainError("runtime artifact archive fields must be typed values")
        if not isinstance(self.os, TargetOS) or not isinstance(self.arch, TargetArch):
            raise MCPBSupplyChainError("runtime artifact target fields must be typed values")
        if type(self.expected_executables) is not tuple or not all(
            type(item) is str for item in self.expected_executables
        ):
            raise MCPBSupplyChainError("runtime artifact expected executables must be a tuple of strings")
        if type(self.notice_paths) is not tuple or not all(type(item) is str for item in self.notice_paths):
            raise MCPBSupplyChainError("runtime artifact notice paths must be a tuple of strings")
        if not _NAME_RE.fullmatch(self.name):
            raise MCPBSupplyChainError("runtime artifact name is invalid")
        if not self.version.strip():
            raise MCPBSupplyChainError("runtime artifact version is required")
        _https_url(self.url, "runtime artifact URL")
        _https_url(self.source_url, "runtime artifact source URL")
        if not _SHA256_RE.fullmatch(self.sha256):
            raise MCPBSupplyChainError("runtime artifact SHA-256 must be 64 hexadecimal characters")
        if not _SHA256_RE.fullmatch(self.source_sha256):
            raise MCPBSupplyChainError("runtime artifact source SHA-256 must be 64 hexadecimal characters")
        if not _LICENSE_RE.fullmatch(self.license_id):
            raise MCPBSupplyChainError("runtime artifact license id is invalid")
        if not self.expected_executables:
            raise MCPBSupplyChainError("runtime artifact must declare expected executables")
        for executable in self.expected_executables:
            _safe_relative_path(executable, "expected executable")
        if not self.notice_paths:
            raise MCPBSupplyChainError("runtime artifact must declare notice paths")
        for notice in self.notice_paths:
            _safe_relative_path(notice, "notice path")
        if type(self.max_download_bytes) is not int or type(self.max_expanded_bytes) is not int:
            raise MCPBSupplyChainError("runtime artifact size bounds must be integers")
        if self.max_download_bytes <= 0 or self.max_expanded_bytes <= 0:
            raise MCPBSupplyChainError("runtime artifact size bounds must be positive")

    @property
    def target(self) -> Target:
        return Target(self.os, self.arch)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RuntimeArtifact:
        fields = {
            "name",
            "version",
            "url",
            "sha256",
            "archive_format",
            "archive_layout",
            "expected_executables",
            "os",
            "arch",
            "license_id",
            "source_url",
            "source_sha256",
            "notice_paths",
            "max_download_bytes",
            "max_expanded_bytes",
        }
        try:
            if type(value) is not dict or set(value) != fields:
                raise TypeError
            string_fields = ("name", "version", "url", "sha256", "license_id", "source_url", "source_sha256")
            if any(type(value[field]) is not str for field in string_fields):
                raise TypeError
            if type(value["expected_executables"]) is not list or not all(
                type(item) is str for item in value["expected_executables"]
            ):
                raise TypeError
            if type(value["notice_paths"]) is not list or not all(type(item) is str for item in value["notice_paths"]):
                raise TypeError
            if type(value["max_download_bytes"]) is not int or type(value["max_expanded_bytes"]) is not int:
                raise TypeError
            return cls(
                name=value["name"],
                version=value["version"],
                url=value["url"],
                sha256=value["sha256"],
                archive_format=ArchiveFormat(value["archive_format"]),
                archive_layout=ArchiveLayout(value["archive_layout"]),
                expected_executables=tuple(value["expected_executables"]),
                os=TargetOS(value["os"]),
                arch=TargetArch(value["arch"]),
                license_id=value["license_id"],
                source_url=value["source_url"],
                source_sha256=value["source_sha256"],
                notice_paths=tuple(value["notice_paths"]),
                max_download_bytes=value["max_download_bytes"],
                max_expanded_bytes=value["max_expanded_bytes"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise MCPBSupplyChainError("invalid runtime artifact lock entry") from error


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    target: Target
    artifacts: tuple[RuntimeArtifact, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target, Target)
            or type(self.artifacts) is not tuple
            or not all(isinstance(artifact, RuntimeArtifact) for artifact in self.artifacts)
        ):
            raise MCPBSupplyChainError("runtime lock fields must use typed values")
        names: set[str] = set()
        for artifact in self.artifacts:
            if artifact.name in names:
                raise MCPBSupplyChainError(f"duplicate runtime artifact: {artifact.name}")
            if artifact.target != self.target:
                raise MCPBSupplyChainError(f"runtime artifact {artifact.name} does not match target {self.target.key}")
            names.add(artifact.name)

    def artifact(self, name: str) -> RuntimeArtifact:
        for artifact in self.artifacts:
            if artifact.name == name:
                return artifact
        raise MCPBSupplyChainError(f"runtime artifact is not locked: {name}")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RuntimeLock:
        try:
            if type(value) is not dict or set(value) != {"target", "artifacts"}:
                raise TypeError
            raw_target = value["target"]
            if type(raw_target) is not dict or set(raw_target) != {"os", "arch"}:
                raise TypeError
            if type(value["artifacts"]) is not list:
                raise TypeError
            target = Target(TargetOS(raw_target["os"]), TargetArch(raw_target["arch"]))
            artifacts = tuple(RuntimeArtifact.from_dict(item) for item in value["artifacts"])
        except (KeyError, TypeError, ValueError) as error:
            raise MCPBSupplyChainError("invalid runtime lock") from error
        return cls(target, artifacts)
