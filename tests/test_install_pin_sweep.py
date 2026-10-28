"""Every current install or launch instruction must pin the released version.

Dated records — release notes, research, plans, decision records, the claims
history — keep their own history and are not re-written. Everything a reader
would run today, and every remediation string the package ships, must name the
exact release it belongs to.

The sweep covers the launch grammars too: pip, pipx, uv, uvx and npm all name
the distribution differently, and an unpinned `uvx` launch would sail past a
pip-only check. The former name ships as a shim, so ``mcp-video`` is a grammar
of its own. A current status file is a current surface: it is scanned, and
the history it records is pinned to the version that was true at the time.

Pinning is not enough on its own: the sweep compares the captured version
with the release it must name. ``pip install kinocut==1.15.2`` is pinned and
still wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATED_PARTS = ("research", "plans", "status", "archive", "retired", "adr", "release-notes")
DATED_FILES = ("CHANGELOG.md", "public_claims.json", "DIRECTORY_REBRAND_STATUS.md")
# The current status file is a current surface, not a dated record.
CURRENT_FILES = ("docs/status/NOW.md",)
SCANNED_SUFFIXES = (".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml")
ROOT_MANIFESTS = ("server.json", "smithery.yaml", "gemini-extension.json", "mcpb/manifest.json", "package.json")

# The release every current surface must name.
EXPECTED_PINS = {"kinocut": "1.16.5", "mcp-video": "1.6.20"}

# Every grammar that names the distribution, with the distribution it names.
# Each capture is the version token that follows the package name; it must be
# the release in EXPECTED_PINS for that distribution. The token is
# version-shaped on purpose: a capture that ran to the end of the word would
# swallow the punctuation around it — a backtick, a comma, a closing paren —
# and call a correct pin wrong.
VERSION_PATTERN = r"(?:==|@)?[0-9][0-9A-Za-z]*(?:\.[0-9A-Za-z]+)*"
INSTALL_GRAMMARS = (
    (
        "kinocut",
        re.compile(
            r"pip\s+install(?:\s+--?[\w-]+)*\s+[\"']?kinocut(?:\[[a-z0-9,-]+\])?[\"']?"
            rf"(?P<version>{VERSION_PATTERN})?"
        ),
    ),
    (
        "mcp-video",
        re.compile(
            r"pip\s+install(?:\s+--?[\w-]+)*\s+[\"']?mcp-video(?:\[[a-z0-9,-]+\])?[\"']?"
            rf"(?P<version>{VERSION_PATTERN})?"
        ),
    ),
    (
        "kinocut",
        re.compile(
            r"pipx\s+run(?:\s+--?[\w-]+)*\s+[\"']?kinocut(?:\[[a-z0-9,-]+\])?[\"']?"
            rf"(?P<version>{VERSION_PATTERN})?"
        ),
    ),
    # The flag and the package can be separated by whitespace or by a JSON
    # array boundary: `"--from", "kinocut"`.
    (
        "kinocut",
        re.compile(
            r"--from(?:[\"']\s*,\s*[\"']|\s+)kinocut(?:\[[a-z0-9,-]+\])?[\"']?"
            rf"(?P<version>{VERSION_PATTERN})?"
        ),
    ),
    (
        "kinocut",
        re.compile(
            r"--with(?:[\"']\s*,\s*[\"']|\s+)kinocut(?:\[[a-z0-9,-]+\])?[\"']?"
            rf"(?P<version>{VERSION_PATTERN})?"
        ),
    ),
    # A bare `uvx kinocut` counts as a launch only when it opens a command.
    # In prose it describes the registry entry's stdio package, and dated
    # records keep the version that was true at the time.
    (
        "kinocut",
        re.compile(
            r"^\s*(?:\$ )?uvx\s+[\"']?kinocut(?:\[[a-z0-9,-]+\])?[\"']?"
            rf"(?P<version>{VERSION_PATTERN})?"
        ),
    ),
    (
        "kinocut",
        re.compile(
            r"npm\s+install\s+(?:-\S+\s+)*[\"']?kinocut"
            rf"(?P<version>{VERSION_PATTERN})?"
        ),
    ),
)


def _captured_version(token: str) -> str:
    """The version a capture names, with the installer prefix removed."""
    captured = (token or "").strip()
    for prefix in ("==", "@"):
        if captured.startswith(prefix):
            return captured[len(prefix) :]
    return captured


def _is_dated(relative: Path) -> bool:
    """Whether a path is a dated record rather than a current surface."""
    if relative.name in DATED_FILES:
        return True
    return any(part in DATED_PARTS for part in relative.parts)


def _current_files() -> list[Path]:
    roots = ("docs", "kinocut", "examples", "plugins", "skills", "compat", "workflows", ".github")
    files = [ROOT / "README.md", ROOT / "README-PYPI.md", ROOT / "llms.txt"]
    files.extend(path for path in (ROOT / name for name in ROOT_MANIFESTS) if path.exists())
    files.extend(path for path in (ROOT / name for name in CURRENT_FILES) if path.exists())
    for name in roots:
        base = ROOT / name
        if not base.exists():
            continue
        files.extend(sorted(path for path in base.rglob("*") if path.is_file() and path.suffix in SCANNED_SUFFIXES))
    keep: list[Path] = []
    for path in files:
        relative = path.relative_to(ROOT)
        if relative.as_posix() in CURRENT_FILES:
            keep.append(path)
            continue
        if _is_dated(relative):
            continue
        keep.append(path)
    return keep


def _offenders(path: Path, relative: Path) -> list[str]:
    """The install instructions in one file that do not name the release."""
    offenders: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        for distribution, grammar in INSTALL_GRAMMARS:
            for match in grammar.finditer(line):
                captured = _captured_version(match.group(1) or "")
                if captured != EXPECTED_PINS[distribution]:
                    offenders.append(f"{relative}:{number}: {line.strip()}")
    return offenders


@pytest.mark.parametrize("path", _current_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_current_install_instructions_pin_the_released_version(path):
    offenders = _offenders(path, path.relative_to(ROOT))
    assert not offenders, "current install instructions must pin the released version:\n" + "\n".join(offenders)


def test_the_sweep_covers_the_launch_grammars_it_claims_to_cover():
    # A guard that only knows about pip is not the guard this file promises.
    text = " ".join(grammar.pattern for _distribution, grammar in INSTALL_GRAMMARS)
    for grammar in ("pip", "pipx", "uvx", "--from", "--with", "npm", "mcp-video"):
        assert grammar in text


def test_a_dated_record_keeps_its_own_history(tmp_path):
    # A dated file is exempt: the version it names is the version that was true.
    dated = tmp_path / "status" / "OLD.md"
    dated.parent.mkdir(parents=True)
    dated.write_text("pip install kinocut==1.15.2\n", encoding="utf-8")
    assert _is_dated(Path("docs/status/OLD.md")) is True


@pytest.mark.parametrize(
    "line",
    [
        "pip install kinocut",
        "pip install kinocut==1.15.2",
        'pip install "kinocut[image]==1.15.2"',
        "uvx kinocut==1.15.2",
        "uvx --from kinocut==1.15.2 kino",
        '"args": ["--from", "kinocut==1.15.2", "kino"]',
        "npm install kinocut@1.15.2",
        "pip install -U mcp-video==1.6.17",
    ],
)
def test_a_wrong_or_missing_release_is_an_offender(tmp_path, line):
    # Pinned is not the same as correct: the sweep compares with the release.
    current = tmp_path / "docs" / "NEW.md"
    current.parent.mkdir(parents=True)
    current.write_text(line + "\n", encoding="utf-8")
    assert _offenders(current, Path("docs/NEW.md"))


@pytest.mark.parametrize(
    "line",
    [
        "pip install kinocut==1.16.5",
        'pip install "kinocut[image]==1.16.5"',
        "uvx kinocut==1.16.5",
        "uvx --from kinocut==1.16.5 kino",
        '"args": ["--from", "kinocut==1.16.5", "kino"]',
        "npm install kinocut@1.16.5",
        "pip install -U mcp-video==1.6.20",
    ],
)
def test_the_current_release_is_not_an_offender(tmp_path, line):
    current = tmp_path / "docs" / "NEW.md"
    current.parent.mkdir(parents=True)
    current.write_text(line + "\n", encoding="utf-8")
    assert not _offenders(current, Path("docs/NEW.md"))
