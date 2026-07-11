"""Regression tests for the path-based repurposing skill and demo recipe."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from tests.test_public_surface import EXPECTED_CLI_COMMANDS, EXPECTED_SERVER_TOOLS


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "kinocut-repurpose" / "SKILL.md"
DEMO = ROOT / "examples" / "repurpose_current_tools_demo.py"


def _fenced_commands(markdown: str) -> set[str]:
    commands: set[str] = set()
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("kino "):
            parts = stripped.split()
            if len(parts) > 1 and not parts[1].startswith("-"):
                commands.add(parts[1])
    return commands


def test_repurpose_skill_is_path_installable_and_current_tool_only():
    skill = SKILL.read_text(encoding="utf-8")

    assert "cp -R skills/kinocut-repurpose .claude/skills/kinocut-repurpose" in skill
    assert "pre-kernel" in skill
    assert "Do not invent commands" in skill
    assert "video_repurpose_plan" in skill
    assert "video_repurpose" in skill
    assert "video-ai-transcribe" in skill
    assert "subtitles" in skill
    assert "resize" in skill
    assert "normalize-audio" in skill
    assert "video-quality-check" in skill
    assert "storyboard" in skill
    assert "thumbnail" in skill
    assert "human review" in skill.lower()

    referenced = _fenced_commands(skill)
    assert referenced
    assert referenced <= EXPECTED_CLI_COMMANDS

    for tool in ("video_repurpose_plan", "video_repurpose"):
        assert tool in EXPECTED_SERVER_TOOLS


def test_repurpose_skill_names_required_guardrails():
    text = SKILL.read_text(encoding="utf-8").lower()

    for guardrail in (
        "captions",
        "audio",
        "aspect",
        "pacing",
        "output review",
        "release checkpoint",
        "manifest",
        "do not publish",
    ):
        assert guardrail in text


def test_demo_script_has_deterministic_fixture_and_uses_only_shipped_cli_commands():
    source = DEMO.read_text(encoding="utf-8")
    tree = ast.parse(source)
    commands: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            second = node.elts[1] if len(node.elts) > 1 else None
            if isinstance(first, ast.Constant) and first.value == "kino":
                assert isinstance(second, ast.Constant)
                commands.add(str(second.value))

    assert {"info", "repurpose-plan", "repurpose", "video-quality-check"} <= commands
    assert commands <= EXPECTED_CLI_COMMANDS
    assert "testsrc2=size=640x360:rate=30" in source
    assert "sine=frequency=880:sample_rate=48000" in source
    assert "-t" in source


def test_demo_dry_run_prints_replayable_current_tool_recipe():
    result = subprocess.run(
        [sys.executable, str(DEMO), "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "kino repurpose-plan" in result.stdout
    assert "kino repurpose" in result.stdout
    assert "youtube-shorts" in result.stdout
    assert "instagram-reel" in result.stdout

    commands = set(re.findall(r"^kino ([a-z0-9-]+)", result.stdout, flags=re.MULTILINE))
    assert commands <= EXPECTED_CLI_COMMANDS
