"""Every current install instruction must pin the released version.

Dated records — release notes, research, plans, the claims history — keep
their own history and are not re-written. Everything a reader would run
today, and every remediation string the package ships, must name the exact
release it belongs to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATED_PARTS = ("research", "plans", "status", "archive", "retired")
DATED_FILES = ("CHANGELOG.md", "public_claims.json")
INSTALL = re.compile(r"pip install\s+[\"']?kinocut(?:\[[a-z0-9,-]+\])?[\"']?([^\s\"']*)")


def _current_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "README-PYPI.md", ROOT / "llms.txt"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    files.extend(sorted((ROOT / "docs").rglob("*.txt")))
    files.extend(sorted((ROOT / "kinocut").rglob("*.py")))
    files.extend(sorted((ROOT / "examples").rglob("*.md")))
    files.extend(sorted((ROOT / "examples").rglob("*.json")))
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
        if "pip install" not in line:
            continue
        for match in INSTALL.finditer(line):
            if not match.group(1).startswith("=="):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "current install instructions must pin the released version:\n" + "\n".join(offenders)
