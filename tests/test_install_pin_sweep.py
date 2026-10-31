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
DATED_PARTS = ("research", "plans", "archive", "retired", "adr", "release-notes", "proofs")
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


def _grammar(prefix: str) -> re.Pattern[str]:
    """Compile a grammar that captures the version token after the package name."""
    return re.compile(prefix + rf"(?P<version>{VERSION_PATTERN})?")


def _package_grammars(distribution: str) -> tuple[re.Pattern[str], ...]:
    """Every launch grammar that can name this distribution.

    The shim ships as ``mcp-video`` on PyPI and is launched through the same
    forms as the package itself: pip, pipx, uvx, and the ``--from`` and
    ``--with`` launch flags in both their whitespace and JSON-array spellings.
    A grammar that only knows pip leaves the other forms unchecked.
    """
    name = re.escape(distribution)
    extras = r"(?:\[[a-z0-9,-]+\])?"
    return (
        _grammar(rf"pip\s+install(?:\s+--?[\w-]+)*\s+[\"']?{name}{extras}[\"']?"),
        _grammar(rf"pipx\s+run(?:\s+--?[\w-]+)*\s+[\"']?{name}{extras}[\"']?"),
        _grammar(rf"--from(?:[\"']\s*,\s*[\"']|\s+){name}{extras}[\"']?"),
        _grammar(rf"--with(?:[\"']\s*,\s*[\"']|\s+){name}{extras}[\"']?"),
        # A bare `uvx <package>` is a launch wherever it appears: in a code
        # block, in a sentence that tells the reader to run it, or in prose
        # that names the registry entry's stdio package. Only a dated record
        # may keep the version that was true at the time.
        _grammar(rf"(?<![A-Za-z0-9_.-])(?:\$ )?uvx\s+[\"']?{name}{extras}[\"']?"),
    )


INSTALL_GRAMMARS = (
    *(
        (distribution, pattern)
        for distribution in ("kinocut", "mcp-video")
        for pattern in _package_grammars(distribution)
    ),
    # The npm distribution is the package itself; the shim is PyPI-only.
    ("kinocut", _grammar(r"npm\s+install\s+(?:-\S+\s+)*[\"']?kinocut")),
)

#: A bare extra reference names the package too. In prose — a README's
#: mention of the extra, a CLI's own help text — the reader copies it, so
#: it has to name a release. Which release it names is not this rule's
#: business: a current file may record a dated fact ("first shipped as
#: ``kinocut[object-matte]==1.15.1``"), and rewriting that to the current
#: release would make the record false.
BARE_EXTRA_GRAMMARS = (("kinocut", _grammar(r"(?<![A-Za-z0-9_.-])kinocut\[[a-z0-9,-]+\]")),)


def _captured_version(token: str) -> str:
    """The version a capture names, with the installer prefix removed."""
    captured = (token or "").strip()
    for prefix in ("==", "@"):
        if captured.startswith(prefix):
            return captured[len(prefix) :]
    return captured


def _is_dated(relative: Path) -> bool:
    """Whether a path is a dated record rather than a current surface."""
    if _DATED_NAME.match(relative.name):
        # A file named for a day is a record of that day.
        return True
    if relative.name in DATED_FILES:
        return True
    return any(part in DATED_PARTS for part in relative.parts)


#: A release section names the version it describes. What is under such a
#: heading is a record of that release, not a current instruction.
_RELEASE_HEADING = re.compile(r"^(?:#{1,6}\s.*?\b|\*\*)(\d+\.\d+\.\d+)")
#: A line that opens with a publication date is a record of what shipped.
_PUBLISHED_LINE = re.compile(r"^Published\s+\d{4}-\d{2}-\d{2}\b")
#: A file named for a day is a record of that day. The directory it sits in
#: says nothing: a runbook and a release note live in the same place.
_DATED_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _is_dated_line(line: str, dated_section: bool) -> bool:
    """Whether a line records a dated fact rather than giving an instruction.

    A current file may hold history — a README names the release it
    published, and its changelog names every release before that. Those
    records keep the version that was true at the time; rewriting them
    would make the record false. Everything else is an instruction a reader
    may copy, so it has to name the release.

    The classification is structural: a section that names a version, or a
    line that opens with a publication date. A line that merely *contains* a
    date and a version somewhere is not history — otherwise an instruction
    could exempt itself by mentioning a day.
    """
    if dated_section:
        return True
    return bool(_PUBLISHED_LINE.match(line.strip()))


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
        if _DATED_NAME.match(path.name):
            continue
        keep.append(path)
    return keep


def _offenders(path: Path, relative: Path) -> list[str]:
    """The install instructions in one file that do not name the release."""
    offenders: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    section_version: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        heading = _RELEASE_HEADING.match(stripped)
        if stripped.startswith("#") or heading:
            # A heading opens a section. A section that names a release is
            # about that release, and its commands are that release's.
            section_version = heading.group(1) if heading else None
        published = bool(_PUBLISHED_LINE.match(stripped))
        for distribution, grammar in INSTALL_GRAMMARS:
            for match in grammar.finditer(line):
                captured = _captured_version(match.group(1) or "")
                if captured:
                    if captured == EXPECTED_PINS[distribution]:
                        # Correctly pinned to the shipped release, wherever
                        # the line sits.
                        continue
                    if section_version is not None and captured == section_version:
                        # A release section's commands are that release's
                        # commands: the record keeps its own version.
                        continue
                    if published:
                        # A record keeps the version that was true then.
                        continue
                    # A launch that names some other version is a stale
                    # instruction, not a record.
                # No version at all is an instruction, whatever it sits in:
                # a reader can copy it and get something unpinned.
                offender = f"{relative}:{number}: {line.strip()}"
                if offender not in offenders:
                    offenders.append(offender)
        if section_version is not None or published:
            # A record may name the extra as it was.
            continue
        for _distribution, grammar in BARE_EXTRA_GRAMMARS:
            for match in grammar.finditer(line):
                if match.group(1):
                    continue
                offender = f"{relative}:{number}: {line.strip()}"
                if offender not in offenders:
                    offenders.append(offender)
    return offenders


def test_a_bare_extra_reference_is_an_offender(tmp_path):
    # A reader copies a bare extra reference out of prose and installs
    # whatever PyPI serves that day, so it has to name a release.
    path = tmp_path / "README.md"
    path.write_text("Install the `kinocut[object-matte]` extra.\n", encoding="utf-8")
    assert _offenders(path, Path("README.md"))


def test_a_pinned_extra_reference_is_not_an_offender(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("Install the `kinocut[object-matte]==1.16.5` extra.\n", encoding="utf-8")
    assert not _offenders(path, Path("README.md"))


def test_a_prose_command_without_a_pin_is_an_offender(tmp_path):
    # A sentence that tells the reader to run it is a launch, wherever the
    # sentence is and however it is punctuated.
    path = tmp_path / "README.md"
    path.write_text("Run `uvx kinocut doctor` to check the install.\n", encoding="utf-8")
    assert _offenders(path, Path("README.md"))


def test_a_dated_looking_instruction_with_an_unpinned_launch_is_an_offender(tmp_path):
    # A line that mentions a day and a version is not a record: the launch
    # on it is an instruction a reader can copy, so it has to name a
    # release.
    path = tmp_path / "README.md"
    path.write_text(
        "Run on 2026-10-28: uvx kinocut doctor; validated against 1.16.5\n",
        encoding="utf-8",
    )
    assert _offenders(path, Path("README.md"))


def test_a_dated_release_record_keeps_its_own_uvx_mention(tmp_path):
    # The changelog records what the release said at the time. Rewriting it
    # to the current release would make the record false, and a record that
    # names the registry entry does not give the reader a command to copy.
    path = tmp_path / "README.md"
    path.write_text(
        "**1.16.2** (2026-10-21):\n\n"
        "- Official MCP Registry entry republished as the local `uvx` stdio package `kinocut`.\n",
        encoding="utf-8",
    )
    assert not _offenders(path, Path("README.md"))


def test_a_dated_record_with_an_unpinned_launch_is_an_offender(tmp_path):
    # A record may keep a version, but a launch inside it still has to name
    # one: the record is not an exemption for the instruction beside it.
    path = tmp_path / "README.md"
    path.write_text(
        "**1.16.2** (2026-10-21):\n\n- Run `uvx kinocut doctor` to check the install.\n",
        encoding="utf-8",
    )
    assert _offenders(path, Path("README.md"))


def test_a_dated_line_keeps_its_own_version(tmp_path):
    # A current file may record what was true on a day it names.
    path = tmp_path / "README.md"
    path.write_text(
        "Published 2026-10-21: 203 MCP tools; `mcp-video==1.6.17` installs `kinocut==1.16.2`.\n",
        encoding="utf-8",
    )
    assert not _offenders(path, Path("README.md"))


@pytest.mark.parametrize("path", _current_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_current_install_instructions_pin_the_released_version(path):
    offenders = _offenders(path, path.relative_to(ROOT))
    assert not offenders, "current install instructions must pin the released version:\n" + "\n".join(offenders)


def test_the_sweep_covers_the_launch_grammars_it_claims_to_cover():
    # A guard that only knows about pip is not the guard this file promises.
    text = " ".join(grammar.pattern for _distribution, grammar in INSTALL_GRAMMARS)
    for grammar in ("pip", "pipx", "uvx", "--from", "--with", "npm"):
        assert grammar in text
    # The shim is launched through the same grammars, so it needs its own
    # set of patterns — not only an entry in the pin table.
    assert "mcp-video" in {distribution for distribution, _grammar in INSTALL_GRAMMARS}
    shim = " ".join(pattern.pattern for distribution, pattern in INSTALL_GRAMMARS if distribution == "mcp-video")
    for grammar in ("pip", "pipx", "uvx", "--from", "--with"):
        assert grammar in shim


def test_a_dated_record_keeps_its_own_history():
    # A file named for a day is a record of that day; a directory named
    # ``status`` says nothing — a runbook and a release note live in the
    # same place, so the classifier reads the name, not the folder.
    assert _is_dated(Path("docs/notes/2024-01-01-notes.md")) is True
    assert _is_dated(Path("docs/status/OLD.md")) is False


def test_an_obsolete_release_record_keeps_its_own_version(tmp_path):
    # A release section's commands are that release's commands: the record
    # keeps the version that was true then.
    path = tmp_path / "README.md"
    path.write_text("**1.15.2** (2026-09-01):\n\npip install kinocut==1.15.2\n", encoding="utf-8")
    assert not _offenders(path, Path("README.md"))


def test_a_current_runbook_is_not_a_record(tmp_path):
    # A runbook under docs/status is a current surface: an unpinned launch
    # in it is an instruction a reader can copy. The directory name does
    # not make it a record.
    runbook = tmp_path / "RUNBOOK.md"
    runbook.write_text("pip install kinocut\n", encoding="utf-8")
    offenders = _offenders(runbook, Path("docs/status/RUNBOOK.md"))
    assert offenders and "RUNBOOK.md:1" in offenders[0]
    assert _is_dated(Path("docs/status/RUNBOOK.md")) is False


def test_a_current_command_under_an_old_heading_is_an_offender(tmp_path):
    # An old release heading does not shelter a current launch: a command
    # that names no version under it is still an instruction.
    page = tmp_path / "PAGE.md"
    page.write_text("## 1.15.2\n\npip install kinocut\n", encoding="utf-8")
    offenders = _offenders(page, Path("docs/PAGE.md"))
    assert offenders and "PAGE.md:3" in offenders[0]


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
        # The shim is launched through the same grammars as the package, and
        # every one of them must catch a wrong or missing release.
        "pipx run mcp-video",
        "pipx run mcp-video==1.6.17",
        "uvx mcp-video",
        "uvx mcp-video==1.6.17",
        "uvx --from mcp-video mcp-video doctor --json",
        "uv run --no-project --with mcp-video python workflow.py",
        '"args": ["--from", "mcp-video==1.6.17", "mcp-video"]',
        '"args": ["--with", "mcp-video==1.6.17"]',
    ],
)
def test_a_wrong_or_missing_release_is_an_offender(tmp_path, line):
    # Pinned is not the same as correct: the sweep compares with the release.
    current = tmp_path / "docs" / "NEW.md"
    current.parent.mkdir(parents=True, exist_ok=True)
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
        # The shim's launch forms, pinned to the release it ships.
        "pipx run mcp-video==1.6.20",
        "uvx mcp-video==1.6.20",
        "uvx --from mcp-video==1.6.20 mcp-video doctor --json",
        "uv run --no-project --with mcp-video==1.6.20 python workflow.py",
        '"args": ["--from", "mcp-video==1.6.20", "mcp-video"]',
        '"args": ["--with", "mcp-video==1.6.20"]',
    ],
)
def test_the_current_release_is_not_an_offender(tmp_path, line):
    current = tmp_path / "docs" / "NEW.md"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(line + "\n", encoding="utf-8")
    assert not _offenders(current, Path("docs/NEW.md"))


def test_a_proof_record_is_historical_not_a_current_surface():
    # A dated proof is history: it keeps the version that was true then.
    # Leaving it in the current scan with an invisible grammar is what the
    # reviewer found, so the classification is asserted rather than assumed.
    assert _is_dated(Path("docs/proofs/2026-06-03-fresh-install-confidence-baseline.md")) is True
    assert Path("docs/proofs/2026-06-03-fresh-install-confidence-baseline.md") not in _current_files()
