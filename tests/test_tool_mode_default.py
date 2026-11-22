"""An unset or blank KINOCUT_TOOLS means core: the 18-tool surface, not all 206 (LFM3 eval: 5.2k vs 44.8k prompt tokens)."""

import json
from pathlib import Path

from kinocut.tool_registry import parse_tool_mode

ROOT = Path(__file__).resolve().parents[1]


def test_unset_and_blank_tools_default_to_core(monkeypatch):
    monkeypatch.delenv("KINOCUT_TOOLS", raising=False)
    assert parse_tool_mode() == ("default", frozenset({"core"}))
    assert parse_tool_mode("") == parse_tool_mode("core") == ("default", frozenset({"core"}))
    assert parse_tool_mode("all")[0] == "all"


def test_plugin_launch_does_not_ask_for_all_tools():
    for name in ("mcp.json", "kinocut.mcp.json"):
        server = json.loads((ROOT / "plugins" / "kinocut" / name).read_text())["mcpServers"]["kinocut"]
        assert "KINOCUT_TOOLS" not in server.get("env", {}) or server["env"]["KINOCUT_TOOLS"] == "core"
