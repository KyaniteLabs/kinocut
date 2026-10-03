"""Dry-run estimates reject invalid arithmetic at the shared engine boundary."""

import argparse
import asyncio
import json
import math

import pytest

from kinocut.cli.handlers_intent import handle_intent_commands
from kinocut.cli.parser.intent import add_parsers
from kinocut.client.estimates import ClientEstimatesMixin
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_ESTIMATE_OPERATION_CHARS
from kinocut.server_tool_contracts import _ContractFastMCP
from kinocut.server_tools_intent import video_estimate_operation
from kinocut.te.cost_oracle import estimate_operation


def _invoke(route, arguments, capsys):
    if route == "engine":
        return estimate_operation(**arguments)
    if route == "client":
        return ClientEstimatesMixin().estimate_operation(**arguments)
    if route == "mcp":
        app = _ContractFastMCP("estimate-validation")
        app.add_tool(video_estimate_operation)
        result = asyncio.run(app.call_tool("video_estimate_operation", arguments))
        payload = result[1] if isinstance(result, tuple) else result.structuredContent
        if payload.get("success") is False:
            error = payload["error"]
            raise MCPVideoError(error["message"], code=error["code"])
        return payload
    parser = argparse.ArgumentParser()
    add_parsers(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "estimate",
            arguments["operation"],
            "--duration=" + str(arguments["duration_seconds"]),
            "--complexity=" + str(arguments.get("complexity", 1.0)),
        ]
    )
    assert handle_intent_commands(args, use_json=True)
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("route", ["engine", "client", "mcp", "cli"])
@pytest.mark.parametrize("operation", ["trim", " STILL-PACKAGE ", "default", "unknown"])
def test_finite_aliases_and_default_estimates_are_not_billing(route, operation, capsys):
    result = _invoke(route, {"operation": operation, "duration_seconds": 10, "complexity": 2}, capsys)
    expected = estimate_operation(operation, duration_seconds=10, complexity=2)
    assert {key: result[key] for key in expected} == expected
    assert result["currency"] is None and result["dry_run"] is True
    assert math.isfinite(result["estimated_wall_seconds"])


@pytest.mark.parametrize("route", ["engine", "client", "mcp", "cli"])
@pytest.mark.parametrize(
    "name, value, code",
    [
        ("duration_seconds", -1, "invalid_duration"),
        ("duration_seconds", float("nan"), "invalid_duration"),
        ("duration_seconds", float("inf"), "invalid_duration"),
        ("complexity", 0, "invalid_complexity"),
        ("complexity", -1, "invalid_complexity"),
        ("complexity", float("nan"), "invalid_complexity"),
        ("complexity", float("inf"), "invalid_complexity"),
    ],
)
def test_nonfinite_and_out_of_range_inputs_fail_closed(route, name, value, code, capsys):
    arguments = {"operation": "trim", "duration_seconds": 10, "complexity": 1}
    arguments[name] = value
    with pytest.raises(MCPVideoError) as error:
        _invoke(route, arguments, capsys)
    assert error.value.code == code


@pytest.mark.parametrize("route", ["engine", "client", "mcp", "cli"])
def test_finite_inputs_cannot_return_overflowed_estimate(route, capsys):
    with pytest.raises(MCPVideoError) as error:
        _invoke(route, {"operation": "upscale", "duration_seconds": 1e308, "complexity": 1e308}, capsys)
    assert error.value.code == "invalid_estimate"


@pytest.mark.parametrize("route", ["engine", "client", "mcp"])
@pytest.mark.parametrize("name", ["duration_seconds", "complexity"])
@pytest.mark.parametrize("value", [True, False, 10**1000, None, []])
def test_invalid_numeric_types_raise_structured_errors(route, name, value, capsys):
    arguments = {"operation": "trim", "duration_seconds": 10, "complexity": 1}
    arguments[name] = value
    with pytest.raises(MCPVideoError) as error:
        _invoke(route, arguments, capsys)
    expected = "invalid_complexity" if name == "complexity" else "invalid_duration"
    assert error.value.code in {expected, "invalid_parameter"}


@pytest.mark.parametrize("route", ["engine", "client", "mcp"])
@pytest.mark.parametrize("value", [None, True, 7, [], {}, "", "   ", "x" * (MAX_ESTIMATE_OPERATION_CHARS + 1)])
def test_operation_shape_and_length_rejected(route, value, capsys):
    with pytest.raises(MCPVideoError) as error:
        _invoke(route, {"operation": value, "duration_seconds": 10}, capsys)
    assert error.value.code in {"invalid_operation", "invalid_parameter"}


@pytest.mark.parametrize("route", ["engine", "client"])
def test_numeric_strings_are_not_direct_api_numbers(route, capsys):
    with pytest.raises(MCPVideoError) as error:
        _invoke(route, {"operation": "trim", "duration_seconds": "10"}, capsys)
    assert error.value.code == "invalid_duration"


def test_mcp_preserves_existing_numeric_string_compatibility(capsys):
    result = _invoke("mcp", {"operation": "trim", "duration_seconds": "10", "complexity": "2"}, capsys)
    assert result["estimated_wall_seconds"] == 1.0


def test_zero_duration_and_maximum_operation_length_remain_valid():
    result = estimate_operation("x" * MAX_ESTIMATE_OPERATION_CHARS, duration_seconds=0)
    assert result["estimated_wall_seconds"] == result["estimated_cost_units"] == 0
