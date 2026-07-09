"""MCP envelope + cross-surface parity tests for video_workflow_validate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mcp_video.client import Client
from mcp_video.server_tools_workflow import video_workflow_validate


def _write_valid_spec(tmp_path: Path) -> str:
    spec = {
        "schema_version": 1,
        "name": "smoke",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {"id": "probe-hero", "op": "probe", "inputs": {"src": "@sources.hero"}},
            {
                "id": "trim-hero",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0, "duration": 6},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }
    path = Path(tmp_path) / "job.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _write_invalid_spec(tmp_path: Path) -> str:
    spec = {
        "schema_version": 1,
        "sources": {"a": {"path": "a.mp4"}},
        "steps": [{"id": "s1", "op": "composite_layers", "inputs": {"src": "@sources.a"}, "output": "@outputs.o"}],
        "outputs": {"o": {"path": "out.mp4"}},
    }
    path = Path(tmp_path) / "bad.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def test_mcp_tool_returns_success_envelope_for_valid_spec(tmp_path):
    result = video_workflow_validate(_write_valid_spec(tmp_path))

    assert result["success"] is True
    assert result["valid"] is True
    assert result["ops"] == ["probe", "trim"]


def test_mcp_tool_returns_structured_error_for_invalid_spec(tmp_path):
    result = video_workflow_validate(_write_invalid_spec(tmp_path))

    assert result["success"] is False
    assert result["error"]["code"] == "unsupported_workflow_op"
    assert "suggested_action" in result["error"]


def test_mcp_tool_returns_structured_error_for_missing_spec():
    result = video_workflow_validate("/definitely/missing/workflow.json")

    assert result["success"] is False
    error = result["error"]
    assert error["code"] == "invalid_input"
    assert error["suggested_action"]["description"]


def _cli_verdict(spec_path: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_video", "--format", "json", "workflow-validate", "--spec", spec_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_mcp_cli_and_client_return_identical_verdicts(tmp_path):
    spec_path = _write_valid_spec(tmp_path)

    mcp_result = video_workflow_validate(spec_path)
    mcp_verdict = {key: value for key, value in mcp_result.items() if key != "success"}
    client_verdict = Client().workflow_validate(spec_path)
    cli_verdict = _cli_verdict(spec_path)

    assert mcp_verdict == client_verdict
    assert cli_verdict == client_verdict
