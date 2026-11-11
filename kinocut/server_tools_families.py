"""Compact typed-operation family dispatch tools.

Registers one dispatcher per family from ``kinocut.tool_families`` plus the
``list_operations`` discovery tool and the ``describe_operation`` contract
tool.  Each dispatcher validates ``operation`` against a closed enum of its
family's registry operations, then runs the exact FastMCP tool object that the
direct registration created — the same wrapped handler, the same contract
argument model, the same error payloads — without registering one schema per
operation.

Family-level ``overwrite`` consent is forwarded into the dispatched call
whenever ``params`` does not carry an explicit ``overwrite`` (the inner SDK
argument model would otherwise materialize its own default and silently drop
the family-level consent). Retry hints emitted under family dispatch name the
family tool with the selected operation and only CLI routes that actually
exist (``kino`` subcommands are enumerated from the real parser).

These tools are registered in default and profile modes only; the legacy
``KINOCUT_TOOLS=all`` surface stays exactly the 206-name registry.
"""

import re
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from .errors import MCPVideoError, _cli_command_set, cli_route_for_operation, retry_context
from .output_policy import read_only
from .server_app import _safe_tool, _validation_error, mcp
from .server_tool_contracts import call_shape, parameter_names_hint, validate_tool_arguments
from .tool_families import (
    DESCRIBE_TOOL_NAME,
    DISCOVERY_TOOL_NAME,
    FAMILY_MODULES,
    FAMILY_OF_OPERATION,
    FAMILY_OPEN_WORLD,
    FAMILY_OPERATIONS,
    FAMILY_SUMMARIES,
    FAMILY_TITLES,
    operation_side_effects,
    operation_verb,
)
from .tool_registry import TOOL_REGISTRY, discovery_catalog, load_operation_tool


# Worst-case-accurate for the mutating hints; open-world is decided per family
# by the audited ``FAMILY_OPEN_WORLD`` table (a family is open-world iff any
# supported member or configuration can interact outside a closed domain).
def _family_annotations(name: str) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=FAMILY_OPEN_WORLD[name],
    )


_PARAMS_ANNOTATION = Annotated[
    dict[str, Any] | None,
    Field(description="The operation's arguments."),
]


def _family_invocation(family: str, operation: str) -> str:
    """A retry hint the caller can actually execute on this surface."""

    mcp_hint = f'call {family}(operation="{operation}", params={{...}}) with corrected parameters (MCP)'
    route = cli_route_for_operation(operation)
    if route:
        return f"{mcp_hint} / run kino {route} with corrected flags (CLI)"
    return mcp_hint


_KINO_ROUTE = re.compile(r"\bkino ([a-z0-9][a-z0-9-]*)")

# The discovery tools are MCP-only: their retry hints must not derive a
# ``kino`` route from the tool name (there is no ``kino list-operations``).
_DISCOVERY_INVOCATIONS = {
    tool: f"call {tool} with corrected parameters (MCP)" for tool in (DISCOVERY_TOOL_NAME, DESCRIBE_TOOL_NAME)
}


def _family_retry_message(message: str, family: str, operation: str) -> str:
    """Retarget a baked-in direct-tool retry hint at the family surface.

    Keeps tool-independent hints (``overwrite=true``, ``a new output_path``)
    untouched; rewrites hints that name the direct operation — which is not on
    the default wire — or an unverified ``kino`` route.
    """

    head, sep, invocation = message.partition("; retry with ")
    if not sep:
        return message
    names_direct = f"call {operation} " in invocation or f"call {operation}(" in invocation
    route = _KINO_ROUTE.search(invocation)
    unverified = route is not None and route.group(1) not in _cli_command_set()
    if not (names_direct or unverified):
        return message
    direct_call = re.compile(rf"\bcall {re.escape(operation)}(?=[ )])")
    if not unverified and direct_call.search(invocation):
        # Keep the hint's own action (overwrite=true, a new output_path, the
        # argument names) and only swap the direct tool for the family call.
        family_call = f'call {family}(operation="{operation}", params={{...}})'
        return f"{head}; retry with {direct_call.sub(lambda _: family_call, invocation)}"
    return f"{head}; retry with {_family_invocation(family, operation)}"


def _retarget_retry_hint(result: Any, family: str, operation: str) -> Any:
    """Rewrite the retry hint of an inner error payload for family dispatch."""

    if not isinstance(result, dict) or result.get("success") is not False:
        return result
    error = result.get("error")
    if not isinstance(error, dict) or not isinstance(error.get("message"), str):
        return result
    message = _family_retry_message(error["message"], family, operation)
    if message == error["message"]:
        return result
    return {**result, "error": {**error, "message": message}}


async def _dispatch_family_operation(
    operation: str,
    params: dict[str, Any] | None,
    ctx: Context | None,
    family: str,
    overwrite: bool,
) -> Any:
    """Run one registry operation through its exact registered tool object."""

    tool = load_operation_tool(operation)
    arguments = dict(params or {})
    accepts_overwrite = "overwrite" in (tool.parameters or {}).get("properties", {})
    if accepts_overwrite and "overwrite" not in arguments:
        # The inner SDK argument model materializes its own ``overwrite=False``
        # default and would reset the output-policy ContextVar; forward the
        # family-level consent explicitly. An explicit ``params.overwrite``
        # still wins (strict boolean, validated by the inner contract).
        arguments["overwrite"] = overwrite
    invocation = _family_invocation(family, operation)
    with retry_context(operation, arguments, invocation=invocation):
        try:
            validate_tool_arguments(operation, tool, arguments)
        except MCPVideoError:
            return _validation_error(
                f"Invalid MCP tool parameters for operation '{operation}'. "
                f"Use {DESCRIBE_TOOL_NAME} to inspect its accepted parameters."
                + parameter_names_hint(tool)
                + call_shape(family, tool, operation=operation)
            )
        result = await tool.run(arguments, context=ctx, convert_result=False)
    return _retarget_retry_hint(result, family, operation)


def _register_family_tool(name: str) -> None:
    operations = FAMILY_OPERATIONS[name]
    operation_enum = Literal[operations]  # closed, typed member set

    async def _dispatch(
        operation: operation_enum,  # type: ignore[valid-type]
        params: _PARAMS_ANNOTATION = None,  # type: ignore[assignment]
        overwrite: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await _dispatch_family_operation(operation, params, ctx, name, overwrite)

    _dispatch.__name__ = name
    _dispatch.__qualname__ = name
    _dispatch.__doc__ = FAMILY_SUMMARIES[name]
    _dispatch.__annotations__ = {
        "operation": operation_enum,
        "params": _PARAMS_ANNOTATION,
        "overwrite": bool,
        "ctx": Context | None,
        "return": dict[str, Any],
    }
    mcp.tool(
        name=name,
        title=FAMILY_TITLES[name],
        description=(
            f"{FAMILY_SUMMARIES[name]} Required arguments: {DISCOVERY_TOOL_NAME}; full schema: {DESCRIBE_TOOL_NAME}."
        ),
        annotations=_family_annotations(name),
    )(_safe_tool(_dispatch))


def _operation_row(
    name: str, catalog_by_name: dict[str, dict[str, Any]], annotations_by_name: dict[str, Any]
) -> dict[str, Any]:
    catalog_row = catalog_by_name.get(name, {})
    return {
        "name": name,
        "family": FAMILY_OF_OPERATION[name],
        "verb": operation_verb(name),
        "description": str(catalog_row.get("description") or "").split("\n")[0].strip(),
        "required_params": list(catalog_row.get("required_params") or ()),
        "annotations": annotations_by_name.get(name),
        **operation_side_effects(name),
    }


def _declared_annotations() -> dict[str, Any]:
    """Live MCP annotations per operation — only what registrations declare."""

    from .tool_registry import SURFACE

    tools = SURFACE.registered()
    declared: dict[str, Any] = {}
    for name in TOOL_REGISTRY:
        tool = tools.get(name)
        annotations = getattr(tool, "annotations", None)
        if annotations is None:
            continue
        hints = annotations.model_dump(exclude_none=True, exclude={"title"})
        if hints:
            declared[name] = hints
    return declared


@_safe_tool
@read_only
def list_operations(
    family: Annotated[
        str | None,
        Field(description="Restrict to one family tool name, e.g. video_edit_ops. Omit to list all families."),
    ] = None,
    query: Annotated[
        str | None,
        Field(description="Optional case-insensitive substring filter over operation names, verbs and summaries."),
    ] = None,
) -> dict[str, Any]:
    """On-demand discovery for the compact family surface.

    Loads the complete catalog lazily (like ``search_tools``) and restores the
    selected registration surface afterwards.  Reports each registry operation
    exactly once with its family, verb, required parameters, and only the
    side-effect annotations its registration actually declares. Call
    ``describe_operation`` for one operation's complete inputSchema.
    """

    with retry_context(
        DISCOVERY_TOOL_NAME, {"family": family, "query": query}, invocation=_DISCOVERY_INVOCATIONS[DISCOVERY_TOOL_NAME]
    ):
        if family is not None and family not in FAMILY_MODULES:
            return _validation_error(
                f"Unknown family '{family}'. Available families: {', '.join(FAMILY_MODULES)}",
                code="unknown_family",
            )
        catalog_by_name = {row["name"]: row for row in discovery_catalog()}
        declared = _declared_annotations()
        needle = (query or "").strip().casefold()
        rows = []
        for name in TOOL_REGISTRY:
            if name == DISCOVERY_TOOL_NAME or name not in FAMILY_OF_OPERATION:
                continue
            if family is not None and FAMILY_OF_OPERATION[name] != family:
                continue
            row = _operation_row(name, catalog_by_name, declared)
            if needle and needle not in " ".join((row["name"], row["verb"], row["description"])).casefold():
                continue
            rows.append(row)
        families = [
            {
                "name": family_name,
                "title": FAMILY_TITLES[family_name],
                "operations": len(FAMILY_OPERATIONS[family_name]),
            }
            for family_name in FAMILY_MODULES
            if family is None or family_name == family
        ]
        return {
            "success": True,
            "count": len(rows),
            "families": families,
            "operations": rows,
        }


mcp.tool(
    name=DISCOVERY_TOOL_NAME,
    title="List family operations",
    description=(
        "List operations: families with member counts, and each operation's family, verb, "
        "required parameters and side-effect annotations."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)(list_operations)


@_safe_tool
@read_only
def describe_operation(
    operation: Annotated[
        str,
        Field(description="Registry operation name, e.g. video_ai_remove_silence (find names with list_operations)."),
    ],
) -> dict[str, Any]:
    """Retrieve one operation's complete input contract on demand.

    Returns the operation's full ``inputSchema`` — every optional argument
    with its type, default and nested definitions, byte-for-byte the schema
    its direct tool advertises in ``KINOCUT_TOOLS=all`` mode — plus the
    family tool that dispatches it, required parameters, declared side-effect
    annotations and the verified ``kino`` CLI route when one exists.
    """

    with retry_context(
        DESCRIBE_TOOL_NAME, {"operation": operation}, invocation=_DISCOVERY_INVOCATIONS[DESCRIBE_TOOL_NAME]
    ):
        family = FAMILY_OF_OPERATION.get(operation)
        if family is None:
            return _validation_error(
                f"Unknown operation '{operation}'. Use {DISCOVERY_TOOL_NAME} to enumerate operations.",
                code="unknown_operation",
            )
        tool = load_operation_tool(operation)
        catalog_row = next((row for row in discovery_catalog() if row["name"] == operation), {})
        route = cli_route_for_operation(operation)
        return {
            "success": True,
            "name": operation,
            "family": family,
            "verb": operation_verb(operation),
            "description": str(catalog_row.get("description") or "").split("\n")[0].strip(),
            "required_params": list(catalog_row.get("required_params") or ()),
            "inputSchema": dict(tool.parameters or {}),
            "annotations": _declared_annotations().get(operation),
            "call": {
                "tool": family,
                "operation": operation,
                "params": "arguments exactly per inputSchema",
            },
            **operation_side_effects(operation),
            **({"cli": f"kino {route}"} if route else {}),
        }


mcp.tool(
    name=DESCRIBE_TOOL_NAME,
    title="Describe one operation",
    description=(
        "Return one operation's full inputSchema, the family tool that dispatches it, "
        "and its kino CLI route when one exists."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)(describe_operation)


for _family_name in FAMILY_MODULES:
    _register_family_tool(_family_name)
