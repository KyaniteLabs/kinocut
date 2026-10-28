"""Every current install or launch instruction must pin the released version.

Dated records — release notes, research, plans, decision records, the claims
history — keep their own history and are not re-written. Everything a reader
would run today, and every remediation string the package ships, must name the
exact release it belongs to.

The sweep covers the launch grammars too: pip, pipx, uv, uvx and npm all name
the distribution differently, and an unpinned `uvx` launch would sail past a
pip-only check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATED_PARTS = ("research", "plans", "status", "archive", "retired", "adr", "release-notes")
DATED_FILES = ("CHANGELOG.md", "public_claims.json", "DIRECTORY_REBRAND_STATUS.md")
SCANNED_SUFFIXES = (".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml")
ROOT_MANIFESTS = ("server.json", "smithery.yaml", "gemini-extension.json", "mcpb/manifest.json", "package.json")

# Every grammar that names the distribution. Each capture is the version
# token that follows the package name; it must carry the version pin.
INSTALL_GRAMMARS = (
    re.compile(r"pip\s+install(?:\s+--?[\w-]+)*\s+[\"']?kinocut(?:\[[a-z0-9,-]+\])?[\"']?([^\s\"']*)"),
    re.compile(r"pipx\s+run(?:\s+--?[\w-]+)*\s+[\"']?kinocut(?:\[[a-z0-9,-]+\])?[\"']?([^\s\"']*)"),
    # The flag and the package can be separated by whitespace or by a JSON
    # array boundary: `"--from", "kinocut"`.
    re.compile(r"--from(?:[\"']\s*,\s*[\"']|\s+)kinocut(?:\[[a-z0-9,-]+\])?[\"']?([^\s\"']*)"),
    re.compile(r"--with(?:[\"']\s*,\s*[\"']|\s+)kinocut(?:\[[a-z0-9,-]+\])?[\"']?([^\s\"']*)"),
    # A bare `uvx kinocut` counts as a launch only when it opens a command.
    # In prose it describes the registry entry's stdio package, and dated
    # records keep the version that was true at the time.
    re.compile(r"^\s*(?:\$ )?uvx\s+[\"']?kinocut(?:\[[a-z0-9,-]+\])?[\"']?([^\s\"']*)"),
    re.compile(r"npm\s+install\s+(?:-\S+\s+)*[\"']?kinocut(@[^\s\"']*)?"),
)


def _current_files() -> list[Path]:
    roots = ("docs", "kinocut", "examples", "plugins", "skills", "compat", "workflows")
    files = [ROOT / "README.md", ROOT / "README-PYPI.md", ROOT / "llms.txt"]
    files.extend(path for path in (ROOT / name for name in ROOT_MANIFESTS) if path.exists())
    for name in roots:
        base = ROOT / name
        if not base.exists():
            continue
        files.extend(sorted(path for path in base.rglob("*") if path.is_file() and path.suffix in SCANNED_SUFFIXES))
    keep: list[Path] = []
    for path in files:
        if path.name in DATED_FILES:
            continue
        relative = path.relative_to(ROOT)
        if any(part in DATED_PARTS for part in relative.parts):
            continue
        keep.append(path)
    return keep


@pytest.mark.parametrize("path", _current_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_current_install_instructions_pin_the_released_version(path):
    offenders: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        for grammar in INSTALL_GRAMMARS:
            for match in grammar.finditer(line):
                version = match.group(1) or ""
                pinned = version.startswith("==") or version.startswith("@1.")
                if not pinned:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "current install instructions must pin the released version:\n" + "\n".join(offenders)


def test_the_sweep_covers_the_launch_grammars_it_claims_to_cover():
    # A guard that only knows about pip is not the guard this file promises.
    text = " ".join(grammar.pattern for grammar in INSTALL_GRAMMARS)
    for grammar in ("pip", "pipx", "uvx", "--from", "--with", "npm"):
        assert grammar in text
