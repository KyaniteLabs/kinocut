"""Local host observations shared by diagnostics and rescue. No installs or downloads."""

from __future__ import annotations

import functools
import importlib.metadata
import importlib.util
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import FFmpegNotFoundError, FFprobeNotFoundError, ProcessingError
from .hashing import file_sha256
from .limits import DOCTOR_COMMAND_TIMEOUT
from .workflow._versions import _binary_identity


def offline_probe_environment() -> dict[str, str]:
    """The environment a version probe runs in, with a malformed setting handled.
    A malformed optional setting must not abort the whole report: telemetry off
    is the conservative reading of an invalid value.

    The process environment is never changed. The doctor's probes run in
    parallel, and a temporary write to ``os.environ`` could be observed by
    another probe halfway through.
    """
    # The only variables a version probe may see. It reads a version and
    # exits: it needs to find the program and a locale, and nothing else.
    # Everything the operator has — a token, a proxy, NODE_OPTIONS pointing
    # at a hook — is theirs, and a probe that inherits it is neither
    # credential-free nor offline.
    allowed = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "WINDIR",
        "PATHEXT",
        "COMSPEC",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(
        {
            "HYPERFRAMES_SKIP_SKILLS": "1",
            "HYPERFRAMES_NO_UPDATE_CHECK": "1",
            "HYPERFRAMES_NO_TELEMETRY": "1",
            "VITE_HYPERFRAMES_NO_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
        }
    )
    return environment


def _run_probe(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=DOCTOR_COMMAND_TIMEOUT,
        env=offline_probe_environment(),
    )


def _command_version(command: list[str]) -> str | None:
    """Run a bounded probe in a sanitized, update-disabled environment."""
    try:
        result = _run_probe(command)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    first_line = (result.stdout or result.stderr).splitlines()[0:1]
    return first_line[0].strip() if first_line else None


def _package_version(distribution_name: str) -> str | None:
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return None


@functools.lru_cache(maxsize=16)
def _sha256_file_stat_cached(path: Path, identity: tuple) -> str:
    digest = file_sha256(path)
    if _binary_identity(str(path)) != identity:
        raise OSError("Local weights changed during the probe")
    return digest


def cached_sha256_file(path: Path) -> str:
    """SHA-256 of ``path``, cached by filesystem identity so doctor avoids re-hashing ~1 GB weights."""
    identity = _binary_identity(str(path))
    if identity is None:
        raise OSError("Local weights are unavailable")
    return _sha256_file_stat_cached(path, identity)


@functools.lru_cache(maxsize=4)
def _probe_ffmpeg_filters(executable: str, identity: tuple) -> frozenset[str]:
    result = _run_probe([executable, "-hide_banner", "-filters"])
    if result.returncode != 0 or _binary_identity(executable) != identity:
        raise ProcessingError(
            "FFmpeg filter discovery", result.returncode, "", reason="Filter probe failed or executable changed"
        )
    filters: set[str] = set()
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 3 and re.fullmatch(r"[.T][.S](?:[.C])?", columns[0]) and "->" in columns[2]:
            filters.add(columns[1])
    return frozenset(filters)


def _ffmpeg_filters(executable: str) -> frozenset[str]:
    identity = _binary_identity(executable)
    if identity is None:
        return frozenset()
    try:
        return _probe_ffmpeg_filters(executable, identity)
    except (OSError, subprocess.SubprocessError, ProcessingError):
        return frozenset()


def _runtime_executable(name: str) -> str | None:
    if name not in {"ffmpeg", "ffprobe"}:
        return shutil.which(name)
    from .engine_runtime_utils import _ffmpeg, _ffprobe

    try:
        return _ffmpeg() if name == "ffmpeg" else _ffprobe()
    except (FFmpegNotFoundError, FFprobeNotFoundError):
        return None


def whisper_model_path(model: str = "base") -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache / "whisper" / f"{model}.pt"


def local_digest(path: Path) -> str | None:
    try:
        return "sha256:" + cached_sha256_file(path) if path.is_file() else None
    except OSError:
        return None


@dataclass(frozen=True)
class HostProbes:
    """Host observations; runners receive resolved executables unless using Doctor's legacy callback."""

    which: Callable[[str], str | None] = _runtime_executable
    version_runner: Callable[[list[str]], str | None] = _command_version
    find_spec: Callable[[str], Any] = field(default_factory=lambda: importlib.util.find_spec)
    package_version: Callable[[str], str | None] = _package_version
    import_module: Callable[[str], Any] = importlib.import_module
    legacy_command_runner: Callable[[list[str]], str | None] | None = None
    filters: Callable[[str], frozenset[str]] = _ffmpeg_filters
    model_path: Callable[[str], Path] = whisper_model_path
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    home: Callable[[], Path] = field(default_factory=lambda: Path.home)
    cwd: Callable[[], Path] = field(default_factory=lambda: Path.cwd)

    def workspace(self) -> tuple[Path, bool, bool, int | None]:
        path = self.cwd()
        try:
            return path, os.access(path, os.R_OK), os.access(path, os.W_OK), shutil.disk_usage(path).free
        except OSError:
            return path, False, False, None

    def matte_weights(self) -> tuple[Path, bool, str | None]:
        from .validation import OBJECT_MATTE_WEIGHTS_BYTES, object_matte_cache_path

        path = object_matte_cache_path()
        try:
            cached = path.is_file()
            digest = cached_sha256_file(path) if cached and path.stat().st_size == OBJECT_MATTE_WEIGHTS_BYTES else None
        except OSError:
            return path, False, None
        return path, cached, digest

    def crush_sources(self) -> Path | None:
        from .engine_glitch_shader import _resolve_crush_path

        path = Path(_resolve_crush_path())
        return path if (path / "common.glsl").is_file() else None

    def tool_mode(self) -> str:
        from .tool_registry import active_mode

        return active_mode()

    def command_version(self, command: list[str], executable: str) -> str | None:
        if self.legacy_command_runner is not None:
            return self.legacy_command_runner(command)
        identity = _binary_identity(executable)
        value = self.version_runner([executable, *command[1:]])
        return value if identity == _binary_identity(executable) else None


#: The report fields that name something of this machine: a path, the
#: command a probe would run — which for Hyperframes is the operator's
#: own configuration, not ours to publish — or a URL that points at one.
MACHINE_FIELDS = ("path", "origin", "executable", "command", "base_url")


def _strip_machine_fields(value: Any) -> Any:
    """Remove machine data from a structure, at every depth."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in MACHINE_FIELDS and item:
                cleaned[f"{key}_present"] = True
                continue
            cleaned[key] = _strip_machine_fields(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_machine_fields(item) for item in value]
    return value


def without_machine_paths(report: dict[str, Any]) -> dict[str, Any]:
    """Say that a path exists, not where it is.

    The report travels to whoever asked for it, so the removal goes all the
    way down: a path nested inside a check's details is still a path.
    """
    return _strip_machine_fields(report)
