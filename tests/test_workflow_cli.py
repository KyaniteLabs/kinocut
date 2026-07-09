"""CLI tests for the workflow-validate command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mcp_video", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _write_valid_spec(tmp_path: Path) -> str:
    spec = {
        "schema_version": 1,
        "name": "cli-smoke",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {
                "id": "trim-hero",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0, "duration": 3},
                "output": "@outputs.master",
            }
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }
    path = Path(tmp_path) / "job.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def test_cli_workflow_validate_json_valid(tmp_path):
    result = _run_cli(["--format", "json", "workflow-validate", "--spec", _write_valid_spec(tmp_path)])

    assert result.returncode == 0, result.stderr
    verdict = json.loads(result.stdout)
    assert verdict["valid"] is True
    assert verdict["name"] == "cli-smoke"
    assert verdict["ops"] == ["trim"]


def test_cli_workflow_validate_text_valid(tmp_path):
    result = _run_cli(["workflow-validate", "--spec", _write_valid_spec(tmp_path)])

    assert result.returncode == 0, result.stderr
    assert "Workflow Validation" in result.stdout


def test_cli_workflow_validate_fails_closed_on_bad_op(tmp_path):
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "explode", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    path = Path(tmp_path) / "bad.json"
    path.write_text(json.dumps(spec), encoding="utf-8")

    result = _run_cli(["--format", "json", "workflow-validate", "--spec", str(path)])

    assert result.returncode == 1
    error = json.loads(result.stderr)
    assert error["success"] is False
    assert error["error"]["code"] == "unsupported_workflow_op"
