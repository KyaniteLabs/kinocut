"""Validation tests for Kinocut 2.1.0 Track B platform & release-polish quick wins."""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tomllib
import urllib.parse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PINNED_RUNTIME = "2.0.1"


def test_opencode_plugin_config_and_helper() -> None:
    """OpenCode plugin ships a valid pinned opencode.json, index.js helper, and README."""
    plugin_dir = ROOT / "plugins" / "kinocut" / "opencode-plugin"
    config = json.loads((plugin_dir / "opencode.json").read_text(encoding="utf-8"))
    readme = (plugin_dir / "README.md").read_text(encoding="utf-8")
    index_js = plugin_dir / "index.js"

    assert config["$schema"] == "https://opencode.ai/config.json"
    kinocut = config["mcp"]["kinocut"]
    assert kinocut == {
        "type": "local",
        "command": ["uvx", f"kinocut=={PINNED_RUNTIME}"],
        "enabled": True,
    }
    assert index_js.is_file()
    assert f"kinocut=={PINNED_RUNTIME}" in readme
    assert "opencode.json" in readme

    node = shutil.which("node")
    if node is not None:
        check = subprocess.run(
            [node, "--check", str(index_js)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert check.returncode == 0, check.stderr
        probe = subprocess.run(
            [
                node,
                "-e",
                (
                    "const m = require('./plugins/kinocut/opencode-plugin'); "
                    "const p = m.kinocutOpenCodePlugin(); "
                    "const e = m.createOpenCodeConfig({ toolsProfile: 'profile:editor' }); "
                    "console.log(JSON.stringify({ name: p.name, version: p.version, "
                    "cmd: p.config.mcp.kinocut.command, env: e.mcp.kinocut.environment }));"
                ),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert probe.returncode == 0, probe.stderr
        payload = json.loads(probe.stdout)
        assert payload["name"] == "kinocut"
        assert payload["version"] == PINNED_RUNTIME
        assert payload["cmd"] == ["uvx", f"kinocut=={PINNED_RUNTIME}"]
        assert payload["env"] == {"KINOCUT_TOOLS": "profile:editor"}


def test_vscode_and_codex_example_configs() -> None:
    """VS Code MCP JSON and Codex TOML examples parse cleanly and pin 2.0.1."""
    vscode = json.loads((ROOT / "examples" / "vscode_mcp.json").read_text(encoding="utf-8"))
    server = vscode["servers"]["kinocut"]
    assert server == {
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", f"kinocut=={PINNED_RUNTIME}", "kino", "--mcp"],
    }

    codex = tomllib.loads((ROOT / "examples" / "codex_config.toml").read_text(encoding="utf-8"))
    codex_server = codex["mcp_servers"]["kinocut"]
    assert codex_server == {
        "command": "uvx",
        "args": ["--from", f"kinocut=={PINNED_RUNTIME}", "kino", "--mcp"],
    }


def test_install_platforms_doc_and_readme_one_click_links() -> None:
    """Multi-platform guide and README include valid pinned VS Code and Cursor one-click links."""
    platforms = (ROOT / "docs" / "INSTALL_PLATFORMS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for expected in (
        "VS Code",
        "GitHub Copilot",
        "Cursor",
        "Codex CLI",
        "~/.codex/config.toml",
        "Windsurf",
        "Zed",
        "Cline",
        "Roo Code",
        "OpenCode",
        "Hermes",
        "Claude",
        "Gemini CLI",
        "extensions/chrome/",
    ):
        assert expected in platforms, f"missing platform section or reference: {expected}"

    assert "docs/INSTALL_PLATFORMS.md" in readme

    for label, text in (("README.md", readme), ("docs/INSTALL_PLATFORMS.md", platforms)):
        vs_match = re.search(r'vscode:mcp/install\?([^"\s<>]+)', text)
        assert vs_match is not None, f"{label} missing vscode:mcp/install link"
        vs_payload = json.loads(urllib.parse.unquote(vs_match.group(1)))
        assert vs_payload == {
            "name": "kinocut",
            "command": "uvx",
            "args": ["--from", f"kinocut=={PINNED_RUNTIME}", "kino", "--mcp"],
        }

        cur_match = re.search(r'cursor://anysphere\.cursor-deeplink/mcp/install\?([^"\s<>]+)', text)
        assert cur_match is not None, f"{label} missing Cursor deeplink"
        cur_query = urllib.parse.parse_qs(cur_match.group(1))
        assert cur_query["name"] == ["kinocut"]
        cur_payload = json.loads(base64.b64decode(cur_query["config"][0]).decode("utf-8"))
        assert cur_payload == {
            "command": "uvx",
            "args": ["--from", f"kinocut=={PINNED_RUNTIME}", "kino", "--mcp"],
        }


def test_repurpose_openai_yaml_has_interface_metadata_parity() -> None:
    """skills/kinocut-repurpose/agents/openai.yaml matches skills/kinocut/agents/openai.yaml structure."""
    main_meta = yaml.safe_load((ROOT / "skills" / "kinocut" / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    repurpose_meta = yaml.safe_load(
        (ROOT / "skills" / "kinocut-repurpose" / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )

    assert "interface" in repurpose_meta and isinstance(repurpose_meta["interface"], dict)
    assert set(repurpose_meta["interface"]) == set(main_meta["interface"])
    for key in ("display_name", "short_description", "default_prompt"):
        value = repurpose_meta["interface"][key]
        assert isinstance(value, str) and value.strip()
    assert "$kinocut-repurpose" in repurpose_meta["interface"]["default_prompt"]
    assert repurpose_meta.get("policy", {}).get("allow_implicit_invocation") is True


def test_skill_parity_for_music_grid_audio_sync_and_tv_preview_fallback() -> None:
    """Root and plugin kinocut SKILL.md stay in lockstep on 2.1.0 additions and 2.0.1 fallback."""
    root_skill = (ROOT / "skills" / "kinocut" / "SKILL.md").read_text(encoding="utf-8")
    plugin_skill = (ROOT / "plugins" / "kinocut" / "skills" / "kinocut" / "SKILL.md").read_text(encoding="utf-8")

    section_heading = "## Beat-locked trim, audio sync, and TV preview fallback"
    for label, text in (("root", root_skill), ("plugin", plugin_skill)):
        assert section_heading in text, f"{label} SKILL.md missing fallback section"
        assert "trim --bpm" in text
        assert "kinocut.music_grid" in text
        assert "kinocut.audio_sync" in text
        assert "kinocut.tv_preview" in text
        assert "video_review_card" in text
        assert "2.0.1" in text

    def _extract_section(text: str) -> str:
        match = re.search(rf"(?ms)^{re.escape(section_heading)}\n(.*?)(?=^## |\Z)", text)
        assert match is not None
        return match.group(1).strip()

    assert _extract_section(root_skill) == _extract_section(plugin_skill)


def test_changelog_v210_has_security_and_wave_summary_sections() -> None:
    """CHANGELOG.md 2.1.0 includes Security and covers the audit remediation waves and Track B additions."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"(?ms)^## 2\.1\.0 - 2026-11-24\n(.*?)(?=^## |\Z)", changelog)
    assert match is not None, "missing 2.1.0 section in CHANGELOG.md"
    body = match.group(1)

    for heading in ("### Added", "### Security", "### Changed", "### Fixed"):
        assert heading in body, f"CHANGELOG 2.1.0 missing {heading}"

    for topic in (
        "KINOCUT_OFFLINE=1",
        "SSRF",
        "C2PA",
        "Zero-clip audio mixing",
        "FFmpeg 7.x",
        "37 -> <=6",
        "O(1) WAL",
        "Hermes Desktop",
        "INSTALL_PLATFORMS.md",
        "Chrome Companion",
    ):
        assert topic in body, f"CHANGELOG 2.1.0 missing expected topic: {topic}"
