#!/usr/bin/env python3
"""Repository readiness audit for maintainability, accessibility, and growth."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "kinocut"

REQUIRED_FILES = [
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "GOVERNANCE.md",
    "MAINTAINERS.md",
    "SECURITY.md",
    "SUPPORT.md",
    "llms.txt",
    "robots.txt",
    "sitemap.xml",
    "server.json",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/DISCUSSION_TEMPLATE/ideas.yml",
    ".github/DISCUSSION_TEMPLATE/q-a.yml",
    ".github/DISCUSSION_TEMPLATE/show-and-tell.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/publish.yml",
    ".github/workflows/pages.yml",
    "docs/AI_AGENT_DISCOVERY.md",
    "docs/git-branch-governance.md",
    "docs/repository-audit-checklist.md",
]


def check(condition: bool, ok: str, bad: str, *, failures: list[str], warnings: list[str], warn: bool = False) -> None:
    if condition:
        print(f"PASS {ok}")
        return
    if warn:
        warnings.append(bad)
        print(f"WARN {bad}")
    else:
        failures.append(bad)
        print(f"FAIL {bad}")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def git_stdout(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    print("== File presence checks ==")
    for file_path in REQUIRED_FILES:
        check(
            (ROOT / file_path).exists(),
            f"{file_path} exists",
            f"Missing required file: {file_path}",
            failures=failures,
            warnings=warnings,
        )

    print("\n== Git hygiene checks ==")
    status = git_stdout("status", "--porcelain")
    check(
        status == "",
        "Working tree is clean",
        "Working tree has uncommitted changes",
        failures=failures,
        warnings=warnings,
        warn=True,
    )

    upstream_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    check(
        upstream_result.returncode == 0,
        "Current branch has an upstream",
        "Current branch has no upstream configured",
        failures=failures,
        warnings=warnings,
        warn=True,
    )

    print("\n== README checks ==")
    readme = read("README.md")
    for section in ["## Installation", "## Quick Start", "## MCP Tools", "## Testing", "## License"]:
        check(
            section in readme,
            f"README contains '{section}'",
            f"README missing expected section '{section}'",
            failures=failures,
            warnings=warnings,
        )

    for doc_link in [
        "CONTRIBUTING.md",
        "SECURITY.md",
        "SUPPORT.md",
        "CODE_OF_CONDUCT.md",
        "CHANGELOG.md",
        "GOVERNANCE.md",
        "MAINTAINERS.md",
        "docs/AI_AGENT_DISCOVERY.md",
    ]:
        check(
            doc_link in readme,
            f"README links {doc_link}",
            f"README should link {doc_link}",
            failures=failures,
            warnings=warnings,
            warn=True,
        )

    print("\n== AI/search discovery checks ==")
    llms = read("llms.txt")
    for phrase in ["MCP server", "FFmpeg", "Claude Code", "Safety Rules For Agents"]:
        check(
            phrase in llms,
            f"llms.txt contains '{phrase}'",
            f"llms.txt missing expected phrase '{phrase}'",
            failures=failures,
            warnings=warnings,
        )

    check(
        "mcp-name: io.github.KyaniteLabs/kinocut" in readme,
        "README contains MCP Registry verification marker",
        "README missing MCP Registry verification marker",
        failures=failures,
        warnings=warnings,
    )

    server_json = read("server.json")
    check(
        '"registryType": "pypi"' in server_json and '"identifier": "kinocut"' in server_json,
        "server.json declares PyPI package metadata",
        "server.json should declare PyPI package metadata",
        failures=failures,
        warnings=warnings,
    )

    robots = read("robots.txt")
    for agent in ["OAI-SearchBot", "GPTBot", "Claude-SearchBot", "Sitemap:"]:
        check(
            agent in robots,
            f"robots.txt mentions {agent}",
            f"robots.txt should mention {agent}",
            failures=failures,
            warnings=warnings,
        )

    print("\n== Metadata checks ==")
    pyproject = read("pyproject.toml")
    for key in ["Homepage =", "Documentation =", "Repository =", "Changelog =", "Discussions ="]:
        check(
            key in pyproject,
            f"pyproject has project URL '{key[:-2]}'",
            f"pyproject missing URL key '{key[:-2]}'",
            failures=failures,
            warnings=warnings,
        )

    version_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    check(
        version_match is not None,
        "Project version is set in pyproject",
        "Unable to find project version in pyproject",
        failures=failures,
        warnings=warnings,
    )
    init_version_match = re.search(r'^__version__\s*=\s*"([^"]+)"', read("kinocut/__init__.py"), flags=re.MULTILINE)
    check(
        bool(version_match and init_version_match and version_match.group(1) == init_version_match.group(1)),
        "pyproject version matches kinocut.__version__",
        "pyproject version should match kinocut.__version__",
        failures=failures,
        warnings=warnings,
    )

    print("\n== Architecture guardrail checks ==")
    for relative_path, max_lines in [
        ("kinocut/engine.py", 140),
        ("kinocut/server.py", 180),
    ]:
        actual_lines = line_count(ROOT / relative_path)
        check(
            actual_lines <= max_lines,
            f"{relative_path} remains a thin facade ({actual_lines} lines)",
            f"{relative_path} should remain a thin facade; found {actual_lines} lines",
            failures=failures,
            warnings=warnings,
        )

    oversized_modules = sorted(
        f"{path.relative_to(ROOT)} ({line_count(path)} lines)"
        for pattern in ["engine*.py", "server*.py"]
        for path in PACKAGE.glob(pattern)
        if line_count(path) > 800
    )
    check(
        oversized_modules == [],
        "Engine/server modules stay below 800 lines",
        "Engine/server modules exceed 800 lines: " + ", ".join(oversized_modules),
        failures=failures,
        warnings=warnings,
    )

    # Facade purity: engine.py and server.py must not define functions/classes
    for relative_path in ("kinocut/engine.py", "kinocut/server.py"):
        path = ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        definitions = [
            node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        if definitions:
            failures.append(f"{relative_path} should re-export/import behavior, not define {definitions}")
            print(f"FAIL {relative_path} defines {definitions}")
        else:
            print(f"PASS {relative_path} is a pure facade")

    # Engine modules must not import the compatibility facade
    facade_import_offenders: list[str] = []
    for path in sorted(PACKAGE.glob("engine*.py")):
        if path.name == "engine.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in ("engine", "kinocut.engine"):
                    facade_import_offenders.append(f"{path.name}: from {node.module} import ...")
                if node.level and node.level >= 1 and node.module == "engine":
                    facade_import_offenders.append(f"{path.name}: from .engine import ...")
                if node.level == 1 and node.module is None:
                    for alias in node.names:
                        if alias.name == "engine":
                            facade_import_offenders.append(f"{path.name}: from . import engine")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kinocut.engine":
                        facade_import_offenders.append(f"{path.name}: import kinocut.engine")
    check(
        facade_import_offenders == [],
        "Engine modules do not import compatibility facade",
        "Engine modules import facade: " + ", ".join(facade_import_offenders),
        failures=failures,
        warnings=warnings,
    )

    # Server tool modules must not import the server facade
    server_tool_offenders: list[str] = []
    for path in sorted(PACKAGE.glob("server_tools_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in ("server", "kinocut.server"):
                    server_tool_offenders.append(f"{path.name}: from {node.module} import ...")
                if node.level and node.level >= 1 and node.module == "server":
                    server_tool_offenders.append(f"{path.name}: from .server import ...")
                if node.level == 1 and node.module is None:
                    for alias in node.names:
                        if alias.name == "server":
                            server_tool_offenders.append(f"{path.name}: from . import server")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kinocut.server":
                        server_tool_offenders.append(f"{path.name}: import kinocut.server")
    check(
        server_tool_offenders == [],
        "Server tool modules do not import server facade",
        "Server tool modules import facade: " + ", ".join(server_tool_offenders),
        failures=failures,
        warnings=warnings,
    )

    # Prevent duplicate canonical helper definitions
    allowed_helper_locations = {
        "_run_ffmpeg": {"kinocut/ffmpeg_helpers.py", "kinocut/engine_runtime_utils.py"},
        "_get_video_duration": {"kinocut/ffmpeg_helpers.py", "kinocut/ai_engine.py"},
        "_seconds_to_srt_time": {"kinocut/ffmpeg_helpers.py"},
    }
    helper_duplicates: list[str] = []
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in allowed_helper_locations:
                expected = allowed_helper_locations[node.name]
                actual = path.relative_to(ROOT).as_posix()
                if actual not in expected:
                    helper_duplicates.append(f"{actual}: {node.name}")
    check(
        helper_duplicates == [],
        "Canonical helpers are not duplicated",
        "Helper duplicates found: " + ", ".join(helper_duplicates),
        failures=failures,
        warnings=warnings,
    )

    print("\n== Release/tag visibility checks ==")
    tags = git_stdout("tag", "--list")
    check(
        tags != "",
        "At least one git tag exists",
        "No git tags found locally; ensure releases are tagged",
        failures=failures,
        warnings=warnings,
        warn=True,
    )

    print("\n== Result ==")
    if failures:
        print(f"FAILURES: {len(failures)}")
        print("- " + "\n- ".join(failures))
    if warnings:
        print(f"WARNINGS: {len(warnings)}")
        print("- " + "\n- ".join(warnings))

    if failures:
        return 1
    print("Repository readiness baseline passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
