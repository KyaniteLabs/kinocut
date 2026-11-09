#!/usr/bin/env python3
"""Capture reproducible MCP tool-list and input-schema-byte baselines.

Launches a Kinocut MCP server exactly the way a real client does (stdio
subprocess + initialize + tools/list), then records the advertised surface:
tool count, per-tool UTF-8 input-schema bytes, per-tool schema digests,
property names, and required parameters.

Two capture kinds:

* Repository modes (``--mode default|all|profile:<name>``) spawn
  ``python -m kinocut --mcp`` from this checkout with ``KINOCUT_TOOLS`` set
  accordingly. ``--regenerate-baseline`` rewrites the committed regression
  fixture ``tests/fixtures/mcp_tool_surface_baseline.json`` from the three
  supported repo modes (default, all, profile:editor).
* Integration captures (``--command`` / ``--arg`` / ``--env``) launch an
  arbitrary configured command — for example the exact launcher script a
  Hermes profile references — and record what that integration actually
  advertises, including its server-reported version.

Serialization contract (shared with the regression tests and the factory
tool-surface design): per tool, ``len(json.dumps(inputSchema, ensure_ascii=False,
separators=(',', ':')).encode('utf-8'))``; the mode total is the sum. This was
verified byte-identical for mcp SDK 1.28.1 and 1.30.0 (both within the pinned
``mcp>=1.28.1,<2`` range), and identical whether read from FastMCP's internal
``parameters`` or the wire ``inputSchema``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata as importlib_metadata
import json
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# Running `python scripts/mcp_surface_baseline.py` puts scripts/ (not the repo
# root) on sys.path; without this an installed kinocut would shadow the checkout.
sys.path.insert(0, str(ROOT))
BASELINE_PATH = ROOT / "tests" / "fixtures" / "mcp_tool_surface_baseline.json"
BASELINE_MODES = ("default", "all", "profile:editor")
SERIALIZATION = (
    "sum over tools of len(json.dumps(inputSchema, ensure_ascii=False, separators=(',',':')).encode('utf-8'))"
)


def canonical_schema_bytes(schema: dict[str, Any]) -> bytes:
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


async def capture_surface(
    command: list[str], env: dict[str, str], cwd: str, timeout_seconds: float = 240.0
) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # ``cwd`` must be absolute: a relative path makes the SDK's subprocess
    # teardown raise BrokenResourceError instead of the real error.
    params = StdioServerParameters(command=command[0], args=command[1:], env=env, cwd=str(Path(cwd).resolve()))
    timeout = timedelta(seconds=timeout_seconds)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, read_timeout_seconds=timeout) as session,
    ):
        init = await session.initialize()
        tools = await session.list_tools()

    rows = []
    for tool in sorted(tools.tools, key=lambda item: item.name):
        schema_bytes = canonical_schema_bytes(tool.inputSchema)
        rows.append(
            {
                "name": tool.name,
                "input_schema_bytes": len(schema_bytes),
                "input_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
                "properties": sorted((tool.inputSchema.get("properties") or {}).keys()),
                "required_params": sorted(tool.inputSchema.get("required") or []),
            }
        )
    names_digest = hashlib.sha256("\n".join(row["name"] for row in rows).encode("utf-8")).hexdigest()
    return {
        "server_info": {"name": init.serverInfo.name, "version": init.serverInfo.version},
        "tool_count": len(rows),
        "total_input_schema_bytes": sum(row["input_schema_bytes"] for row in rows),
        "tool_names_sha256": names_digest,
        "tools": rows,
    }


def repo_mode_command(mode: str) -> tuple[list[str], dict[str, str], str]:
    env = dict(os.environ)
    if mode == "default":
        env.pop("KINOCUT_TOOLS", None)
    else:
        env["KINOCUT_TOOLS"] = mode
    return [sys.executable, "-m", "kinocut", "--mcp"], env, str(ROOT)


def capture_repo_mode(mode: str) -> dict[str, Any]:
    command, env, cwd = repo_mode_command(mode)
    surface = asyncio.run(capture_surface(command, env, cwd))
    from kinocut.tool_registry import TOOL_MODULE_BY_NAME, TOOL_REGISTRY

    for row in surface["tools"]:
        row["module"] = TOOL_MODULE_BY_NAME.get(row["name"])
        row["profiles"] = list(TOOL_REGISTRY.get(row["name"], ()))
    surface["mode"] = mode
    # The committed baseline must stay portable: repo-mode servers always
    # launch from the repository root, so the launch cwd is recorded
    # repo-relative (".") instead of the absolute checkout path, which would
    # embed the operator's home directory and machine layout in a published
    # fixture. assert_portable_provenance() refuses to write anything else.
    surface["launch"] = {
        "command": command[1:],
        "env_kinocut_tools": env.get("KINOCUT_TOOLS", "<unset>"),
        "cwd": ".",
    }
    return surface


def capture_integration(command: list[str], env_overrides: dict[str, str], cwd: str | None) -> dict[str, Any]:
    env = {**os.environ, **env_overrides}
    surface = asyncio.run(capture_surface(command, env, cwd or str(ROOT)))
    surface["mode"] = "integration"
    surface["launch"] = {"command": command, "env": env_overrides, "cwd": cwd or str(ROOT)}
    return surface


def environment_block(kind: str) -> dict[str, Any]:
    try:
        kinocut_version = importlib_metadata.version("kinocut")
    except importlib_metadata.PackageNotFoundError:
        kinocut_version = "source-tree"
    # The MCP handshake reports the *installed* kinocut metadata version
    # (server_app._product_version prefers dist-info), which can differ from
    # the checkout actually launched — record both so captures stay honest.
    init_py = ROOT / "kinocut" / "__init__.py"
    source_version = None
    if init_py.is_file():
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_py.read_text(encoding="utf-8"), re.MULTILINE)
        source_version = match.group(1) if match else None
    return {
        "kind": kind,
        "git_commit": _git_commit(),
        "kinocut_metadata_version": kinocut_version,
        "kinocut_source_version": source_version,
        "mcp_sdk_version": importlib_metadata.version("mcp"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


_PERSONAL_PATH_MARKERS = ("/home/", "/Users/", "C:\\Users\\")


def _iter_strings(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_strings(value)


def assert_portable_provenance(payload: dict[str, Any]) -> None:
    """Refuse to write a committed baseline that embeds operator-specific paths.

    The fixture is a published artifact: its launch provenance must be
    repo-relative so regeneration on any machine produces identical bytes.
    Exact host paths belong only in private, uncommitted capture evidence
    (integration captures via ``--command`` are never written by this path).
    """
    home = str(Path.home()).rstrip("/")
    markers = [marker for marker in (*_PERSONAL_PATH_MARKERS, home) if marker]
    leaked = sorted({marker for marker in markers if any(marker in value for value in _iter_strings(payload))})
    if leaked:
        msg = f"baseline embeds personal path(s) {leaked}; launch provenance must stay repo-relative"
        raise ValueError(msg)
    for mode, surface in payload.get("modes", {}).items():
        cwd = surface.get("launch", {}).get("cwd")
        if cwd != ".":
            msg = f"mode {mode}: launch.cwd must be the repo-relative root '.', got {cwd!r}"
            raise ValueError(msg)


def regenerate_baseline() -> dict[str, Any]:
    modes = {mode: capture_repo_mode(mode) for mode in BASELINE_MODES}
    baseline = {
        "schema_version": 1,
        "serialization": SERIALIZATION,
        "captured": environment_block("repo-modes"),
        "note": (
            "Deterministic baseline of the repository MCP surface. Regenerate after an intentional "
            "schema change with: python scripts/mcp_surface_baseline.py --regenerate-baseline — "
            "then review the diff; the regression tests fail until the baseline is consciously updated."
        ),
        "modes": modes,
    }
    assert_portable_provenance(baseline)
    write_json(BASELINE_PATH, baseline)
    print(f"wrote {BASELINE_PATH}")
    for mode, surface in modes.items():
        print(f"  {mode}: {surface['tool_count']} tools, {surface['total_input_schema_bytes']} schema bytes")
    return baseline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", help="repository mode to capture: default, all, core, or profile:<name>")
    parser.add_argument("--command", help="exact integration command to launch (e.g. a configured launcher script)")
    parser.add_argument("--arg", action="append", default=[], help="argument appended to --command (repeatable)")
    parser.add_argument("--env", action="append", default=[], help="K=V environment override (repeatable)")
    parser.add_argument("--cwd", help="working directory for the launched server")
    parser.add_argument("--out", help="write the capture JSON to this path (default: stdout summary)")
    parser.add_argument("--regenerate-baseline", action="store_true", help="rewrite the committed regression fixture")
    args = parser.parse_args()

    if args.regenerate_baseline:
        regenerate_baseline()
        return 0
    if args.command:
        overrides = dict(item.split("=", 1) for item in args.env)
        surface = capture_integration([args.command, *args.arg], overrides, args.cwd)
        surface["captured"] = environment_block("integration")
        surface["captured_at_utc"] = datetime.now(UTC).isoformat()
    elif args.mode:
        surface = capture_repo_mode(args.mode)
        surface["captured"] = environment_block("repo-mode")
    else:
        parser.error("one of --mode, --command, or --regenerate-baseline is required")
        return 2

    if args.out:
        write_json(Path(args.out), surface)
        print(f"wrote {args.out}")
    server = surface["server_info"]
    print(
        f"{surface['mode']}: server {server['name']} v{server['version']} — "
        f"{surface['tool_count']} tools, {surface['total_input_schema_bytes']} input-schema bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
