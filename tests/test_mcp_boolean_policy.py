"""Quality and audio policy flags survive the actual MCP admission boundary."""

import asyncio
import json
from unittest.mock import Mock

import pytest

from kinocut.models import EditResult


@pytest.fixture(
    params=[
        ("video_repurpose", "include_release_checkpoint", "include_release_checkpoint"),
        ("video_repurpose", "start_job", "start"),
        ("video_mix_audio", "keep_source", "keep_source"),
    ],
    ids=["release-checkpoint", "start-job", "source-audio"],
)
def policy_route(request, monkeypatch):
    from kinocut.server import mcp

    name, field, forwarded = request.param
    validate = Mock(return_value="input.mp4")
    monkeypatch.setattr("kinocut.server_tools_repurpose._validate_input_path", validate)
    if name == "video_repurpose":
        engine = Mock(return_value={"job_id": "test-job"})
        monkeypatch.setattr("kinocut.projectstore.repurpose.durable_repurpose", engine)
        arguments = {"input_path": "input.mp4", "output_dir": "unused-project"}
    else:
        engine = Mock(return_value=EditResult(output_path="mixed.mp4"))
        monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", engine)
        arguments = {"input_path": "input.mp4", "sounds": [{"path": "sound.wav"}]}
    return mcp, name, field, forwarded, arguments, engine, validate


@pytest.mark.parametrize("value", [True, False])
def test_actual_call_preserves_explicit_boolean_policy(policy_route, value):
    mcp, name, field, forwarded, arguments, engine, _ = policy_route
    result = asyncio.run(mcp.call_tool(name, {**arguments, field: value}))
    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload["success"] is True
    engine.assert_called_once()
    assert engine.call_args.kwargs[forwarded] is value


def test_actual_call_preserves_default_enabled_policy(policy_route):
    mcp, name, _, forwarded, arguments, engine, _ = policy_route
    result = asyncio.run(mcp.call_tool(name, arguments))
    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload["success"] is True
    engine.assert_called_once()
    assert engine.call_args.kwargs[forwarded] is True


@pytest.mark.parametrize("value", [0, 1, "false", "true", "0", "1", None, []])
def test_actual_call_rejects_coercible_policy_before_engine_or_job(policy_route, value):
    mcp, name, field, _, arguments, engine, validate = policy_route
    result = asyncio.run(mcp.call_tool(name, {**arguments, field: value}))
    assert result.isError is True
    assert result.structuredContent["success"] is False
    error = result.structuredContent["error"]
    assert error["type"] == "validation_error"
    assert error["code"] == "invalid_parameter"
    engine.assert_not_called()
    validate.assert_not_called()


def test_actual_call_redacts_invalid_policy_value(policy_route):
    mcp, name, field, _, arguments, engine, _ = policy_route
    secret = "private-policy-token-" + "x" * 20_000
    result = asyncio.run(mcp.call_tool(name, {**arguments, field: secret}))
    assert result.isError is True
    assert "private-policy-token" not in json.dumps(result.model_dump())
    assert len(result.content[0].text) < 1000
    engine.assert_not_called()


def test_actual_repurpose_keeps_existing_numeric_string_compatibility(monkeypatch):
    from kinocut.server import mcp

    monkeypatch.setattr("kinocut.server_tools_repurpose._validate_input_path", lambda path: path)
    engine = Mock(return_value={"job_id": "test-job"})
    monkeypatch.setattr("kinocut.projectstore.repurpose.durable_repurpose", engine)
    result = asyncio.run(
        mcp.call_tool(
            "video_repurpose",
            {
                "input_path": "input.mp4",
                "output_dir": "unused-project",
                "include_release_checkpoint": False,
                "start_job": False,
                "min_score": "80.5",
            },
        )
    )
    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload["success"] is True
    assert engine.call_args.kwargs["min_score"] == 80.5
    assert engine.call_args.kwargs["include_release_checkpoint"] is False
    assert engine.call_args.kwargs["start"] is False
