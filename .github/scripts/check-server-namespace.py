#!/usr/bin/env python3
"""
check-server-namespace.py — HR-NOV-1 / HR-NOV-2 hardening control.

Hardens the legacy io.github.KyaniteLabs/* namespace against out-of-cycle
publishes per Security ruling t_9f514ee8 (R4). Scans every server.json
in the checkout and rejects any whose `name` matches the legacy namespace
pattern. Canonical tech.kyanitelabs/* names are explicitly allowed.

Scope (per Security addendum to t_eccfa7a5, 2026-10-14 19:27):
  DENY  : io.github.KyaniteLabs/(kinocut|dialectos|mcp-video|Epoch)
  ALLOW : tech.kyanitelabs/(kinocut|dialectos|mcp-video|Epoch)

The deny regex matches io.github.KyaniteLabs/* but NOT tech.kyanitelabs/*
(the namespaces share a dot-separated form but the leading segment
"io.github.KyaniteLabs" is unique to the legacy namespace). A safety
assertion below proves the denylist is namespace-scoped.

Exit codes:
  0  all server.json files are namespace-OK (PASS)
  1  at least one server.json has a legacy io.github.KyaniteLabs/* name
  2  invalid usage (no server.json found, malformed file, etc.)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Legacy namespace pattern. Anchored at start of string. Explicit branch
# for each legacy name so future entries can be added with surgical
# review. Case-sensitive — the registry treats KyaniteLabs vs epoch
# case as significant.
LEGACY_NAMESPACE_RE = re.compile(
    r"^io\.github\.KyaniteLabs/"
    r"(?:kinocut|dialectos|mcp-video|Epoch)$"
)

# Canonical namespace. Listed for the safety assertion; the denylist
# MUST NOT match this pattern under any circumstance (per Security
# addendum: "denylist regex must NOT match the tech.* namespace").
CANONICAL_NAMESPACE_RE = re.compile(
    r"^tech\.kyanitelabs/"
    r"(?:kinocut|dialectos|mcp-video|Epoch)$"
)

# Files to skip. Subdirectory name in the variable just keeps the
# search honest about what it is inspecting.
IGNORED_DIRS = {".git", "node_modules", "__pycache__", "release-dist", "npm-dist"}


def find_server_json_files(root: Path) -> list[Path]:
    """Return every server.json in the tree, excluding junk dirs."""
    found: list[Path] = []
    for path in root.rglob("server.json"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        found.append(path)
    return sorted(found)


def check_file(path: Path) -> tuple[str, str]:
    """Return (status, message). status is 'OK', 'ERROR', or 'LEGACY'."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return ("ERROR", f"could not parse JSON: {exc}")
    name = data.get("name")
    if not isinstance(name, str):
        return ("ERROR", "no `name` field or not a string")
    if LEGACY_NAMESPACE_RE.match(name):
        return (
            "LEGACY",
            f"server.json `name` is in the legacy io.github.KyaniteLabs/* namespace: {name!r}",
        )
    return ("OK", f"name={name!r}")


def safety_assertion() -> None:
    """Prove the denylist regex is namespace-scoped (Security addendum)."""
    # Positive control: must match the four legacy names.
    for legacy in ("io.github.KyaniteLabs/kinocut",
                   "io.github.KyaniteLabs/dialectos",
                   "io.github.KyaniteLabs/mcp-video",
                   "io.github.KyaniteLabs/Epoch"):
        if not LEGACY_NAMESPACE_RE.match(legacy):
            raise SystemExit(f"denylist regression: failed to match {legacy!r}")
    # Negative control: must NOT match the four canonical names.
    for canonical in ("tech.kyanitelabs/kinocut",
                      "tech.kyanitelabs/dialectos",
                      "tech.kyanitelabs/mcp-video",
                      "tech.kyanitelabs/Epoch"):
        if LEGACY_NAMESPACE_RE.match(canonical):
            raise SystemExit(f"denylist regression: matched canonical name {canonical!r}")
        if not CANONICAL_NAMESPACE_RE.match(canonical):
            raise SystemExit(f"canonical regex regression: failed to match {canonical!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=".",
        help="root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--required",
        action="store_true",
        help="treat zero server.json files found as a failure",
    )
    args = parser.parse_args()

    # The safety assertion runs every invocation so a regex edit can't
    # silently widen the deny set to the canonical namespace.
    safety_assertion()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root does not exist: {root}", file=sys.stderr)
        return 2

    server_jsons = find_server_json_files(root)
    if not server_jsons:
        msg = f"no server.json found under {root}"
        if args.required:
            print(f"FAIL: {msg}", file=sys.stderr)
            return 1
        print(f"PASS: {msg}")
        return 0

    legacy_hits: list[tuple[Path, str, str]] = []
    for path in server_jsons:
        status, detail = check_file(path)
        rel = path.relative_to(root)
        if status == "OK":
            print(f"PASS {rel}  {detail}")
        elif status == "ERROR":
            print(f"FAIL {rel}  {detail}", file=sys.stderr)
            legacy_hits.append((path, status, detail))
        else:  # LEGACY
            print(f"FAIL {rel}  {detail}", file=sys.stderr)
            legacy_hits.append((path, status, detail))

    if legacy_hits:
        print(
            f"\nFAIL: {len(legacy_hits)} server.json file(s) carry a legacy "
            f"io.github.KyaniteLabs/* name. The Nov 1.17.0 deprecation cycle "
            f"requires all server.json `name` fields to use the canonical "
            f"tech.kyanitelabs/* namespace. Migration is the package-surface "
            f"path; out-of-cycle publishes to the legacy namespace are "
            f"denied by HR-NOV-1 / HR-NOV-2 (Security ruling t_9f514ee8 R4).",
            file=sys.stderr,
        )
        return 1

    print(f"\nPASS: {len(server_jsons)} server.json file(s) are namespace-OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
