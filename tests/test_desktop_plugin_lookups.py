"""The Desktop pane's lookup list matches the tools that never write media.

plugins/kinocut/desktop/plugin.js files a finished tool under Activity when it
is in LOOKUP_TOOLS and under Renders otherwise. A tool that writes media takes
an ``overwrite`` argument, so the lookups are exactly the tools without one.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from kinocut.server import mcp

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "kinocut" / "desktop" / "plugin.js"


def _plugin_lookups() -> set[str]:
    src = PLUGIN.read_text(encoding="utf-8")
    block = re.search(r"LOOKUP_TOOLS = new Set\(\[(.*?)\]\)", src, re.S)
    assert block, "LOOKUP_TOOLS not found in plugin.js"
    return set(re.findall(r"'([a-z_]+)'", block.group(1)))


def test_lookup_tools_are_the_tools_without_overwrite():
    tools = asyncio.run(mcp.list_tools())
    no_overwrite = {t.name for t in tools if "overwrite" not in (t.inputSchema.get("properties") or {})}
    assert _plugin_lookups() == no_overwrite
