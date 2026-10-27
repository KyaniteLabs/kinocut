"""Shipped plugin skills must not advertise tools the plugin's launch cannot serve.

The plugin's own launch (``mcp.json``) registers the curated 20-tool core — the
environment-unset default — while the ``kino`` CLI exposes its 177 commands
independently. A skill that names an MCP tool outside that core must therefore
say how to reach it: an explicit ``KINOCUT_TOOLS=profile:...`` selection and a
server restart, plus the instruction to stop and report when the tool is not
registered.

A skill that names a profile tool without that prerequisite sends the agent
after a tool the host never registered (Gate 2 F10): the agent searches,
finds the name, calls it, and gets a failure it cannot resolve. This test
makes that drift fail CI instead of shipping.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "kinocut" / "skills"
TOOL_NAME = re.compile(r"\b((?:video|hyperframes)_[a-z0-9_]+)\b")


def _default_core() -> set[str]:
    """The 20-tool default surface, read from a fresh process.

    The diet is applied when ``kinocut.server`` is imported, and the surface is
    process-global: importing it inside the test session would inherit whatever
    an earlier test left behind.
    """
    script = (
        "import asyncio\n"
        "from kinocut.server import mcp\n"
        "print('\\n'.join(sorted(tool.name for tool in asyncio.run(mcp.list_tools()))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_default_surface_is_the_curated_twenty():
    assert len(_default_core()) == 20


def test_shipped_skills_document_how_to_reach_tools_outside_the_default_core():
    core = _default_core()
    for skill in sorted(SKILLS.glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        named = set(TOOL_NAME.findall(text))
        unreachable = named - core
        if not unreachable:
            continue
        name = skill.parent.name
        assert "KINOCUT_TOOLS" in text, (
            f"skill {name} names tools outside the default core "
            f"({sorted(unreachable)}) without saying how to enable them"
        )
        assert "profile" in text, f"skill {name} must name the profile to select"
        assert "stop" in text.lower(), (
            f"skill {name} must tell the agent to stop and report when the tool is unavailable"
        )


def test_plugin_readme_documents_the_explicit_profile_launch():
    readme = (ROOT / "plugins" / "kinocut" / "README.md").read_text(encoding="utf-8")
    assert "KINOCUT_TOOLS" in readme
    assert "profile:editor" in readme
    assert "20-tool" in readme


def test_plugin_launch_stays_on_the_curated_default():
    """The plugin's own launch must not silently widen the default surface."""
    import json

    server = json.loads((ROOT / "plugins" / "kinocut" / ".mcp.json").read_text(encoding="utf-8"))
    kinocut = server["mcpServers"]["kinocut"]
    assert kinocut["args"] == ["kinocut==1.16.5"]
    assert "env" not in kinocut, "the plugin launch must stay on the environment-unset default"
