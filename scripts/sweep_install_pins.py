#!/usr/bin/env python3
"""Move every current install pin to a new release in one pass.

After a release is live on PyPI, every current install or launch instruction
(``pip install kinocut==X``, ``uvx kinocut==X``, ``--from mcp-video==Y`` and the
rest) has to name it; ``tests/test_install_pin_sweep.py`` fails until they do.
This script uses that test's own file set and grammars, so it rewrites exactly
what the test checks and nothing it treats as a dated record:

- release sections and ``Published YYYY-MM-DD`` lines keep their versions;
- only pins on the outgoing release move: a dated fact such as "first shipped
  as ``kinocut[object-matte]==1.15.1``" names another version and stays;
- ``README-PYPI.md`` follows ``pyproject.toml``, not the published release.

Every spelling moves: pip and uvx lines, JSON launch arguments, extras and
``mcp-video==`` pins next to a ``kinocut==`` one. It also moves ``EXPECTED_PINS``
in the test itself, then lists the current lines that still name the outgoing
version in prose ("Published 1.16.5 lists 20 tools"), which need a person.

Usage:
    python scripts/sweep_install_pins.py --kinocut 2.0.0 --mcp-video 1.6.21          # dry run
    python scripts/sweep_install_pins.py --kinocut 2.0.0 --mcp-video 1.6.21 --apply
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / "tests" / "test_install_pin_sweep.py"


def _load_sweep():
    spec = importlib.util.spec_from_file_location("install_pin_sweep", TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pin(distribution: str, version: str) -> re.Pattern[str]:
    """``kinocut==1.16.5``, ``kinocut[ai]==1.16.5`` or ``kinocut@1.16.5``, wherever it sits."""
    return re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(distribution)}(?P<extras>\[[a-z0-9,-]+\])?(?P<op>==|@){re.escape(version)}(?![0-9A-Za-z]|\.[0-9A-Za-z])"
    )


def rewrite(text: str, old: dict[str, str], new: dict[str, str], sweep) -> tuple[str, int, list[tuple[int, str]]]:
    """Move current pins on ``old`` to ``new``.

    Returns the new text, the number of pins moved, and the current lines that
    still name an old version in prose (``Published 1.16.5 lists 20 tools``),
    which a person has to rewrite.
    """
    pins = {distribution: _pin(distribution, version) for distribution, version in old.items()}
    bare = re.compile(rf"(?<![0-9.]){'|'.join(re.escape(v) for v in set(old.values()) - set(new.values()))}(?![0-9])")
    out: list[str] = []
    count = 0
    prose: list[tuple[int, str]] = []
    section_version: str | None = None
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        stripped = line.strip()
        heading = sweep._RELEASE_HEADING.match(stripped)
        if stripped.startswith("#") or heading:
            section_version = heading.group(1) if heading else None
        if section_version is not None or sweep._PUBLISHED_LINE.match(stripped):
            # A release section or a dated line is a record: it keeps its version.
            out.append(line)
            continue
        for distribution, pattern in pins.items():
            line, n = pattern.subn(rf"{distribution}\g<extras>\g<op>{new[distribution]}", line)
            count += n
        if bare.pattern != "(?<![0-9.])(?![0-9])" and bare.search(line):
            prose.append((number, line.strip()))
        out.append(line)
    return "".join(out), count, prose


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kinocut", required=True, help="the kinocut release to pin, e.g. 2.0.0")
    ap.add_argument("--mcp-video", required=True, help="the mcp-video shim release to pin, e.g. 1.6.21")
    ap.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    args = ap.parse_args()

    sweep = _load_sweep()
    old = dict(sweep.EXPECTED_PINS)
    new = {"kinocut": args.kinocut, "mcp-video": args.mcp_video}
    if old == new:
        print(f"already pinned to {new}")
        return 0
    package = sweep._package_version()
    total = 0
    leftovers: list[str] = []
    for path in dict.fromkeys(sweep._current_files()):
        relative = path.relative_to(ROOT)
        before = path.read_text(encoding="utf-8")
        if relative.as_posix() == sweep.PACKAGE_DESCRIPTION:
            after, n, prose = rewrite(before, {**old, "kinocut": package}, {**new, "kinocut": package}, sweep)
        else:
            after, n, prose = rewrite(before, old, new, sweep)
        if n:
            total += n
            print(f"  {'WRITE' if args.apply else 'WOULD'} {relative}: {n} pin(s)")
            if args.apply:
                path.write_text(after, encoding="utf-8")
        leftovers += [f"  {relative}:{number}: {line[:160]}" for number, line in prose]

    test_text = TEST.read_text(encoding="utf-8")
    pins = re.compile(r"^EXPECTED_PINS = \{.*\}$", re.MULTILINE)
    replacement = f'EXPECTED_PINS = {{"kinocut": "{new["kinocut"]}", "mcp-video": "{new["mcp-video"]}"}}'
    print(f"  {'WRITE' if args.apply else 'WOULD'} {TEST.relative_to(ROOT)}: EXPECTED_PINS -> {new}")
    if args.apply:
        TEST.write_text(pins.sub(replacement, test_text, count=1), encoding="utf-8")
    print(f"{total} pin(s) {'moved' if args.apply else 'would move'} from {old} to {new}")
    if leftovers:
        print(f"{len(leftovers)} current line(s) still name an old version in prose; rewrite them by hand:")
        print("\n".join(leftovers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
