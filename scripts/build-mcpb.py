#!/usr/bin/env python3
"""Validate and package the staged Kinocut MCPB bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MCPB_DIR = ROOT / "mcpb"
VERSION = "1.15.1"
MEMBERS = ("README.md", "manifest.json", "server/launcher.js")
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


def _load_manifest(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or MCPB_DIR / "manifest.json").read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any], *, check_sources: bool = True) -> list[str]:
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
    if server.get("type") != "node" or server.get("entry_point") != "server/launcher.js":
        errors.append("server must use the staged Node launcher")
    mcp_config = server.get("mcp_config", {})
    if mcp_config.get("command") != "node" or mcp_config.get("args") != ["${__dirname}/server/launcher.js"]:
        errors.append("server.mcp_config must launch the bundle-relative launcher")
    expected_env = {
        "KINOCUT_MCPB_PYTHON": "${user_config.pythonExecutable}",
        "KINOCUT_MCPB_FFMPEG": "${user_config.ffmpegPath}",
        "MCP_VIDEO_HYPERFRAMES_COMMAND": "${user_config.hyperframesCommand}",
    }
    if mcp_config.get("env") != expected_env:
        errors.append("server.mcp_config.env must not expose unenforced root or optional-AI contracts")
    user_config = manifest.get("user_config", {})
    prohibited_present = sorted({"workspaceRoot", "outputRoot", "enableOptionalAi"}.intersection(user_config))
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
    if check_sources:
        for name in MEMBERS:
            if not (MCPB_DIR / name).is_file():
                errors.append(f"{name} is missing")
    return errors


def _checked_source(name: str) -> Path:
    root = MCPB_DIR.resolve(strict=True)
    source = MCPB_DIR / name
    if source.is_symlink() or not source.is_file() or not stat.S_ISREG(source.stat(follow_symlinks=False).st_mode):
        raise ValueError(f"MCPB source must be a regular non-symlink: {name}")
    try:
        source.resolve(strict=True).relative_to(root)
    except ValueError as exc:
        raise ValueError(f"MCPB source escapes its root: {name}") from exc
    return source


def _safe_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or name not in MEMBERS:
        raise ValueError(f"unsafe or unlisted MCPB archive member: {name}")
    mode = (info.external_attr >> 16) & 0o170000
    if mode not in {0, stat.S_IFREG} or info.is_dir():
        raise ValueError(f"MCPB archive member is not a regular file: {name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_sha() -> str:
    configured = os.environ.get("GITHUB_SHA", "")
    if len(configured) == 40 and all(char in "0123456789abcdef" for char in configured.lower()):
        return configured.lower()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else "unbound"


def audit_bundle(bundle: Path, *, source_sha: str | None = None, source_manifest_valid: bool = False) -> dict[str, Any]:
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("MCPB archive contains a duplicate member")
        for info in infos:
            _safe_member(info)
        if sorted(names) != sorted(MEMBERS):
            raise ValueError("MCPB archive inventory does not match the staged three-file product")
        try:
            packed_manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("MCPB archive manifest is invalid JSON") from exc
    errors = validate_manifest(packed_manifest, check_sources=False)
    if errors:
        raise ValueError("MCPB archive manifest failed Kinocut invariants: " + "; ".join(errors))
    return {
        "artifact_kind": "mcpb_build_receipt",
        "source_sha": source_sha or _source_sha(),
        "archive_sha256": _sha256(bundle),
        "archive_inventory": sorted(names),
        "source_manifest_valid": source_manifest_valid,
        "extracted_manifest_valid": True,
        "official_validation": "not_run",
    }


def build_bundle(output_dir: Path) -> Path:
    manifest = _load_manifest()
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("MCPB source manifest failed Kinocut invariants: " + "; ".join(errors))
    sources = [(name, _checked_source(name)) for name in MEMBERS]
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = output_dir / f"kinocut-{manifest['version']}.mcpb"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, source in sources:
            archive.write(source, name)
    receipt = audit_bundle(bundle, source_manifest_valid=True)
    (output_dir / "mcpb-build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        bundle = build_bundle(args.output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
