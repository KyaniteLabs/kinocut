"""The doctor's offline rules for version probes.

A package manager resolves its package over the network, so the doctor never
runs one: a configured ``npx --yes hyperframes`` prefix is reported, not
executed. The rules live here so the doctor module stays inside its size
budget and so the rule is testable on its own.
"""

from __future__ import annotations

from typing import Any

PACKAGE_MANAGER_PREFIXES = ("npx", "npm", "pnpm", "yarn", "bunx", "bun")


def is_package_manager_prefix(prefix: list[str]) -> bool:
    """Whether a configured command starts with a package manager.

    A package manager resolves its package over the network, so the offline
    doctor never runs one.
    """
    if not prefix:
        return False
    head = prefix[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    return head in PACKAGE_MANAGER_PREFIXES


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
