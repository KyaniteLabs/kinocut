"""Shipped plugin skills must not advertise tools the plugin's launch cannot serve.

The plugin's own launch (``mcp.json``) registers the curated 20-tool core — the
environment-unset default — while the ``kino`` CLI exposes its 177 commands
independently. A skill that names an MCP tool outside that core must therefore
say how to reach it: an explicit ``KINOCUT_TOOLS=profile:<name>`` selection that
the registry actually assigns that tool to, a server restart, and the
instruction to stop and report when the tool is not registered.

A skill that names a profile tool without that prerequisite sends the agent
after a tool the host never registered (Gate 2 F10, Gate 3 N1/N2): the agent
searches, finds the name, calls it, and gets a failure it cannot resolve. This
test binds the claim to the registry, so a tool that moves to another profile
fails CI until the skill is updated to name the right one.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from kinocut.tool_registry import TOOL_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
SKILL_FILES = (
    ROOT / "skills" / "kinocut" / "SKILL.md",
    ROOT / "skills" / "kinocut-repurpose" / "SKILL.md",
    ROOT / "skills" / "mcp-video" / "SKILL.md",
    ROOT / "plugins" / "kinocut" / "skills" / "kinocut" / "SKILL.md",
    ROOT / "plugins" / "kinocut" / "skills" / "kinocut-repurpose" / "SKILL.md",
)
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _default_core() -> set[str]:
    """The 20-tool default surface, read from a fresh process.

    The diet is applied when ``kinocut.server`` is imported and the surface is
    process-global, so the probe runs in its own interpreter. ``KINOCUT_TOOLS``
    is stripped from the environment: an ambient value would change the subject
    of the "default" claim.
    """
    script = (
        "import asyncio\n"
        "from kinocut.server import mcp\n"
        "print('\\n'.join(sorted(tool.name for tool in asyncio.run(mcp.list_tools()))))\n"
    )
    env = {key: value for key, value in os.environ.items() if key != "KINOCUT_TOOLS"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _named_tools(text: str) -> set[str]:
    """Registered MCP tools the skill names.

    The registry is the source of truth for what a tool is called, so the scan
    is a token sweep rather than a prefix guess: ``revideo_*``, ``sound_*`` and
    every other family count. Prose fragments and wildcards
    (``video_360_*``) are not registered names, and a skill may deliberately
    name a tool it tells the agent not to invent.
    """
    return {token for token in TOKEN.findall(text) if token in TOOL_REGISTRY}


def _skill_label(skill: Path) -> str:
    return skill.parent.parent.name if skill.parent.name == "skills" else skill.parent.name


def _profile_map(text: str) -> dict[str, set[str]]:
    """Tool -> profiles, parsed from the ``profile:<tag> carries ...`` lines.

    The mapping is the machine-checkable form of the claim. A skill that
    states one is held to it: the tool must be listed, and it must be listed
    under a profile the registry assigns it to. A skill that states no
    mapping names no way to reach the tool, and fails the contract.
    """
    mapping: dict[str, set[str]] = {}
    for line in text.splitlines():
        match = re.match(r"\s*`profile:([a-z0-9_-]+)`\s+carries\s+(.*)", line)
        if not match:
            continue
        tag = match.group(1)
        for tool in TOKEN.findall(match.group(2)):
            if tool in TOOL_REGISTRY:
                mapping.setdefault(tool, set()).add(tag)
    return mapping


def _contract_offenders(text: str, core: set[str], name: str = "skill") -> list[str]:
    """The ways a skill's text breaks the profile contract.

    The contract is a mapping, not a substring. A sentence that merely
    mentions ``profile:editor`` while the tool sits under another profile
    satisfies nothing, so the check reads the mapping lines and nothing else.
    """
    mapping = _profile_map(text)
    offenders: list[str] = []
    for tool in sorted(_named_tools(text) - core):
        tags = [tag for tag in TOOL_REGISTRY[tool] if tag != "core"]
        if not tags:
            offenders.append(f"{name} names {tool}, which the registry assigns to no profile")
            continue
        if not mapping:
            offenders.append(f"{name} names {tool} but states no profile mapping for it")
            continue
        if tool not in mapping:
            offenders.append(f"{name} maps tools to profiles but never lists {tool}")
            continue
        if not mapping[tool] & set(tags):
            offenders.append(
                f"{name} lists {tool} under profile(s) {sorted(mapping[tool])}, "
                f"which do not carry it (its profiles: {', '.join(tags)})"
            )
    return offenders


def test_default_surface_is_the_curated_twenty():
    assert len(_default_core()) == 20


def test_every_shipped_skill_is_covered():
    for skill in SKILL_FILES:
        assert skill.exists(), f"{skill} is missing; the contract test would skip it"


def test_shipped_skills_document_the_profile_that_carries_each_tool():
    core = _default_core()
    for skill in SKILL_FILES:
        text = skill.read_text(encoding="utf-8")
        name = _skill_label(skill)
        offenders = _contract_offenders(text, core, name)
        assert not offenders, "\n".join(offenders)


def test_a_tool_removed_from_the_mapping_breaks_the_contract():
    # The mapping is the claim. Drop the tool from it and the skill fails.
    text = "Use `video_repurpose_plan` and `video_repurpose`.\n`profile:editor` carries `video_repurpose`;\n"
    core = _default_core()
    assert _contract_offenders(text, core, "mutated")


def test_an_unrelated_profile_mention_does_not_satisfy_the_contract():
    # The old rule accepted any occurrence of `profile:<tag>` anywhere.
    text = "Use `video_repurpose_plan` and `video_repurpose`.\nThe `profile:editor` diet is mentioned in passing.\n"
    core = _default_core()
    assert _contract_offenders(text, core, "prose")


def test_shipped_skills_say_how_to_apply_the_selection():
    core = _default_core()
    for skill in SKILL_FILES:
        text = skill.read_text(encoding="utf-8")
        if not _named_tools(text) - core:
            continue
        name = _skill_label(skill)
        assert "KINOCUT_TOOLS" in text, f"skill {name} must name the environment variable"
        assert "restart" in text.lower(), f"skill {name} must say the server has to be restarted"
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
    server = json.loads((ROOT / "plugins" / "kinocut" / ".mcp.json").read_text(encoding="utf-8"))
    kinocut = server["mcpServers"]["kinocut"]
    assert kinocut["args"] == ["kinocut==1.16.5"]
    assert "env" not in kinocut, "the plugin launch must stay on the environment-unset default"
