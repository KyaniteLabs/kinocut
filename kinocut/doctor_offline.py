"""The doctor's offline rules for version probes.

The doctor executes nothing that can reach the network. A package manager
resolves its package over the network, and a resolved script can reach it
whatever its source says — reading a script does not prove that it is
offline. So the doctor reports what it finds and reads versions from the
installed package's metadata on disk.
"""

from __future__ import annotations

import os
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import MCPVideoError

PACKAGE_MANAGER_PREFIXES = ("npx", "npm", "pnpm", "yarn", "bunx", "bun")
# Windows resolves the same tools as `npx.cmd`, `npm.cmd` and so on, so the
# executable suffix is stripped before the name is compared.
WINDOWS_EXECUTABLE_SUFFIXES = (".cmd", ".exe", ".bat", ".ps1")
# Only the Hyperframes executable itself is probed. A shell, an interpreter
# or a package manager can run anything, and an allowlist of their names
# would always be incomplete, so the rule is inverted instead.
DIRECT_EXECUTABLE_NAME = "hyperframes"
# The manifest that owns the Hyperframes executable. A manifest with any
# other name is somebody else's package, and its version is not evidence
# about Hyperframes.
HYPERFRAMES_PACKAGE_NAMES = frozenset({"hyperframes", "@hyperframes/cli"})


def _basename(token: str) -> str:
    """The comparable name of an executable token, path and suffix removed."""
    head = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in WINDOWS_EXECUTABLE_SUFFIXES:
        if head.endswith(suffix):
            head = head[: -len(suffix)]
            break
    return head


def is_package_manager_prefix(prefix: list[str]) -> bool:
    """Whether any token in the configured command is a package manager.

    The whole argv is inspected: ``env npx --yes hyperframes`` reaches the
    network through its second token, not its first. A package manager
    resolves its package over the network, so the offline doctor never runs
    one.
    """
    return any(_basename(token) in PACKAGE_MANAGER_PREFIXES for token in prefix)


def is_direct_executable_command(prefix: list[str]) -> bool:
    """Whether the command names the Hyperframes executable itself.

    Only the direct executable is probed. Everything else — a shell, an
    interpreter, a package manager, a wrapper of any kind — is refused,
    because the doctor cannot know what such a command will run.
    """
    if not prefix:
        return False
    return _basename(prefix[0]) == DIRECT_EXECUTABLE_NAME


def hyperframes_version_from_metadata(path: str) -> str | None:
    """The installed package's version, read from disk without running it.

    The version comes from the nearest ``package.json`` above the resolved
    path. Reading a file is not executing anything, so it cannot phone home.
    """
    try:
        target = Path(path).resolve()
    except OSError:
        return None
    for parent in list(target.parents)[:6]:
        manifest = parent / "package.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        name = data.get("name")
        if not isinstance(name, str) or name not in HYPERFRAMES_PACKAGE_NAMES:
            return None
        version = data.get("version")
        if isinstance(version, str) and version:
            return version
    return None


def resolve_executable(path: str | None) -> str | None:
    """The path only when it is a regular, executable file.

    A configured command can name a file that is not there. Reporting that
    as present would tell the operator a tool is installed when it is not.
    """
    if not path:
        return None
    try:
        candidate = Path(path).resolve()
    except OSError:
        return None
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return None
    return str(candidate)


def package_manager_probe_refusal(command: list[str], env_name: str) -> dict[str, Any]:
    """The finding for a configured probe the offline doctor will not run."""
    return {
        "name": "hyperframes",
        "category": "hyperframes",
        "required": False,
        "ok": False,
        "path": None,
        "version": None,
        "command": command,
        "install_hint": (
            "The configured Hyperframes command starts with a package manager, which resolves "
            f"packages over the network. The doctor does not run it. Point {env_name} at the "
            "resolved binary, or install Hyperframes on PATH."
        ),
    }


def wrapper_probe_refusal(command: list[str], env_name: str) -> dict[str, Any]:
    """The finding for a configured probe that is not the executable itself."""
    finding = package_manager_probe_refusal(command, env_name)
    finding["install_hint"] = (
        "The configured Hyperframes command does not name the Hyperframes executable itself. "
        "A shell, an interpreter or a package manager can run anything, and the doctor does not "
        f"run it. Point {env_name} at the resolved binary, or install Hyperframes on PATH."
    )
    return finding


def offline_probe_refusal(prefix: list[str], command: list[str], env_name: str) -> dict[str, Any] | None:
    """The refusal for a configured command the offline doctor will not run."""
    if is_package_manager_prefix(prefix):
        return package_manager_probe_refusal(command, env_name)
    if not is_direct_executable_command(prefix):
        return wrapper_probe_refusal(command, env_name)
    return None


def offline_probe_environment() -> dict[str, str]:
    """The environment a version probe runs in, with a malformed setting handled.
    A malformed optional setting must not abort the whole report: telemetry off
    is the conservative reading of an invalid value.

    The process environment is never changed. The doctor's probes run in
    parallel, and a temporary write to ``os.environ`` could be observed by
    another probe halfway through.
    """
    from .hyperframes_engine import _hyperframes_environment

    try:
        return _hyperframes_environment()
    except MCPVideoError:
        return _hyperframes_environment(telemetry_allowed=False)


def report_resolved_hyperframes(path: str) -> dict[str, Any]:
    """Report the resolved Hyperframes executable without running it.

    A resolved script can reach the network whatever its source says, and
    the doctor cannot prove otherwise, so it does not run one. The version
    comes from the installed package's metadata, read from disk.
    """
    version = hyperframes_version_from_metadata(path)
    if version:
        return {
            "hyperframes_version": version,
            "hyperframes_version_source": "package metadata, read from disk",
        }
    return {
        "hyperframes_probe_skipped": (
            "the doctor does not execute a resolved hyperframes script; "
            "its version is not read from the script's output"
        )
    }


def check_hyperframes_cli(
    which: Callable[[str], str | None],
) -> dict[str, Any]:
    """Report the Hyperframes CLI without running anything that can phone home."""
    from .errors import HyperframesNotFoundError
    from .hyperframes_engine import HYPERFRAMES_COMMAND_ENV, _hyperframes_command_prefix

    try:
        prefix = _hyperframes_command_prefix(which=which)
    except HyperframesNotFoundError:
        prefix = ["hyperframes"]
    command = [*prefix, "--version"]
    refusal = offline_probe_refusal(prefix, command, HYPERFRAMES_COMMAND_ENV)
    if refusal is not None:
        return refusal
    # The executable is the first element of the prefix. A bare name is
    # looked up on PATH, the way a shell would; a path is resolved as one.
    executable = prefix[0]
    located = executable if ("/" in executable or os.sep in executable) else which(executable)
    path = resolve_executable(located)
    extra = report_resolved_hyperframes(path) if path else {}
    version = extra.get("hyperframes_version")
    ok = path is not None
    return {
        "name": "hyperframes",
        "category": "hyperframes",
        "required": False,
        "ok": ok,
        "path": path,
        "version": version,
        "command": command,
        "install_hint": None
        if ok
        else (f"Install a pinned Hyperframes package, add hyperframes to PATH, or set {HYPERFRAMES_COMMAND_ENV}."),
        **extra,
    }
