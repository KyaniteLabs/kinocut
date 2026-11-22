"""Compatibility contracts for discovery, legacy facade calls, and profile isolation.

These tests protect the behaviors the 1.16.5 tool diet promised:

* ``search_tools`` / ``discover_tools`` find hidden tools deterministically
  over caller-supplied metadata, never invent names, and never leak the full
  catalog into the registered surface afterwards;
* legacy Python access (``from kinocut.server import <hidden tool>``) keeps
  working in every mode with unchanged parameters and outcomes, while the
  wire surface stays fail-closed for hidden tools;
* ``KINOCUT_TOOLS`` modes are isolated: default/core is the 20 core tools
  plus the compact family surface (8 dispatchers + ``list_operations`` +
  ``describe_operation``), ``all`` is exactly the registry,
  profiles are additive on core, and
  an unknown profile aborts startup instead of silently degrading.

The tests are hermetic: an autouse fixture pins the ambient ``KINOCUT_TOOLS``
so this file passes identically with the variable unset, ``all``, or a
profile exported; the production rule that no-argument calls honor the
environment at call time is asserted explicitly rather than assumed away.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from kinocut.server import mcp, search_tools
from kinocut.tool_discovery import discover_tools
from kinocut.tool_families import FAMILY_SURFACE_TOOLS
from kinocut.tool_registry import (
    CORE_TOOLS,
    TOOL_REGISTRY,
    active_mode,
    configure_tool_surface,
    discovery_catalog,
    ensure_tool_loaded,
    parse_tool_mode,
)

ROOT = Path(__file__).resolve().parents[1]


def _default_surface() -> set[str]:
    """Default mode: the core diet plus the compact family surface, exactly."""
    return set(CORE_TOOLS) | set(FAMILY_SURFACE_TOOLS)


@pytest.fixture(autouse=True)
def _restore_full_surface():
    """Keep the session-wide full catalog intact regardless of test outcome."""
    yield
    configure_tool_surface("all")


@pytest.fixture(autouse=True)
def _hermetic_selector(monkeypatch):
    """Freeze the ambient ``KINOCUT_TOOLS`` selector for every test here.

    Production deliberately reads ``KINOCUT_TOOLS`` at call time — both
    ``configure_tool_surface()`` and ``parse_tool_mode(None)`` honor it (that
    is how deployments select a mode). These tests control the variable
    instead of assuming it is unset, so this file passes identically with the
    ambient selector unset, ``all``, or any profile. The honoring contract
    itself is asserted in
    ``test_no_argument_calls_honor_the_controlled_environment``.
    """
    monkeypatch.delenv("KINOCUT_TOOLS", raising=False)


def _surface_names() -> set[str]:
    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def _subprocess_surface(env_mode: str | None) -> dict[str, Any]:
    """Spawn a cold server process the way deployments do and return its state."""
    script = (
        "import asyncio, json\n"
        "from kinocut.server import mcp\n"
        "from kinocut.tool_registry import active_mode\n"
        "names = sorted(t.name for t in asyncio.run(mcp.list_tools()))\n"
        "print(json.dumps({'mode': active_mode(), 'count': len(names), 'names': names}))\n"
    )
    env = dict(os.environ)
    if env_mode is None:
        env.pop("KINOCUT_TOOLS", None)
    else:
        env["KINOCUT_TOOLS"] = env_mode
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# --- discovery over caller-supplied metadata --------------------------------------


def _catalog_entry(name: str, description: str = "", required: list[str] | None = None) -> dict:
    return {"name": name, "description": description, "required_params": required or []}


def test_discovery_ranks_exact_name_first_and_reports_required_params():
    tools = [
        _catalog_entry("video_trim", "Trim a video clip", ["input_path"]),
        _catalog_entry("video_trim_extended", "Trim with extras"),
        _catalog_entry("audio_trim", "Trim audio"),
    ]
    result = discover_tools("video_trim", tools)
    assert result["success"] is True
    assert result["count"] == 2
    assert result["tools"][0]["name"] == "video_trim"
    assert result["tools"][0]["required_params"] == ["input_path"]
    assert result["tools"][1]["name"] == "video_trim_extended"


def test_discovery_phrase_aliases_point_at_public_contracts():
    result = discover_tools(
        "remove filler words", [_catalog_entry(name) for name in ("video_timeline_edit_plan", "video_trim")]
    )
    assert [tool["name"] for tool in result["tools"]] == ["video_timeline_edit_plan"]

    resume = discover_tools(
        "resume render", [_catalog_entry(name) for name in ("video_workflow_render", "video_workflow_inspect")]
    )
    assert [tool["name"] for tool in resume["tools"]] == ["video_workflow_render"]


def test_discovery_requires_full_token_coverage_so_generic_words_cannot_recommend():
    # "video" appears only in tool A's description, "audio" only in tool B's:
    # neither tool covers the whole query, so nothing may be recommended.
    tools = [
        _catalog_entry("tool_a", "handles video streams"),
        _catalog_entry("tool_b", "handles audio streams"),
    ]
    assert discover_tools("video audio", tools)["tools"] == []
    # A single tool covering both tokens is a complete match.
    tools.append(_catalog_entry("tool_ab", "handles video and audio streams"))
    assert [tool["name"] for tool in discover_tools("video audio", tools)["tools"]] == ["tool_ab"]


def test_discovery_never_invents_names_beyond_the_supplied_catalog():
    tools = [_catalog_entry("video_trim", "Trim a video clip")]
    result = discover_tools("remove background", tools)
    assert result["tools"] == [], "hyperframes_remove_background exists in the real catalog but not here"


def test_discovery_excludes_itself_and_empty_queries_and_breaks_ties_by_name():
    tools = [
        _catalog_entry("search_tools", "search"),
        _catalog_entry("video_alpha", "alpha"),
        _catalog_entry("audio_alpha", "alpha"),
    ]
    assert discover_tools("alpha", tools)["tools"][0]["name"] != "search_tools"
    assert discover_tools("", tools)["count"] == 0
    result = discover_tools("alpha", tools)
    assert [tool["name"] for tool in result["tools"]] == ["audio_alpha", "video_alpha"]


def test_search_tools_finds_hidden_tools_in_default_mode_without_leaking_them():
    configure_tool_surface()  # default: 20-tool diet
    result = search_tools("blur")
    assert result["success"] is True
    assert "video_filter" in {tool["name"] for tool in result["tools"]}
    assert _surface_names() == _default_surface(), "discovery must not register hidden tools"


def test_discovery_catalog_covers_the_registry_and_restores_the_surface():
    configure_tool_surface()  # default
    catalog = discovery_catalog()
    assert {row["name"] for row in catalog} == set(TOOL_REGISTRY)
    assert all("required_params" in row for row in catalog)
    assert active_mode() == "default"
    assert _surface_names() == _default_surface(), (
        "loading the full catalog for discovery must restore the selected surface"
    )


# --- legacy facade imports and calls ----------------------------------------------


def test_legacy_facade_import_of_hidden_tools_keeps_the_wire_surface_closed():
    from kinocut import server as facade

    configure_tool_surface()  # default
    hidden = facade.video_filter  # resolved through the PEP 562 module __getattr__
    assert callable(hidden)
    assert _surface_names() == _default_surface(), "a legacy import must not register its module's tools"
    with pytest.raises(ToolError, match="Unknown tool: video_filter"):
        asyncio.run(mcp.call_tool("video_filter", {"input_path": "unused.mp4"}))


def test_legacy_import_in_a_cold_default_mode_process():
    script = (
        "import asyncio, json\n"
        "from kinocut.server import mcp, video_filter  # legacy facade import of a hidden tool\n"
        "from kinocut.tool_registry import CORE_TOOLS\n"
        "names = {t.name for t in asyncio.run(mcp.list_tools())}\n"
        "from kinocut.tool_families import FAMILY_SURFACE_TOOLS\n"
        "expected = set(CORE_TOOLS) | set(FAMILY_SURFACE_TOOLS)\n"
        "print(json.dumps({'imported': video_filter.__name__, 'count': len(names), 'is_default_surface': names == expected}))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "KINOCUT_TOOLS"}
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"imported": "video_filter", "count": 18, "is_default_surface": True}


def test_ensure_tool_loaded_rejects_unknown_names():
    with pytest.raises(AttributeError, match="definitely_not_a_tool"):
        ensure_tool_loaded("definitely_not_a_tool")


def test_legacy_hidden_tool_call_keeps_parameters_and_outcome(sample_video):
    """A hidden tool imported the legacy way must behave exactly like its wire form.

    ``video_audio_waveform`` is exercised over stdio by
    test_mcp_argument_contracts with ``bins=2``; the same parameters called
    through the Python facade must return the same successful outcome.
    """
    configure_tool_surface()  # default: the tool is hidden from MCP but importable
    from kinocut.server import video_audio_waveform

    result = video_audio_waveform(input_path=sample_video, bins=2)
    assert result["success"] is True
    assert len(result["peaks"]) == 2
    assert _surface_names() == _default_surface()


# --- profile isolation ------------------------------------------------------------


def test_parse_tool_mode_matrix():
    assert parse_tool_mode("") == ("default", frozenset({"core"}))
    assert parse_tool_mode(None) == ("default", frozenset({"core"}))
    assert parse_tool_mode("core") == ("default", frozenset({"core"}))
    assert parse_tool_mode("ALL") == ("all", frozenset())
    mode, profiles = parse_tool_mode("profile:editor,audio")
    assert mode == "profile:audio,editor"
    assert profiles == frozenset({"core", "editor", "audio"})
    with pytest.raises(ValueError, match="KINOCUT_TOOLS must be all, core, or profile:<name>"):
        parse_tool_mode("profile:does_not_exist")
    with pytest.raises(ValueError):
        parse_tool_mode("everything")


def test_no_argument_calls_honor_the_controlled_environment(monkeypatch):
    """``configure_tool_surface()`` / ``parse_tool_mode(None)`` read
    ``KINOCUT_TOOLS`` at call time — the deployment contract that selects a
    mode without code changes. Asserted against a controlled environment, not
    ambient chance (the autouse fixture pins the ambient variable to unset).
    """
    monkeypatch.setenv("KINOCUT_TOOLS", "all")
    assert parse_tool_mode(None) == ("all", frozenset())
    configure_tool_surface()
    assert active_mode() == "all"
    assert _surface_names() == set(TOOL_REGISTRY)

    monkeypatch.setenv("KINOCUT_TOOLS", "profile:editor")
    mode, profiles = parse_tool_mode(None)
    assert mode == "profile:editor"
    assert profiles == frozenset({"core", "editor"})
    configure_tool_surface()
    assert active_mode() == "profile:editor"
    assert set(CORE_TOOLS) <= _surface_names()


def test_cold_server_modes_are_isolated():
    default = _subprocess_surface(None)
    assert default["mode"] == "default"
    assert default["count"] == 18  # 8 core tools + 8 family dispatchers + list_operations + describe_operation
    assert set(default["names"]) == _default_surface()

    core_alias = _subprocess_surface("core")
    assert core_alias["names"] == default["names"], "core is the documented alias of the default mode"

    everything = _subprocess_surface("all")
    assert everything["mode"] == "all"
    assert everything["count"] == 208 == len(TOOL_REGISTRY)
    assert set(everything["names"]) == set(TOOL_REGISTRY)

    editor = _subprocess_surface("profile:editor")
    expected = {name for name, tags in TOOL_REGISTRY.items() if "editor" in tags or "core" in tags} | set(
        FAMILY_SURFACE_TOOLS
    )
    assert editor["mode"] == "profile:editor"
    assert set(editor["names"]) == expected
    assert set(CORE_TOOLS) <= set(editor["names"])
    assert set(FAMILY_SURFACE_TOOLS) <= set(editor["names"])
    assert editor["count"] == 115  # 105 direct + the compact family surface


def test_unknown_profile_aborts_startup_instead_of_silently_degrading():
    env = {**os.environ, "KINOCUT_TOOLS": "profile:does_not_exist"}
    result = subprocess.run(
        [sys.executable, "-c", "import kinocut.server"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )
    assert result.returncode != 0
    assert "KINOCUT_TOOLS must be all, core, or profile:<name>" in result.stderr


def test_in_process_reconfigure_cycles_never_strand_tools():
    configure_tool_surface()
    assert _surface_names() == _default_surface()
    configure_tool_surface("profile:editor")
    assert set(CORE_TOOLS) <= _surface_names()
    configure_tool_surface("all")
    assert _surface_names() == set(TOOL_REGISTRY)
    configure_tool_surface()
    assert _surface_names() == _default_surface()
    configure_tool_surface("all")
    assert _surface_names() == set(TOOL_REGISTRY)
