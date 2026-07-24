#!/usr/bin/env python3
"""Validate and package the staged Kinocut MCPB bundle."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MCPB_DIR = ROOT / "mcpb"
VERSION = "1.10.0"
TOP_LEVEL_KEYS = {
    "$schema",
    "manifest_version",
    "name",
    "display_name",
    "version",
    "description",
    "long_description",
    "author",
    "homepage",
    "repository",
    "documentation",
    "support",
    "license",
    "keywords",
    "server",
    "user_config",
    "compatibility",
    "tools_generated",
}
CONFIG_TYPES = {"string", "number", "boolean", "directory", "file"}


def _load_manifest() -> dict[str, Any]:
    return json.loads((MCPB_DIR / "manifest.json").read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(manifest) - TOP_LEVEL_KEYS)
    if unknown:
        errors.append(f"manifest has unknown top-level keys: {', '.join(unknown)}")
    for key in ("manifest_version", "name", "version", "description", "author", "server"):
        if key not in manifest:
            errors.append(f"manifest missing required key: {key}")
    if manifest.get("manifest_version") != "0.4":
        errors.append("manifest_version must be 0.4")
    if manifest.get("name") != "kinocut":
        errors.append("name must be kinocut")
    if manifest.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    server = manifest.get("server", {})
    if server.get("type") != "node":
        errors.append("server.type must be node for the staged launcher")
    if server.get("entry_point") != "server/launcher.js":
        errors.append("server.entry_point must be server/launcher.js")
    mcp_config = server.get("mcp_config", {})
    if mcp_config.get("command") != "node":
        errors.append("server.mcp_config.command must be node")
    if mcp_config.get("args") != ["${__dirname}/server/launcher.js"]:
        errors.append("server.mcp_config.args must launch the bundle-relative launcher")
    expected_env = {
        "KINOCUT_MCPB_PYTHON": "${user_config.pythonExecutable}",
        "KINOCUT_MCPB_FFMPEG": "${user_config.ffmpegPath}",
        "MCP_VIDEO_HYPERFRAMES_COMMAND": "${user_config.hyperframesCommand}",
    }
    if mcp_config.get("env") != expected_env:
        errors.append("server.mcp_config.env must not expose unenforced root or optional-AI contracts")
    user_config = manifest.get("user_config", {})
    prohibited_config = {"workspaceRoot", "outputRoot", "enableOptionalAi"}
    prohibited_present = sorted(prohibited_config.intersection(user_config))
    if prohibited_present:
        errors.append(f"user_config has unenforced fields: {', '.join(prohibited_present)}")
    for key, config in user_config.items():
        if config.get("type") not in CONFIG_TYPES:
            errors.append(f"user_config.{key}.type is invalid")
        for required_key in ("title", "description"):
            if not config.get(required_key):
                errors.append(f"user_config.{key}.{required_key} is required")
    if manifest.get("compatibility", {}).get("runtimes") != {"node": ">=18"}:
        errors.append("compatibility.runtimes must truthfully require node >=18")
    if not (MCPB_DIR / "server" / "launcher.js").is_file():
        errors.append("server/launcher.js is missing")
    if not (MCPB_DIR / "README.md").is_file():
        errors.append("README.md is missing")
    return errors


def build_bundle(output_dir: Path) -> Path:
    manifest = _load_manifest()
    errors = validate_manifest(manifest)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = output_dir / f"kinocut-{manifest['version']}.mcpb"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (MCPB_DIR / "manifest.json", MCPB_DIR / "README.md", MCPB_DIR / "server" / "launcher.js"):
            archive.write(path, path.relative_to(MCPB_DIR).as_posix())
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist", help="Directory for the .mcpb artifact")
    args = parser.parse_args()
    bundle = build_bundle(args.output_dir)
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
