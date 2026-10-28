"""The doctor's offline rules for version probes.

A package manager resolves its package over the network, so the doctor never
runs one: a configured ``npx --yes hyperframes`` prefix is reported, not
executed. The rules live here so the doctor module stays inside its size
budget and so the rule is testable on its own.
"""

from __future__ import annotations

import re
import os
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
# A shim whose only action is to call a package manager takes the doctor
# online. The patterns match an invocation, not the word in a comment.
PACKAGE_MANAGER_INVOCATIONS = (
    r"\b(?:exec|sudo|command|nohup)\s+(?:-\S+\s+)*(?:npx|npm|pnpm|yarn|bunx|bun|uvx|uv|pipx)\b",
    r"\bnpx\s+",
    r"\bnpm\s+(?:exec|install|i|add|ci|run)\b",
    r"\b(?:pnpm|yarn|bun)\s+(?:dlx|exec|add|install|create)\b",
    r"\bbunx\s+",
    r"\buvx\s+",
    r"\bpipx\s+run\b",
)
# A file larger than this cannot be read whole, so it cannot be cleared.
MAX_INSPECTABLE_BYTES = 2 * 1024 * 1024


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


def executable_probe_refusal(path: str) -> str | None:
    """Why a resolved executable may not be run, or None when it may.

    The doctor cannot prove that a binary stays offline, so it refuses what
    it cannot read and clear: a path that is not a regular file, a file too
    large to inspect, a binary, a script with no interpreter line, and any
    file that invokes a package manager anywhere in it.
    """
    try:
        target = Path(path).resolve()
        if not target.is_file():
            return "the resolved hyperframes path is not a regular file"
        if target.stat().st_size > MAX_INSPECTABLE_BYTES:
            return "the resolved hyperframes file is too large to inspect"
        data = target.read_bytes()
    except OSError:
        return "the resolved hyperframes file could not be read"
    if b"\0" in data[:8192]:
        return "the resolved hyperframes file is a binary; the doctor does not run it"
    if not data.startswith(b"#!"):
        return "the resolved hyperframes file has no interpreter line; the doctor does not run it"
    text = data.decode("utf-8", errors="replace").lower()
    for pattern in PACKAGE_MANAGER_INVOCATIONS:
        if re.search(pattern, text):
            return "the resolved hyperframes file invokes a package manager; the doctor does not run it"
    return None


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
    """
    from .hyperframes_engine import _hyperframes_environment

    try:
        return _hyperframes_environment()
    except MCPVideoError:
        previous = os.environ.get("KINOCUT_HYPERFRAMES_TELEMETRY")
        os.environ["KINOCUT_HYPERFRAMES_TELEMETRY"] = "false"
        try:
            return _hyperframes_environment()
        finally:
            if previous is None:
                os.environ.pop("KINOCUT_HYPERFRAMES_TELEMETRY", None)
            else:
                os.environ["KINOCUT_HYPERFRAMES_TELEMETRY"] = previous


def probe_resolved_hyperframes(path: str, version_runner: Callable[[list[str]], str | None]) -> dict[str, Any]:
    """Probe a resolved Hyperframes executable, or say why it was not run.

    Nothing is executed that the doctor cannot read and clear: an unreadable
    file, a binary, a script with no interpreter line, and a file that
    invokes a package manager anywhere in it are reported, not run.
    """
    refusal = executable_probe_refusal(path)
    if refusal is not None:
        return {"hyperframes_probe_skipped": refusal}
    version = version_runner([path, "--version"])
    return {"hyperframes_version": version} if version else {}


def check_hyperframes_cli(
    which: Callable[[str], str | None],
    version_runner: Callable[[list[str]], str | None],
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
    path = prefix[0] if prefix != ["hyperframes"] else which("hyperframes")
    version = version_runner(command) if path else None
    ok = path is not None and version is not None
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
    }
