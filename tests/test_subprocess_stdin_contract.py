"""AST contract: child processes must explicitly own their stdin, never MCP stdio.

Explicit ``stdin=`` supports DEVNULL/PIPE; ``subprocess.run(input=...)`` also
owns a pipe through the standard library. Explicit None still inherits stdin.
Imports, aliases and asynchronous subprocess calls are included; comments and
nearby calls cannot satisfy this contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("kinocut", "kinocut_sound")
_PROCESS_APIS = {
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "asyncio.subprocess.create_subprocess_exec",
    "asyncio.subprocess.create_subprocess_shell",
}
_NONPROCESS_APIS = {
    "subprocess.TimeoutExpired",
    "subprocess.CalledProcessError",
    "subprocess.SubprocessError",
    "subprocess.CompletedProcess",
    "subprocess.list2cmdline",
}
_CRITICAL_RUNNERS = {
    "kinocut/ffmpeg_helpers.py",
    "kinocut/ffmpeg_progress.py",
    "kinocut/quality_signal_reader.py",
    "kinocut_sound/post/_subprocess.py",
    "kinocut_sound/qa/meter_process.py",
    "kinocut_sound/public/mix_process.py",
    "kinocut_sound/public/mix_process_async.py",
    "kinocut_sound/public/dub_process.py",
}


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return f"{_qualified_name(node.value, aliases)}.{node.attr}"
    return ""


def _process_calls(text: str) -> list[tuple[ast.Call, str]]:
    tree = ast.parse(text)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                aliases[imported.asname or imported.name.split(".")[0]] = (
                    imported.name if imported.asname else imported.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            for imported in node.names:
                aliases[imported.asname or imported.name] = f"{node.module}.{imported.name}"
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _qualified_name(node.func, aliases)
        if target in _NONPROCESS_APIS:
            continue
        if target.startswith("subprocess.") or ".create_subprocess" in target:
            found.append((node, target))
        elif target == "getattr" and node.args:
            module = _qualified_name(node.args[0], aliases)
            if module in {"subprocess", "asyncio", "asyncio.subprocess"}:
                found.append((node, "dynamic subprocess API"))
    return found


def _owns_stdin(call: ast.Call, target: str) -> bool:
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    stdin = keywords.get("stdin")
    if stdin is not None:
        return not (isinstance(stdin, ast.Constant) and stdin.value is None)
    supplied = keywords.get("input") if target == "subprocess.run" else None
    return supplied is not None and not (isinstance(supplied, ast.Constant) and supplied.value is None)


def test_every_subprocess_call_names_stdin_explicitly() -> None:
    offenders, checked_files, checked_packages = [], set(), set()
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            for call, target in _process_calls(path.read_text(encoding="utf-8")):
                relative = path.relative_to(ROOT).as_posix()
                checked_files.add(relative)
                checked_packages.add(package)
                if target not in _PROCESS_APIS or not _owns_stdin(call, target):
                    offenders.append(f"{relative}:{call.lineno} ({target})")
    assert checked_packages == set(PACKAGES), "Both production packages must be scanned"
    assert checked_files >= _CRITICAL_RUNNERS, f"Missing runner coverage: {_CRITICAL_RUNNERS - checked_files}"
    assert not offenders, f"Subprocess calls with unknown APIs or inherited MCP stdin: {offenders}"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import subprocess\nsubprocess.run(['tool']) # stdin is mentioned only here", False),
        ("import subprocess as sp\nsp.Popen(['tool'], stdin=None)", False),
        ("import subprocess\nsubprocess.run(['tool'], input=None)", False),
        ("from subprocess import run as execute\nexecute(['tool'], stdin=-3)", True),
        ("import subprocess\nsubprocess.run(['tool'], input='owned payload')", True),
        ("import asyncio as aio\naio.create_subprocess_exec('tool', stdin=-1)", True),
        ("import asyncio\nasyncio.create_subprocess_exec('tool')", False),
        ("import subprocess\ngetattr(subprocess, 'run')(['tool'])", False),
    ],
)
def test_scanner_requires_actual_explicit_pipe_or_stdin(source: str, expected: bool) -> None:
    calls = _process_calls(source)
    assert calls
    assert all(target in _PROCESS_APIS and _owns_stdin(call, target) for call, target in calls) is expected
