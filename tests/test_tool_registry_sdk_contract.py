"""Pin the private FastMCP shape the tool registry reads.

The public list_tools() is async and returns wire-level tools without the
callable or schema the registry needs, so the registry reads
mcp._tool_manager._tools. That is private SDK API: this test fails loudly
if an mcp upgrade changes it, and pyproject caps mcp below 2.
"""

import tomllib
from pathlib import Path


def test_registry_private_sdk_shape_is_pinned():
    from kinocut.server_app import mcp

    tools = mcp._tool_manager._tools
    assert isinstance(tools, dict) and tools
    tool = next(iter(tools.values()))
    assert hasattr(tool, "parameters") and hasattr(tool, "description")
    assert callable(mcp._tool_manager.get_tool)


def test_mcp_dependency_has_an_upper_bound():
    root = Path(__file__).resolve().parents[1]
    deps = tomllib.loads((root / "pyproject.toml").read_text())["project"]["dependencies"]
    spec = next(d for d in deps if d.replace(" ", "").startswith("mcp>"))
    assert "<2" in spec.replace(" ", "")
