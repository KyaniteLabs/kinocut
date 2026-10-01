"""Declared MCP parameters survive validation; undeclared ones cannot disappear."""

import asyncio
import inspect
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
import pytest
from pydantic import BaseModel, ConfigDict

from kinocut.server_tool_contracts import _ContractFastMCP


def test_all_registered_argument_models_and_schemas_reject_extras():
    from kinocut.server import mcp

    async def check():
        tools = await mcp.list_tools()
        assert len(tools) == 201
        for tool in tools:
            model = mcp._tool_manager.get_tool(tool.name).fn_metadata.arg_model
            assert model.model_config["extra"] == "forbid", tool.name
            assert tool.inputSchema["additionalProperties"] is False, tool.name

    asyncio.run(check())


def test_async_context_and_arbitrary_declared_mapping_are_preserved():
    app = _ContractFastMCP("test-contract")
    observed = []

    async def handler(value: int, ctx: Context, options: dict | None = None) -> dict:
        observed.append((value, ctx, options))
        return {"value": value, "options": options}

    signature = inspect.signature(handler)
    app.add_tool(handler, name="context-tool")
    context = object()
    result = asyncio.run(
        app._tool_manager.call_tool("context-tool", {"value": 7, "options": {"arbitrary": 9}}, context=context)
    )
    assert result == {"value": 7, "options": {"arbitrary": 9}}
    assert observed == [(7, context, {"arbitrary": 9})]
    assert inspect.signature(handler) == signature
    assert "ctx" not in app._tool_manager.get_tool("context-tool").parameters["properties"]
    rejected = asyncio.run(app.call_tool("context-tool", {"value": 7, "unexpected": 1}))
    assert rejected.isError and rejected.structuredContent["error"]["code"] == "invalid_parameter"
    assert len(observed) == 1
    for arguments in ({"value": "not-an-integer"}, {"value": "not-an-integer", "unexpected": 1}, {"unexpected": 1}):
        rejected = asyncio.run(app.call_tool("context-tool", arguments))
        assert rejected.isError and rejected.structuredContent["error"]["code"] == "invalid_parameter"
    assert len(observed) == 1


def test_nested_argument_validation_is_bounded_before_handler_execution():
    class NestedArguments(BaseModel):
        model_config = ConfigDict(extra="forbid")
        allowed: int

    app = _ContractFastMCP("test-nested-contract")

    def handler(payload: NestedArguments) -> dict:
        return payload.model_dump()

    app.add_tool(handler)
    for arguments in (
        {"payload": {"allowed": 1, "unexpected": 2}},
        {"payload": {"allowed": 1, "unexpected": 2}, "extra": 3},
    ):
        rejected = asyncio.run(app.call_tool("handler", arguments))
        assert rejected.isError and rejected.structuredContent["error"]["code"] == "invalid_parameter"


def test_unknown_parameters_fail_over_actual_stdio_without_echoing_values(sample_video):
    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut", "--mcp"])
        source = sample_video
        secret = "private-argument-value-" + "x" * 20_000
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            rejected = await session.call_tool("video_info", {"input_path": source, "unknown": secret})
            assert rejected.isError
            payload = rejected.structuredContent or json.loads(rejected.content[0].text)
            assert payload["success"] is False
            assert payload["error"]["type"] == "validation_error"
            assert payload["error"]["code"] == "invalid_parameter"
            assert "private-argument-value" not in json.dumps(rejected.model_dump())
            assert len(rejected.content[0].text) < 1000
            for arguments in ({"unknown": secret}, {"input_path": {"secret": secret}, "unknown": secret}):
                mixed = await session.call_tool("video_info", arguments)
                assert mixed.isError
                assert mixed.structuredContent["error"]["code"] == "invalid_parameter"
                assert "private-argument-value" not in json.dumps(mixed.model_dump())
                assert len(mixed.content[0].text) < 1000
            deep_json = "[" * 1500 + "]" * 1500
            for arguments in (
                {"clips": deep_json},
                {"clips": deep_json, "unknown": secret},
                {"clips": "1" * 5000},
            ):
                nested = await session.call_tool("video_merge", arguments)
                assert nested.isError and nested.structuredContent["error"]["code"] == "invalid_parameter"
                assert "private-argument-value" not in json.dumps(nested.model_dump())
            valid = await session.call_tool("video_info", {"input_path": source})
            assert not valid.isError and valid.structuredContent["success"]
            waveform = await session.call_tool("video_audio_waveform", {"input_path": source, "bins": 2})
            assert not waveform.isError and waveform.structuredContent["success"]
            assert len(waveform.structuredContent["peaks"]) == 2
            numeric_boolean = await session.call_tool("video_audio_waveform", {"input_path": source, "bins": True})
            assert numeric_boolean.isError
            assert numeric_boolean.structuredContent["error"]["code"] == "invalid_parameter"
            numeric_string = await session.call_tool("video_audio_waveform", {"input_path": source, "bins": "2"})
            assert not numeric_string.isError and len(numeric_string.structuredContent["peaks"]) == 2
            discovery = await session.call_tool("search_tools", {"query": "resume render"})
            assert not discovery.isError and discovery.structuredContent["success"]

    asyncio.run(check())


def test_handler_raised_validation_error_is_not_misreported_as_argument_error():
    class ResultModel(BaseModel):
        value: int

    app = _ContractFastMCP("handler-error")
    observed = []

    def handler(value: int) -> dict:
        observed.append(value)
        return ResultModel(value="invalid").model_dump()

    app.add_tool(handler)
    with pytest.raises(ToolError):
        asyncio.run(app.call_tool("handler", {"value": 3}))
    assert observed == [3]


def test_numeric_booleans_reject_before_coercion_without_changing_boolean_or_string_parameters():
    app = _ContractFastMCP("numeric-contract")
    observed = []

    def handler(count: int, ratio: float | None = None, enabled: bool = False) -> dict:
        observed.append((count, ratio, enabled))
        return {"count": count, "ratio": ratio, "enabled": enabled}

    app.add_tool(handler)
    for arguments in ({"count": True}, {"count": 2, "ratio": False}):
        rejected = asyncio.run(app.call_tool("handler", arguments))
        assert rejected.isError and rejected.structuredContent["error"]["code"] == "invalid_parameter"
    assert observed == []
    asyncio.run(app.call_tool("handler", {"count": "2", "ratio": "0.5", "enabled": True}))
    assert observed == [(2, 0.5, True)]


@pytest.mark.parametrize("handler_error", [RecursionError("handler recursion"), ValueError("handler value error")])
def test_serialized_argument_limits_are_bounded_without_intercepting_handler_errors(handler_error):
    app = _ContractFastMCP("recursive-contract")
    observed = []

    def handler(options: dict) -> dict:
        observed.append(options)
        raise handler_error

    app.add_tool(handler)
    for value in ("[" * 1500 + "]" * 1500, "1" * 5000):
        rejected = asyncio.run(app.call_tool("handler", {"options": value}))
        assert rejected.isError and rejected.structuredContent["error"]["code"] == "invalid_parameter"
    assert observed == []
    with pytest.raises(ToolError, match=str(handler_error)):
        asyncio.run(app.call_tool("handler", {"options": {}}))
    assert observed == [{}]
