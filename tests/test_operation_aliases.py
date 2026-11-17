"""The discovery catalog carries user language; the wire surface does not.

People ask for "a voiceover" or "a reel" where the tool docstrings say
"generate speech audio" or "submit a repurpose job". ``operation_aliases``
appends one line of everyday words to the description the discovery catalog
indexes, so retrieval can match ordinary wording. That line must stay out of
the registered tool description: the default MCP surface, its schema budget
and the generated reference index all read the first line only.
"""

from __future__ import annotations

import asyncio

from kinocut.operation_aliases import OPERATION_ALIASES, operation_alias
from kinocut.tool_families import FAMILY_OF_OPERATION
from kinocut.tool_registry import configure_tool_surface, discovery_catalog


def test_every_alias_names_a_real_operation_and_says_something():
    unknown = sorted(set(OPERATION_ALIASES) - set(FAMILY_OF_OPERATION))
    assert unknown == [], f"alias for an operation that is not registered: {unknown}"
    empty = sorted(name for name, line in OPERATION_ALIASES.items() if not line.strip())
    assert empty == [], f"alias line is empty: {empty}"


def test_discovery_catalog_appends_the_alias_after_the_docstring():
    configure_tool_surface("all")
    from kinocut.server_app import mcp

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    catalog = {row["name"]: row for row in discovery_catalog()}
    for name, line in OPERATION_ALIASES.items():
        description = catalog[name]["description"]
        # After the docstring, never in front of it, so first-line surfaces
        # (list_operations, search_tools, the reference index) stay stable.
        assert description.rstrip().endswith(line), name
        assert not description.startswith(line), name
        assert description.splitlines()[0] == (tools[name].description or "").splitlines()[0], name
    # An operation with no alias keeps its registered description verbatim.
    assert operation_alias("audio_preset") == ""
    assert catalog["audio_preset"]["description"] == (tools["audio_preset"].description or "")


def test_registered_tool_descriptions_do_not_carry_the_alias():
    # The alias is a catalog concern. Folding it into the registered tool
    # description would change the default surface and its schema budget.
    configure_tool_surface("all")
    from kinocut.server_app import mcp

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    leaked = sorted(name for name, line in OPERATION_ALIASES.items() if line in (tools[name].description or ""))
    assert leaked == [], f"alias leaked into the registered tool description: {leaked}"
