"""Real retained PCM through Python, namespaced CLI and actual MCP transports."""

import asyncio
import json
import subprocess
import sys

from kinocut import Client
from tests.test_sound_master_public import master_project, inspect_master  # noqa: F401 - shared fixture


def test_actual_master_transport_parity(master_project):  # noqa: F811
    root, request = master_project
    expected, metrics = inspect_master(root, Client().sound_master_render(request, str(root)))
    request["output_path"] = "cli.zip"
    path = root / "request.json"
    path.write_text(json.dumps(request))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "sound",
            "master-render",
            "--request-json",
            str(path),
            "--project-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    cli, cli_metrics = inspect_master(root, json.loads(result.stdout))
    request["output_path"] = "mcp.zip"
    mcp, mcp_metrics = inspect_master(root, asyncio.run(asyncio.wait_for(_mcp(root, request), 45)))
    assert expected["media"] == cli["media"] == mcp["media"]
    assert metrics == cli_metrics == mcp_metrics
    assert expected["backend"] == cli["backend"] == mcp["backend"]
    assert expected["normalization_type"] == cli["normalization_type"] == mcp["normalization_type"]


async def _mcp(root, request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        response = await session.call_tool("sound_master_render", {"request": request, "project_root": str(root)})
        assert not response.isError
        payload = response.structuredContent or json.loads(response.content[0].text)
        result = payload.get("result", payload)
        assert result.pop("success", True) is True
        return result
