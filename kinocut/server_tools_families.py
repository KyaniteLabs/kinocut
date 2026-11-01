"""Compact typed-operation family dispatch tools.

Registers one dispatcher per family from ``kinocut.tool_families`` plus the
``list_operations`` discovery tool.  Each dispatcher validates ``operation``
against a closed enum of its family's registry operations, then runs the exact
FastMCP tool object that the direct registration created — the same wrapped
handler, the same contract argument model, the same error payloads — without
registering one schema per operation.

These tools are registered in default and profile modes only; the legacy
``KINOCUT_TOOLS=all`` surface stays exactly the 205-name registry.
"""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from .server_app import _safe_tool, _validation_error, mcp
from .server_tool_contracts import validate_tool_arguments
from .tool_families import (
    DISCOVERY_TOOL_NAME,
    FAMILY_MODULES,
    FAMILY_OF_OPERATION,
    FAMILY_OPERATIONS,
    FAMILY_SUMMARIES,
    FAMILY_TITLES,
    operation_side_effects,
    operation_verb,
)
from .tool_registry import TOOL_REGISTRY, load_operation_tool

# Worst-case-accurate: every family dispatches operations that write rendered
# artifacts, so the family tool itself is mutating, not idempotent, and closed.
_FAMILY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)

_PARAMS_ANNOTATION = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Arguments for the operation, exactly as its direct tool accepts them "
            "(see list_operations for required parameters)."
        )
    ),
]


async def _dispatch_family_operation(operation: str, params: dict[str, Any] | None, ctx: Context | None) -> Any:
    """Run one registry operation through its exact registered tool object."""

    tool = load_operation_tool(operation)
    arguments = dict(params or {})
    validate_tool_arguments(operation, tool, arguments)
    return await tool.run(arguments, context=ctx, convert_result=False)


def _register_family_tool(name: str) -> None:
    operations = FAMILY_OPERATIONS[name]
    operation_enum = Literal[operations]  # closed, typed member set
    family_hint = ", ".join(FAMILY_MODULES[name])

    async def _dispatch(
        operation: operation_enum,  # type: ignore[valid-type]
        params: _PARAMS_ANNOTATION = None,  # type: ignore[assignment]
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await _dispatch_family_operation(operation, params, ctx)

    _dispatch.__name__ = name
    _dispatch.__qualname__ = name
    _dispatch.__doc__ = FAMILY_SUMMARIES[name]
    _dispatch.__annotations__ = {
        "operation": operation_enum,
        "params": _PARAMS_ANNOTATION,
        "ctx": Context | None,
        "return": dict[str, Any],
    }
    mcp.tool(
        name=name,
        title=FAMILY_TITLES[name],
        description=(
            f"{FAMILY_SUMMARIES[name]} Registry modules: {family_hint}. "
            f"Use {DISCOVERY_TOOL_NAME} to enumerate members with required parameters."
        ),
        annotations=_FAMILY_ANNOTATIONS,
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

    from .tool_registry import _HIDDEN_TOOLS, _tool_manager

    tools: dict[str, Any] = {**_tool_manager()._tools, **_HIDDEN_TOOLS}
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
    side-effect annotations its registration actually declares.
    """

    from .tool_registry import discovery_catalog

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
        "Enumerate compact-surface operations on demand: families with member counts, and each "
        "operation's family, verb, required parameters and declared side-effect annotations. "
        "Optional family or query filters. Complements search_tools."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)(list_operations)

for _family_name in FAMILY_MODULES:
    _register_family_tool(_family_name)
