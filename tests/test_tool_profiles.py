"""Contracts for the profile-driven MCP tool surface."""

import os
import importlib.util
import json
import subprocess
import sys

import pytest

from kinocut.tool_registry import CORE_TOOLS, TOOL_REGISTRY, parse_tool_mode


def test_registry_covers_the_full_server_tool_catalog():
    assert len(TOOL_REGISTRY) == 205
    assert len(CORE_TOOLS) <= 25
    assert {"video_info", "video_trim", "video_add_text", "search_tools"} <= CORE_TOOLS


def test_default_and_all_modes_are_explicit():
    assert parse_tool_mode("") == ("default", frozenset({"core"}))
    assert parse_tool_mode("all") == ("all", frozenset())


def test_profiles_include_core_and_named_editor_profile():
    mode, profiles = parse_tool_mode("profile:editor")
    assert mode == "profile:editor"
    assert profiles == frozenset({"core", "editor"})
    assert "video_info" in TOOL_REGISTRY
    assert "editor" in TOOL_REGISTRY["video_info"]


def test_glitch_family_is_hidden_from_default_surface_even_when_imported():
    script = """
import asyncio
import json
from kinocut.server import mcp
import kinocut.server_tools_glitch
import kinocut.server_tools_glitch_shader

print(json.dumps([tool.name for tool in asyncio.run(mcp.list_tools())]))
"""
    default_env = {key: value for key, value in os.environ.items() if key != "KINOCUT_TOOLS"}
    result = subprocess.run([sys.executable, "-c", script], env=default_env, capture_output=True, text=True, check=True)
    names = set(json.loads(result.stdout.strip()))
    assert len(names) == 20
    assert not any(name.startswith("glitch_") for name in names)

    glitch_names = {name for name in TOOL_REGISTRY if name.startswith("glitch_")}
    assert glitch_names
    assert all("hidden" in TOOL_REGISTRY[name] for name in glitch_names)


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="MCP dependency unavailable")
def test_runtime_surface_modes_and_hidden_discovery():
    script = "import asyncio; from kinocut.server import mcp; print(len(asyncio.run(mcp.list_tools())))"

    default = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    full_env = {**os.environ, "KINOCUT_TOOLS": "all"}
    full = subprocess.run([sys.executable, "-c", script], env=full_env, capture_output=True, text=True, check=True)
    assert int(default.stdout.strip()) == 20
    assert int(full.stdout.strip()) == 205

    from kinocut.server import search_tools

    result = search_tools("blur")
    assert result["success"] is True
    assert "video_filter" in {tool["name"] for tool in result["tools"]}
