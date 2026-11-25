"""Wave 5b regression tests for CI, docs, QA runner, and public surface hygiene."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import subprocess
from pathlib import Path

from kinocut.server import mcp
from kinocut.tool_registry import configure_tool_surface
from tests.public_surface_inventory import EXPECTED_SERVER_TOOLS

ROOT = Path(__file__).resolve().parents[1]
QA_RUNNER_PATH = ROOT / "qa" / "runner.py"
QA_CATALOG_PATH = ROOT / "qa" / "operator-paths.yaml"


def _load_qa_runner():
    spec = importlib.util.spec_from_file_location("kinocut_wave5b_qa_runner", QA_RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if re.match(r"\s*`profile:[a-z0-9_-]+`\s+carries\s+", line)]


def test_expected_server_tools_exact_match_kinocut_tools_all() -> None:
    """D8-011: EXPECTED_SERVER_TOOLS locks exact equality with KINOCUT_TOOLS=all (208 tools)."""
    configure_tool_surface("all")
    live_names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert len(live_names) == 208
    assert live_names == EXPECTED_SERVER_TOOLS


def test_plugin_skill_matches_root_skill_guidance() -> None:
    """D8-011: plugin SKILL.md stays in sync with skills/kinocut/SKILL.md without stale next-release copy."""
    root_skill = (ROOT / "skills" / "kinocut" / "SKILL.md").read_text(encoding="utf-8")
    plugin_skill = (ROOT / "plugins" / "kinocut" / "skills" / "kinocut" / "SKILL.md").read_text(encoding="utf-8")

    assert "The next release adds `video_direct`" not in plugin_skill
    assert "## When the user just says what they want (next release)" not in plugin_skill
    assert "## When the user just says what they want\n" in plugin_skill
    assert "`video_direct`, `video_direct_apply`" in plugin_skill
    assert _profile_lines(plugin_skill) == _profile_lines(root_skill)


def test_plugin_readme_has_no_stale_1_16_4_pin() -> None:
    """D8-011: plugins/kinocut/README.md aligns on the 2.0.1 published runtime pin."""
    text = (ROOT / "plugins" / "kinocut" / "README.md").read_text(encoding="utf-8")
    assert "kinocut==1.16.4" not in text
    assert "kinocut==2.0.1" in text


def test_status_now_docs_testing_and_ci_dockerfile_hygiene() -> None:
    """D8-006 + D8-011: NOW.md, docs/TESTING.md, and containers/ci/Dockerfile metadata stay truthful."""
    now_text = (ROOT / "docs" / "status" / "NOW.md").read_text(encoding="utf-8")
    first_nonempty = [line.strip() for line in now_text.splitlines() if line.strip()]
    assert first_nonempty[0] == "# Kinocut now"
    assert first_nonempty[1].startswith("**Published:** 2.0.1")
    assert first_nonempty[2].startswith("**Development candidate:** 2.1.0")
    assert "Runtime 1.16.5 is published" not in now_text
    assert "the18" not in now_text
    assert "passed8,297" not in now_text
    assert "exact2d903f7" not in now_text

    testing_text = (ROOT / "docs" / "TESTING.md").read_text(encoding="utf-8")
    assert "test_real_all_features.py" not in testing_text
    assert "tests/test_real_media.py" in testing_text

    dockerfile = (ROOT / "containers" / "ci" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.14." in dockerfile
    assert "FROM node:24." in dockerfile
    assert "Python 3.14 and Node 24" in dockerfile
    assert "Python 3.13 and Node 22" not in dockerfile


def test_readme_badges_and_contributor_test_commands_aligned() -> None:
    """D8-006 + D8-012: README badges match published counts; CONTRIBUTING & PR template use run_full_suite.py."""
    claims = json.loads((ROOT / "docs" / "public_claims.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"MCP-{claims['published_mcp_tools']}%20tools" in readme
    assert f"CLI-{claims['published_cli_commands']}%20commands" in readme

    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    pr_template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert "python3 scripts/run_full_suite.py" in contributing
    assert "python3 scripts/run_full_suite.py" in pr_template


def test_conftest_uses_canonical_kinocut_rescue_models_import() -> None:
    """D8-018: tests/conftest.py imports kinocut.rescue.models rather than legacy mcp_video alias."""
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "from kinocut.rescue.models import" in conftest
    assert "from mcp_video.rescue.models import" not in conftest


def test_qa_runner_supports_v210_paths_and_portable_browser_tempdir(tmp_path) -> None:
    """D8-008 + D8-019: qa/runner.py avoids hardcoded /tmp and handles all five 2.1.0 operator paths."""
    source = QA_RUNNER_PATH.read_text(encoding="utf-8")
    assert 'dir="/tmp"' not in source

    runner = _load_qa_runner()
    expected_v210 = {
        "trim-music-grid",
        "direct-plan-and-apply",
        "quality-check-dark-grade",
        "offline-doctor",
        "hermes-desktop-plugin",
    }
    assert expected_v210 == set(runner.OPTIONAL_V210_PATH_IDS)
    assert "node" in runner.COMMAND_ALLOWLIST

    catalog = runner.load_catalog(QA_CATALOG_PATH)
    existing_ids = {entry["id"] for entry in catalog["paths"]}
    assert expected_v210.issubset(existing_ids)
    runner.validate_catalog(catalog)

    instance = object.__new__(runner.OperatorRunner)
    instance.product_root = ROOT
    instance.product_problem = None
    instance.product_sha = "0" * 40
    instance.work = tmp_path / "work"
    (instance.work / "artifacts").mkdir(parents=True)
    (instance.work / "fixtures").mkdir(parents=True)
    instance.venv = instance.work / "venv"
    instance.python = instance.venv / "bin" / "python"
    instance.kino = instance.venv / "bin" / "kino"
    instance.hyperframes_executable = None
    instance.installed = True
    instance.fixtures_ready = True
    instance.results = []
    instance.catalog = catalog
    instance.catalog_path = QA_CATALOG_PATH

    seen_envs: list[dict[str, str] | None] = []
    fake_out = instance.work / "artifacts" / "out.mp4"
    fake_out.write_bytes(b"fake")

    def fake_run(argv, *, cwd=None, timeout=180, env=None):
        seen_envs.append(env)
        if argv[0] == "node":
            return subprocess.CompletedProcess(argv, 0, stdout="pass 28\nfail 0\n", stderr="")
        if "doctor" in argv:
            payload = {"summary": {"required_ok": True}, "checks": [{"name": "offline_readiness", "ok": False}]}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")
        if "video-quality-check" in argv:
            payload = {"success": True, "profile": "dark-grade", "overall_score": 92}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")
        out_path = fake_out
        if "-o" in argv:
            idx = argv.index("-o")
            if idx + 1 < len(argv):
                out_path = Path(argv[idx + 1])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(b"fake")
        payload = {"success": True, "output_path": str(out_path)}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    instance._run = fake_run
    instance._ffprobe = lambda _p: {"width": 320, "height": 180, "duration": 2.0, "has_audio": True}
    instance._decode = lambda _p: subprocess.CompletedProcess(["ffmpeg"], 0, stdout="", stderr="")

    for path_id in sorted(expected_v210):
        instance._run_selected(instance._entry(path_id))

    assert [r["status"] for r in instance.results] == ["PASS"] * 5
    assert any(env and env.get("KINOCUT_OFFLINE") == "1" for env in seen_envs)
