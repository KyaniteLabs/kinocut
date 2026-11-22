"""Keep MCP input schemas and SDK argument validation in agreement."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, get_args

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import create_model, model_validator
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import PydanticCustomError

from .errors import MCPVideoError
from .tool_docstrings import fold_args
from .tool_families import DESCRIBE_TOOL_NAME, FAMILY_OF_OPERATION


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


_BOOLEAN_POLICY_TOOLS: dict[str, tuple[str, ...]] = {
    "video_mix_audio": ("keep_source",),
    "video_repurpose": ("include_release_checkpoint", "start_job"),
}


_HINT_NAME_LIMIT = 12

# Spellings agents reach for instead of the compact surface's two dispatch
# arguments. Renamed only when the tool declares the canonical name, does not
# declare the alias itself, and the call did not also pass the canonical name.
_ARGUMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "operation": ("name", "op", "operation_name"),
    "params": ("args", "arguments", "parameters"),
}


def forgive_argument_aliases(tool: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Rename a known alias (``name`` for ``operation``) to the declared argument."""

    declared = (getattr(tool, "parameters", None) or {}).get("properties") or {}
    renamed = dict(arguments)
    for canonical, aliases in _ARGUMENT_ALIASES.items():
        if canonical not in declared or canonical in renamed:
            continue
        present = [alias for alias in aliases if alias in renamed and alias not in declared]
        if len(present) == 1:
            renamed[canonical] = renamed.pop(present[0])
    return renamed


def call_shape(tool_name: str, tool: Any, *, operation: str | None = None) -> str:
    """One line showing a correct call, built from the schema's required names only."""

    schema = getattr(tool, "parameters", None) or {}
    accepted = (schema.get("properties") or {}).keys()
    required = [name for name in schema.get("required") or () if name in accepted]
    args = ", ".join(f"{name}=..." for name in required)
    if operation is None:
        return f" Call: {tool_name}({args})."
    return f' Call: {tool_name}(operation="{operation}", params={{{args}}}).'


def parameter_names_hint(tool: Any) -> str:
    """Name the tool's required and accepted parameters, from its own schema.

    Only schema-declared names appear, never the caller's keys or values, so
    the hint cannot reflect injected input back to the agent.
    """

    schema = getattr(tool, "parameters", None) or {}
    accepted = list((schema.get("properties") or {}).keys())
    if not accepted:
        return ""
    required = [name for name in schema.get("required") or () if name in accepted]
    shown = accepted[:_HINT_NAME_LIMIT]
    more = len(accepted) - len(shown)
    accepted_text = ", ".join(shown) + (f" and {more} more" if more else "")
    required_text = f"Required: {', '.join(required)}. " if required else ""
    return f" {required_text}Accepted: {accepted_text}."


def validate_tool_arguments(name: str, tool: Any, arguments: dict[str, Any]) -> None:
    """Run the wire-path argument checks for ``tool`` before it executes.

    Shared by ``call_tool`` (the direct wire path) and the compact family
    dispatchers so both reject the same arguments with the same payload:
    explicit-boolean policy fields, pre-parsed mix sounds, and the contract
    argument model (undeclared top-level arguments, numeric booleans). Raises
    ``MCPVideoError`` with the generic wire message on any rejection.
    """

    try:
        for field in _BOOLEAN_POLICY_TOOLS.get(name, ()):
            if field in arguments and type(arguments[field]) is not bool:
                raise MCPVideoError("Policy parameters require explicit booleans", code="invalid_parameter")
        if name == "video_mix_audio" and "sounds" in arguments:
            from .audio_mix_inputs import parse_mix_sounds

            parse_mix_sounds(arguments["sounds"])
        tool.fn_metadata.arg_model.model_validate(tool.fn_metadata.pre_parse_json(arguments))
    except (ValueError, RecursionError, MCPVideoError):
        raise MCPVideoError(
            "Invalid MCP tool parameters. Use tools/list to inspect the accepted parameters."
            + parameter_names_hint(tool)
            + call_shape(name, tool),
            error_type="validation_error",
            code="invalid_parameter",
        ) from None


class _UntitledSchema(GenerateJsonSchema):
    """Omit the titles pydantic derives from field names ("input_path" -> "Input Path").

    They restate the property key, carry no validation meaning, and were
    about a sixth of every advertised inputSchema. Titles a field declares
    explicitly are kept.
    """

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False


def _compact_tool_metadata(tool: Any) -> None:
    """Drop advertised metadata that only repeats something else in the listing."""
    tool.parameters.pop("title", None)  # "<name>Arguments" repeats the tool name
    output_schema = tool.fn_metadata.output_schema
    if output_schema is not None:
        output_schema.pop("title", None)  # "<name>DictOutput" likewise
    annotations = tool.annotations
    if annotations is not None and annotations.title is not None and annotations.title == tool.title:
        tool.annotations = annotations.model_copy(update={"title": None})


def _failed_payload(structured: Any) -> bool:
    if not isinstance(structured, dict):
        return False
    # FastMCP wraps non-object returns as {"result": ...}; look through it.
    if set(structured) == {"result"} and isinstance(structured["result"], dict):
        structured = structured["result"]
    return structured.get("success") is False


def _flag_failure(result: Any) -> Any:
    """Mark a tool's own ``success: false`` result as an MCP error.

    Tools turn exceptions into ``{"success": false, "error": ...}``. Without
    ``isError`` the host treats that as a successful call and shows a check
    mark for a render that failed.
    """
    if isinstance(result, tuple) and len(result) == 2:
        unstructured, structured = result
    elif isinstance(result, dict):
        unstructured, structured = [TextContent(type="text", text=json.dumps(result, indent=2))], result
    else:
        return result
    if not _failed_payload(structured):
        return result
    return CallToolResult(isError=True, content=list(unstructured), structuredContent=structured)


class _ContractFastMCP(FastMCP):
    """Reject undeclared top-level arguments before a handler executes."""

    def add_tool(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        from .output_policy import with_output_policy

        fn = with_output_policy(fn)
        super().add_tool(fn, *args, **kwargs)
        name = kwargs.get("name") or (args[0] if args else None) or fn.__name__
        tool = self._tool_manager.get_tool(name)
        if tool is None:
            raise MCPVideoError("MCP tool registration failed", code="tool_registration_failed")
        annotations = tool.annotations
        if annotations is not None and annotations.readOnlyHint and "overwrite" in tool.parameters["properties"]:
            raise MCPVideoError("A readOnlyHint tool must not offer overwrite consent", code="tool_registration_failed")
        model = tool.fn_metadata.arg_model
        model.model_config = {**model.model_config, "extra": "forbid"}
        model.model_rebuild(force=True)
        model = create_model(
            model.__name__,
            __base__=model,
            __validators__={"_reject_numeric_booleans": _numeric_boolean_validator(model)},
        )
        tool.fn_metadata.arg_model = model
        tool.parameters = model.model_json_schema(by_alias=True, schema_generator=_UntitledSchema)
        tool.description = fold_args(tool.description, tool.parameters)
        _compact_tool_metadata(tool)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tool_manager.get_tool(name)
        if tool is None:
            self._raise_if_unlisted_operation(name)
            return await super().call_tool(name, arguments)
        arguments = forgive_argument_aliases(tool, arguments)
        try:
            validate_tool_arguments(name, tool, arguments)
        except MCPVideoError as error:
            payload = {"success": False, "error": error.to_dict()}
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=json.dumps(payload))],
                structuredContent=payload,
            )
        return _flag_failure(await super().call_tool(name, arguments))

    def _raise_if_unlisted_operation(self, name: str) -> None:
        """Point a by-name call of a family-served operation at its family.

        On the default and profile surfaces most operations are not listed by
        name, and the wire stays fail-closed for them. An agent that calls one
        directly (from 1.x guidance or memory) would otherwise see a bare
        "Unknown tool" and conclude the operation is unavailable.
        """

        family = FAMILY_OF_OPERATION.get(name)
        if family is None or self._tool_manager.get_tool(family) is None:
            return
        raise ToolError(
            f"Unknown tool: {name}. It is not listed by name on this surface; "
            f'call {family}(operation="{name}", params={{...}}) instead. '
            f"{DESCRIBE_TOOL_NAME} returns its parameters."
        )
