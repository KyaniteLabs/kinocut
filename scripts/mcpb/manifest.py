"""Generate MCPB v0.4 manifests for self-contained runtime targets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import MCPBSupplyChainError
from .model import Target, TargetOS


def _node_path(target: Target) -> str:
    root = "${__dirname}/runtime"
    if target.os is TargetOS.WINDOWS:
        return f"{root}/node/node.exe"
    return f"{root}/node/bin/node"


def generate_target_manifest(base: dict[str, Any], target: Target) -> dict[str, Any]:
    """Return a target-specific manifest that references only bundled runtimes."""
    if base.get("manifest_version") != "0.4":
        raise MCPBSupplyChainError("target manifest generation requires MCPB manifest_version 0.4")
    manifest = deepcopy(base)
    compatibility = deepcopy(manifest.get("compatibility", {}))
    compatibility.pop("runtimes", None)
    compatibility["platforms"] = [target.mcpb_platform]
    manifest["compatibility"] = compatibility
    manifest["server"]["mcp_config"] = {
        "command": _node_path(target),
        "args": ["${__dirname}/server/native-launcher.js"],
    }
    manifest["server"]["entry_point"] = "server/native-launcher.js"
    manifest.pop("user_config", None)
    manifest["long_description"] = (
        "Kinocut exposes local video editing, analysis, workflow, rescue, and repurposing tools over MCP stdio. "
        f"This {target.key} package launches with bundled target runtimes; optional AI and Hyperframes integrations "
        "remain capability-gated and are not included."
    )
    return manifest
