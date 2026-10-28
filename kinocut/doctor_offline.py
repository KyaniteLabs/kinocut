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
# Shells and interpreters that can run anything — including a package
# manager — so a command that opens with one is never executed offline.
WRAPPER_PREFIXES = (
    "env",
    "sh",
    "bash",
    "zsh",
    "dash",
    "ksh",
    "cmd",
    "powershell",
    "pwsh",
    "python",
    "python3",
    "node",
    "sudo",
    "nohup",
    "time",
    "xargs",
)


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


def is_wrapper_prefix(prefix: list[str]) -> bool:
    """Whether the command opens with a shell or an interpreter."""
    if not prefix:
        return False
    return _basename(prefix[0]) in WRAPPER_PREFIXES


def script_invokes_package_manager(path: str) -> bool:
    """Whether a resolved script would run a package manager.

    A PATH entry can be a shim whose only action is to call ``npx``; running
    it would take the doctor online, so the shim is read instead of executed.
    """
    try:
        target = Path(path).resolve()
        if not target.is_file():
            return False
        with target.open("rb") as handle:
            head = handle.read(8192)
    except OSError:
        return False
    if not head.startswith(b"#!"):
        return False
    text = head.decode("utf-8", errors="replace").lower()
    return any(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) for name in PACKAGE_MANAGER_PREFIXES)


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
    """The finding for a configured probe that opens with a shell."""
    finding = package_manager_probe_refusal(command, env_name)
    finding["install_hint"] = (
        "The configured Hyperframes command opens with a shell or interpreter, which can run "
        f"anything including a package manager. The doctor does not run it. Point {env_name} "
        "at the resolved binary, or install Hyperframes on PATH."
    )
    return finding


def offline_probe_refusal(prefix: list[str], command: list[str], env_name: str) -> dict[str, Any] | None:
    """The refusal for a configured command the offline doctor will not run."""
    if is_package_manager_prefix(prefix):
        return package_manager_probe_refusal(command, env_name)
    if is_wrapper_prefix(prefix):
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

    A PATH shim whose only action is to call a package manager would take the
    probe online, so the shim is read rather than executed.
    """
    if script_invokes_package_manager(path):
        return {
            "hyperframes_probe_skipped": "the resolved hyperframes shim invokes a package manager; doctor stays offline"
        }
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
