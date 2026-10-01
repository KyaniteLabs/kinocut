"""Keep MCP input schemas and SDK argument validation in agreement."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, get_args

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import create_model, model_validator
from pydantic_core import PydanticCustomError

from .errors import MCPVideoError


def _numeric_boolean_validator(model: Any) -> Any:
    numeric_fields = set()
    for name, field in model.model_fields.items():
        members = get_args(field.annotation) or (field.annotation,)
        if any(member in (int, float) for member in members) and all(
            member in (int, float, type(None)) for member in members
        ):
            numeric_fields.add(name)
            if field.alias:
                numeric_fields.add(field.alias)

    def reject_numeric_booleans(cls: Any, data: Any) -> Any:
        if isinstance(data, dict) and any(isinstance(data.get(name), bool) for name in numeric_fields):
            raise PydanticCustomError("numeric_boolean", "Boolean values are not numeric parameters")
        return data

    return model_validator(mode="before")(classmethod(reject_numeric_booleans))


class _ContractFastMCP(FastMCP):
    """Reject undeclared top-level arguments before a handler executes."""

    def add_tool(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().add_tool(fn, *args, **kwargs)
        name = kwargs.get("name") or (args[0] if args else None) or fn.__name__
        tool = self._tool_manager.get_tool(name)
        if tool is None:
            raise MCPVideoError("MCP tool registration failed", code="tool_registration_failed")
        model = tool.fn_metadata.arg_model
        model.model_config = {**model.model_config, "extra": "forbid"}
        model.model_rebuild(force=True)
        model = create_model(
            model.__name__,
            __base__=model,
            __validators__={"_reject_numeric_booleans": _numeric_boolean_validator(model)},
        )
        tool.fn_metadata.arg_model = model
        tool.parameters = model.model_json_schema(by_alias=True)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tool_manager.get_tool(name)
        if tool is None:
            return await super().call_tool(name, arguments)
        try:
            tool.fn_metadata.arg_model.model_validate(tool.fn_metadata.pre_parse_json(arguments))
        except (ValueError, RecursionError):
            error = MCPVideoError(
                "Invalid MCP tool parameters. Use tools/list to inspect the accepted parameters.",
                error_type="validation_error",
                code="invalid_parameter",
            )
            payload = {"success": False, "error": error.to_dict()}
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=json.dumps(payload))],
                structuredContent=payload,
            )
        return await super().call_tool(name, arguments)
