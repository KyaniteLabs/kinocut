"""Byte-level regression baseline for the MCP tool surface.

Pins the committed fixture ``tests/fixtures/mcp_tool_surface_baseline.json``
(captured at 2cf76e98 / 1.16.5 by ``scripts/mcp_surface_baseline.py``) against
three independent re-derivations:

1. in-process registration (FastMCP internal surface),
2. a real stdio client handshake (the wire bytes registries and clients see),
3. the declarative registry tables in ``kinocut.tool_registry``.

Serialization contract shared with the capture script: per tool,
``len(json.dumps(input_schema, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))``
summed per mode. Verified byte-identical for mcp SDK 1.28.1 and 1.30.0 (the
pinned range is ``mcp>=1.28.1,<2``) and identical between FastMCP's internal
``parameters`` and the wire ``inputSchema``.

If these tests fail after an *intentional* schema change, regenerate the
fixture with ``python scripts/mcp_surface_baseline.py --regenerate-baseline``
and review the diff — the failure is the point: every schema byte change on
the 1.16.5 surface must be a conscious, reviewed edit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from kinocut.server import mcp
from kinocut.tool_registry import (
    CORE_TOOLS,
    MODULE_PROFILE_TAGS,
    TOOL_MODULE_BY_NAME,
    TOOL_NAMES_BY_MODULE,
    TOOL_REGISTRY,
    configure_tool_surface,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "tests" / "fixtures" / "mcp_tool_surface_baseline.json"
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
MODES = ("default", "all", "profile:editor")


def canonical_schema_bytes(schema: dict) -> bytes:
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@pytest.fixture(autouse=True)
def _restore_full_surface():
    """Keep the session-wide full catalog intact regardless of test outcome."""
    yield
    configure_tool_surface("all")


def _in_process_surface(mode: str) -> dict[str, tuple[int, str]]:
    # The default mode is selected by an empty (or "core") selector — the
    # literal string "default" is not a valid KINOCUT_TOOLS value.
    configure_tool_surface("" if mode == "default" else mode)
    tools = asyncio.run(mcp.list_tools())
    return {
        tool.name: (
            len(canonical_schema_bytes(tool.inputSchema)),
            hashlib.sha256(canonical_schema_bytes(tool.inputSchema)).hexdigest(),
        )
        for tool in tools
    }


def _baseline_surface(mode: str) -> dict[str, tuple[int, str]]:
    return {
        row["name"]: (row["input_schema_bytes"], row["input_schema_sha256"]) for row in BASELINE["modes"][mode]["tools"]
    }


def _fixture_strings(node: object):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _fixture_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _fixture_strings(value)


def _mismatches(actual: dict[str, tuple[int, str]], expected: dict[str, tuple[int, str]]) -> list[str]:
    problems = []
    for name in sorted(set(actual) | set(expected)):
        if name not in actual:
            problems.append(f"{name}: missing from live surface")
        elif name not in expected:
            problems.append(f"{name}: not in baseline")
        elif actual[name] != expected[name]:
            problems.append(f"{name}: baseline {expected[name]} != live {actual[name]}")
    return problems


# --- fixture integrity -----------------------------------------------------------


def test_baseline_fixture_is_wellformed():
    assert BASELINE["schema_version"] == 1
    assert set(BASELINE["modes"]) == set(MODES)
    for mode in MODES:
        surface = BASELINE["modes"][mode]
        rows = surface["tools"]
        assert [row["name"] for row in rows] == sorted(row["name"] for row in rows), mode
        assert surface["tool_count"] == len(rows), mode
        assert surface["total_input_schema_bytes"] == sum(row["input_schema_bytes"] for row in rows), mode
        assert all(len(row["input_schema_sha256"]) == 64 for row in rows), mode
        names = "\n".join(row["name"] for row in rows).encode("utf-8")
        assert surface["tool_names_sha256"] == hashlib.sha256(names).hexdigest(), mode


def test_headline_baseline_numbers_are_pinned():
    """The one-screen numbers every doc and design decision quotes.

    default 30 tools / 24,281 B (20-tool core diet + the 10 compact-surface
    tools added by the typed operation families: 8 dispatchers,
    list_operations, describe_operation); all 205 tools / 126,776 B — the
    legacy full-catalog surface, byte-identical since 2cf76e98;
    profile:editor 118 tools / 81,747 B. Regenerated after the compact
    surface landed; the all-mode rows are unchanged down to per-tool digests.
    #679 then added an optional ``profile`` input to video_quality_check and
    video_release_checkpoint: default 24,347 B, all 126,908 B, editor 81,813 B.
    The hot-path diet then cut the direct core from 20 tools to 8 (every
    dropped tool stays reachable through its family dispatcher): default
    18 tools / 17,429 B, editor 114 tools / 80,152 B; all-mode unchanged.
    Dropping the titles pydantic derives from property names (and the
    "<name>Arguments" schema title) then cut every mode: default 15,335 B,
    all 98,000 B, editor 63,857 B. Same properties, types and validation.
    Moving Args help onto each parameter (#719) grew the schemas: default
    17,021 B, all 128,297 B, editor 87,550 B (tools/list itself shrank).
    Shorter family dispatcher text then cut default to 16,373 B and editor
    to 86,902 B (all unchanged: it carries no family tools).
    A shorter overwrite description (on every mutating tool) then cut
    default to 15,563 B, all to 119,072 B and editor to 81,772 B.
    Trimming direct-tool descriptions moved one note (exact is slower) into
    its parameter: default 15,603 B, all 119,112 B, editor 81,812 B.
    Read-only tools then stopped offering overwrite consent: default
    15,200 B, all 118,911 B, editor 81,409 B.
    Trimming the longest remaining texts (family params, position, trim,
    merge, extract_frame) then cut default to 14,739 B, all to 118,736 B
    and editor to 80,922 B.
    video_review_card (#723) then added one family operation: default
    14,759 B, all 206 tools / 119,053 B, editor 115 tools / 81,259 B.
    video_release_checkpoint's profile_reason (#771) then grew all to 119,131 B.
    """
    assert BASELINE["captured"]["git_commit"] == "1affa2e236084ce3679340139a700faeeb9b9a0e"
    for mode, count, total in (("default", 18, 14_759), ("all", 206, 119_131), ("profile:editor", 115, 81_259)):
        assert BASELINE["modes"][mode]["tool_count"] == count, mode
        assert BASELINE["modes"][mode]["total_input_schema_bytes"] == total, mode


def test_baseline_fixture_provenance_is_portable():
    """Committed provenance must never embed operator home/worktree paths.

    The fixture is a published artifact (Kinocut receipt hygiene: no home
    paths, no usernames), so ``launch.cwd`` is recorded repo-relative — "." is
    the repository root the server launches from — and regeneration on any
    machine must produce identical bytes. Exact host paths belong only in
    private, uncommitted capture evidence. The generator's
    ``assert_portable_provenance`` guard enforces the same rule at write time.
    """
    raw = BASELINE_PATH.read_text(encoding="utf-8")
    for marker in ("/home/", "/Users/", "C:\\Users\\"):
        assert marker not in raw, marker
    home = str(Path.home()).rstrip("/")
    if home:
        for value in _fixture_strings(BASELINE):
            assert not value.startswith(home), value
    for mode in MODES:
        launch = BASELINE["modes"][mode]["launch"]
        assert launch["cwd"] == ".", (mode, launch["cwd"])
        assert not os.path.isabs(launch["cwd"]), (mode, launch["cwd"])


# --- re-derivation 1: in-process registration ------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_in_process_surface_matches_baseline_byte_for_byte(mode):
    assert _mismatches(_in_process_surface(mode), _baseline_surface(mode)) == [], (
        f"{mode}: live input schemas drifted from the committed baseline — if the change is "
        "intentional, regenerate with `python scripts/mcp_surface_baseline.py --regenerate-baseline` "
        "and review the diff"
    )


# --- re-derivation 2: real stdio client (the bytes clients see) -------------------


def _stdio_surface(mode: str) -> tuple[int, int, list[str]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def capture() -> tuple[int, int, list[str]]:
        from mcp.client.stdio import get_default_environment

        if mode == "default":
            # Hermetic by construction: build the SDK's safe allowlist
            # environment explicitly and select the default mode by hand, so
            # an ambient KINOCUT_TOOLS on the test host can never change what
            # "default" measures (the allowlist never carries KINOCUT_TOOLS
            # or PYTHONPATH; "" selects the default mode exactly like unset).
            env = get_default_environment() | {"KINOCUT_TOOLS": ""}
        else:
            env = {**os.environ, "KINOCUT_TOOLS": mode}
        params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut", "--mcp"], env=env)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
        names = sorted(tool.name for tool in tools.tools)
        total = sum(len(canonical_schema_bytes(tool.inputSchema)) for tool in tools.tools)
        return len(names), total, names

    return asyncio.run(capture())


@pytest.mark.parametrize("mode,count,total", [("default", 18, 14_759), ("all", 206, 119_131)])
def test_stdio_wire_surface_matches_baseline(mode, count, total):
    wire_count, wire_total, names = _stdio_surface(mode)
    baseline = BASELINE["modes"][mode]
    assert wire_count == count == baseline["tool_count"], mode
    assert wire_total == total == baseline["total_input_schema_bytes"], mode
    assert names == [row["name"] for row in baseline["tools"]], mode


def test_stdio_wire_default_surface_is_the_core_diet_plus_family_tools():
    _, _, names = _stdio_surface("default")
    from kinocut.tool_families import FAMILY_SURFACE_TOOLS

    assert names == sorted(set(CORE_TOOLS) | set(FAMILY_SURFACE_TOOLS))


# --- re-derivation 3: declarative registry inventory ------------------------------


def test_registry_inventory_is_complete_and_unambiguous():
    all_names = [name for names in TOOL_NAMES_BY_MODULE.values() for name in names]
    assert len(TOOL_NAMES_BY_MODULE) == 25
    assert len(all_names) == 206 == len(set(all_names)), "a tool name must live in exactly one module"
    assert set(TOOL_MODULE_BY_NAME) == set(all_names) == set(TOOL_REGISTRY)
    assert set(MODULE_PROFILE_TAGS) == set(TOOL_NAMES_BY_MODULE)


def test_registry_core_table_matches_default_surface():
    from kinocut.tool_families import FAMILY_SURFACE_TOOLS

    assert len(CORE_TOOLS) == 8
    core_tagged = {name for name, tags in TOOL_REGISTRY.items() if "core" in tags}
    assert core_tagged == set(CORE_TOOLS)
    assert {row["name"] for row in BASELINE["modes"]["default"]["tools"]} == set(CORE_TOOLS) | set(FAMILY_SURFACE_TOOLS)


def test_baseline_all_mode_agrees_with_registry_mappings():
    for row in BASELINE["modes"]["all"]["tools"]:
        name = row["name"]
        assert row["module"] == TOOL_MODULE_BY_NAME[name], name
        assert row["profiles"] == list(TOOL_REGISTRY[name]), name
        assert row["required_params"] == sorted(row["required_params"]), name


def test_every_module_has_profile_tags_and_default_subset_inherits_them():
    for name in CORE_TOOLS:
        module = TOOL_MODULE_BY_NAME[name]
        assert set(MODULE_PROFILE_TAGS[module]) <= set(TOOL_REGISTRY[name]), name
