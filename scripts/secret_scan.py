#!/usr/bin/env python3
"""Deterministic vendored secret scanner (Head-of-Security card F5, AUDIT-2026-09-15).

Scope and boundaries, stated honestly:
- Scans the git WORKTREE (tracked files only) and the ADDED lines of locally
  available git history (bounded by clone depth; CI clones are shallow).
- Regex rules for known token shapes plus an entropy-gated generic
  assignment rule. No network calls, no dependencies, fully deterministic.
- Known documentation example values and obvious placeholders are suppressed
  (see _PLACEHOLDER_SUBSTRINGS / _EXAMPLE_VALUES). Suppression is exact-match
  or substring, deterministic, and documented here — a real secret that
  happens to contain a placeholder substring would be missed by design;
  the allowlist is the override surface for reviewers, not this list.
- Allowlist (scripts/secret_scan_allowlist.txt) entry forms, each REQUIRING
  a trailing "# reason":
    path                          suppress all findings in that file
    path:LINE                     one worktree line (1-based)
    path:sha256:HEX8              one exact content line (worktree + history)
- Previews are redacted (first 4 chars + length) so CI logs never re-leak.

Exit codes: 0 clean (or everything allowlisted), 1 findings, 2 usage/allowlist error.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("github_pat", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,255}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{24,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("forgejo_salted_token", re.compile(r"\bsha256~[A-Za-z0-9_\-]{40,64}\b")),
    ("stripe_key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    (
        "generic_secret_assignment",
        # Quoted and bare assignment shapes; the captured value is then
        # entropy-gated and placeholder-filtered below.
        re.compile(
            r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)\b\s*[:=]\s*"
            r"(?:[\"'](?P<quoted>[^\"'\n]{12,})[\"']|(?P<bare>[A-Za-z0-9_\-+/=]{16,}))"
        ),
    ),
]

# Canonical documentation example secrets (AWS docs, etc.) — never real.
_EXAMPLE_VALUES = {
    "akiaiosfodnn7example",
    "wjalrxutnfemi/k7mdeng/bpxrficyexamplekey",
    "ghp_abcdefghijklmnopqrstuvwx",
}

_PLACEHOLDER_SUBSTRINGS = (
    "example",
    "sample",
    "placeholder",
    "changeme",
    "change-me",
    "dummy",
    "xxxx",
    "your-name",
    "your_",
    "your-",
    "<your",
    "<the",
    "${",
    "%(",
    "{{",
    "$(",
    "todo",
    "fixme",
    "redacted",
    "notareal",
    "obviously",
    "0123456789",
    "abcdefghijklmnop",
    "qrstuvwxyz012345",
    "...",
)

_ENTROPY_FLOOR = 3.5
_GENERIC_RULE_IDS = {"generic_secret_assignment"}


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    if lowered in _EXAMPLE_VALUES:
        return True
    return any(marker in lowered for marker in _PLACEHOLDER_SUBSTRINGS)


def _redact(value: str) -> str:
    return f"{value[:4]}...[{len(value)} chars]"


def _run_git(root: Path, args: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def load_allowlist(path: Path) -> tuple[set[str], set[str], set[str], list[str]]:
    """Return (whole-file entries, file:line entries, file:hash entries, errors)."""
    files: set[str] = set()
    lines: set[str] = set()
    hashes: set[str] = set()
    errors: list[str] = []
    if not path.exists():
        return files, lines, hashes, errors
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if "#" in entry:
            entry, _, reason = entry.partition("#")
            entry = entry.strip()
            if not reason.strip():
                errors.append(f"{path.name}:{lineno}: allowlist entry needs a '# reason' suffix")
                continue
        else:
            errors.append(f"{path.name}:{lineno}: allowlist entry needs a '# reason' suffix")
            continue
        parts = entry.split(":")
        if len(parts) == 1:
            files.add(parts[0])
        elif len(parts) == 2 and parts[1].isdigit():
            lines.add(f"{parts[0]}:{parts[1]}")
        elif len(parts) == 3 and parts[1] == "sha256" and len(parts[2]) >= 8:
            hashes.add(f"{parts[0]}:{parts[2][:8].lower()}")
        else:
            errors.append(f"{path.name}:{lineno}: unrecognized entry form: {entry}")
    return files, lines, hashes, errors


class Finding:
    __slots__ = ("line", "origin", "path", "rule", "value")

    def __init__(self, rule: str, path: str, line: int, value: str, origin: str) -> None:
        self.rule = rule
        self.path = path
        self.line = line
        self.value = value
        self.origin = origin

    def describe(self) -> str:
        origin = f" [{self.origin}]" if self.origin else ""
        return f"FINDING {self.rule} {self.path}:{self.line}{origin} preview={_redact(self.value)}"


def _match_line(line_text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for rule, pattern in _RULES:
        match = pattern.search(line_text)
        if not match:
            continue
        if rule in _GENERIC_RULE_IDS:
            value = match.group("quoted") or match.group("bare") or ""
            if match.group("bare") and re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
                continue  # identifier reference (SYNTHETIC_TOKEN), not a literal
            if _entropy(value) < _ENTROPY_FLOOR:
                continue
        else:
            value = match.group(0)
        if not value or _is_placeholder(value):
            continue
        hits.append((rule, value))
    return hits


def scan_text_lines(lines: Iterable[str]) -> Iterable[tuple[int, str, str, str]]:
    """Yield (line_number, rule, value, line_text) for each finding in a text blob."""
    for lineno, text in enumerate(lines, start=1):
        for rule, value in _match_line(text):
            yield lineno, rule, value, text


def scan_worktree(root: Path, allow: tuple[set[str], set[str], set[str]]) -> tuple[list[Finding], int, int]:
    files, allow_lines, allow_hashes = allow
    tracked = _run_git(root, ["ls-files"])
    paths = tracked.split("\n") if tracked is not None else [
        str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
    ]
    findings: list[Finding] = []
    suppressed = scanned = 0
    for rel in sorted(p for p in paths if p):
        if rel in files:
            continue
        path = root / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\x00" in raw[:8192]:
            continue  # binary
        scanned += 1
        text_lines = raw.decode("utf-8", errors="replace").split("\n")
        for lineno, rule, value, line_text in scan_text_lines(text_lines):
            digest = hashlib.sha256(line_text.strip().encode()).hexdigest()[:8]
            if f"{rel}:{lineno}" in allow_lines or f"{rel}:{digest}" in allow_hashes:
                suppressed += 1
                continue
            findings.append(Finding(rule, rel, lineno, value, ""))
    return findings, scanned, suppressed


def scan_history(root: Path, allow: tuple[set[str], set[str], set[str]]) -> tuple[list[Finding], int, int]:
    """Scan added lines of locally available history (bounded by clone depth)."""
    files, _allow_lines, allow_hashes = allow
    log = _run_git(root, ["log", "-p", "--no-color", "--full-history", "--diff-filter=AM", "--", "."])
    if log is None:
        print("history: git log unavailable (or not a repo); worktree scan only")
        return [], 0, 0
    findings: list[Finding] = []
    suppressed = commits = 0
    sha = current_file = ""
    lineno = 0
    for raw_line in log.split("\n"):
        if raw_line.startswith("commit ") and re.fullmatch(r"[0-9a-f]{40}", raw_line[7:47]):
            commits += 1
            sha, current_file, lineno = raw_line[7:47], "", 0
        elif raw_line.startswith("+++ b/"):
            current_file = raw_line[6:]
        elif raw_line.startswith("@@ "):
            m = re.search(r"\+(\d+)", raw_line)
            lineno = int(m.group(1)) - 1 if m else 0
        elif current_file and raw_line.startswith("+") and not raw_line.startswith("+++"):
            lineno += 1
            content = raw_line[1:]
            for rule, value in _match_line(content):
                if current_file in files:
                    continue
                digest = hashlib.sha256(content.strip().encode()).hexdigest()[:8]
                if f"{current_file}:{digest}" in allow_hashes:
                    suppressed += 1
                    continue
                findings.append(Finding(rule, current_file, lineno, value, sha[:12]))
    return findings, commits, suppressed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--allowlist",
        default=None,
        help="allowlist path (default: <root>/scripts/secret_scan_allowlist.txt)",
    )
    parser.add_argument("--skip-history", action="store_true", help="scan the worktree only")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    allowlist_path = Path(args.allowlist) if args.allowlist else root / "scripts" / "secret_scan_allowlist.txt"
    allow = load_allowlist(allowlist_path)
    if allow[3]:
        for err in allow[3]:
            print(f"ALLOWLIST ERROR {err}")
        return 2
    allow_set = (allow[0], allow[1], allow[2])

    findings, files_scanned, suppressed = scan_worktree(root, allow_set)
    history_note = ""
    if not args.skip_history:
        h_findings, commits, h_suppressed = scan_history(root, allow_set)
        findings.extend(h_findings)
        suppressed += h_suppressed
        history_note = f", {commits} commits"
    else:
        history_note = ", history skipped"

    for finding in findings:
        print(finding.describe())
    print(
        f"secret-scan: scanned {files_scanned} tracked files{history_note}; "
        f"{len(findings)} findings; {suppressed} allowlisted suppressions"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
