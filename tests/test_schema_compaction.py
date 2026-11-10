"""Advertised MCP schemas carry no auto-generated titles (#655 hill-climb).

Pydantic derives a ``title`` for every property from its name
("input_path" -> "Input Path") and one for the arguments model
("<tool>Arguments"). They repeat the property key, carry no validation
meaning, and were about a fifth of the full catalog's input-schema bytes.
"""

from __future__ import annotations

import asyncio

from kinocut.server import mcp
from kinocut.tool_registry import configure_tool_surface


def _schema_titles(node, path="$"):
    """Yield the path of every ``title`` used as a JSON Schema keyword."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("properties", "$defs", "definitions") and isinstance(value, dict):
                # Keys here are property / definition names, not keywords: a
                # parameter literally called ``title`` must survive.
                for name, child in value.items():
                    yield from _schema_titles(child, f"{path}.{key}.{name}")
            elif key == "title" and isinstance(value, str):
                yield path
            else:
                yield from _schema_titles(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _schema_titles(item, f"{path}[{index}]")


def _tools():
    configure_tool_surface("all")
    try:
        return asyncio.run(mcp.list_tools())
    finally:
        configure_tool_surface("all")


def test_no_tool_advertises_auto_generated_schema_titles():
    offenders = {
        tool.name: titles
        for tool in _tools()
        if (titles := [*_schema_titles(tool.inputSchema), *_schema_titles(tool.outputSchema or {})])
    }
    assert offenders == {}


def test_a_parameter_named_title_is_still_advertised():
    with_title = [tool.name for tool in _tools() if "title" in tool.inputSchema.get("properties", {})]
    assert with_title, "a tool with a `title` parameter must keep it after compaction"


def test_annotation_titles_do_not_repeat_the_tool_title():
    repeats = [
        tool.name
        for tool in _tools()
        if tool.annotations is not None and tool.annotations.title is not None and tool.annotations.title == tool.title
    ]
    assert repeats == []
