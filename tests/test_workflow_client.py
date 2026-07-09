"""Python client tests for Client.workflow_validate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_video.client import Client
from mcp_video.errors import MCPVideoError


def _valid_spec() -> dict:
    return {
        "schema_version": 1,
        "name": "client-smoke",
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


def _write(tmp_path: Path, spec: dict) -> str:
    path = Path(tmp_path) / "job.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def test_client_workflow_validate_path_returns_verdict(tmp_path):
    verdict = Client().workflow_validate(_write(tmp_path, _valid_spec()))

    assert verdict["valid"] is True
    assert verdict["name"] == "client-smoke"


def test_client_workflow_validate_accepts_dict_spec():
    verdict = Client().workflow_validate(_valid_spec())

    assert verdict["valid"] is True
    assert verdict["ops"] == ["trim"]


def test_client_workflow_validate_raises_on_invalid_spec():
    spec = _valid_spec()
    spec["steps"][0]["op"] = "explode"

    with pytest.raises(MCPVideoError) as exc:
        Client().workflow_validate(spec)
    assert exc.value.code == "unsupported_workflow_op"


def test_client_workflow_validate_is_introspectable():
    info = Client().inspect("workflow_validate")

    assert info["category"] == "workflow"
    assert "spec" in info["parameters"]
