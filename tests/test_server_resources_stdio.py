"""Fresh-process stdio resource registration (t_e3775201 F3 regression guard).

The lazy-facade refactor once dropped every ``mcp-video://`` resource on a
fresh launch: the old facade eagerly imported ``server_resources``; the new one
only imported it through ``__getattr__`` for Python callers. These tests launch
the server the way real clients do — stdio subprocess — and deliberately never
import :mod:`kinocut.server_resources` (nor anything that pulls it in) in this
process, so an unregistered resource cannot be masked by test-side imports.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TEMPLATE_URIS = {
    "mcp-video://video/{path}/info",
    "mcp-video://video/{path}/preview",
    "mcp-video://video/{path}/audio",
}
STATIC_RESOURCE_URI = "mcp-video://templates"


def _template_uris(result) -> set[str]:
    return {
        getattr(t, "uriTemplate", None) or t.uri_template
        for t in (getattr(result, "resourceTemplates", None) or result.resource_templates)
    }


def _resource_uris(result) -> set[str]:
    return {str(r.uri) for r in result.resources}


async def _launch(env_extra: dict[str, str]):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_video"],
        env={**os.environ, **env_extra},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        templates = await session.list_resource_templates()
        resources = await session.list_resources()
        contents = await session.read_resource(STATIC_RESOURCE_URI)
    return templates, resources, contents


def test_resources_registered_on_fresh_stdio_launch_default_mode():
    templates, resources, contents = asyncio.run(_launch({}))

    assert _template_uris(templates) >= EXPECTED_TEMPLATE_URIS
    assert STATIC_RESOURCE_URI in _resource_uris(resources)

    text = next((getattr(c, "text", None) for c in contents.contents if getattr(c, "text", None)), "")
    assert text, "templates resource must return text content"
    payload = json.loads(text)
    assert "aspect_ratios" in payload
    assert "quality_presets" in payload


def test_resources_registered_on_fresh_stdio_launch_all_mode():
    templates, resources, _contents = asyncio.run(_launch({"KINOCUT_TOOLS": "all"}))

    assert _template_uris(templates) >= EXPECTED_TEMPLATE_URIS
    assert STATIC_RESOURCE_URI in _resource_uris(resources)
