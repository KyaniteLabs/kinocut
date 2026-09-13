"""Stereo PCM through Python, CLI and actual MCP transports."""

import asyncio
import json
import subprocess
import sys

from kinocut import Client
from tests.test_sound_public_mix import mix_project  # noqa: F401 - stereo fixture dependency
from tests.test_sound_stereo_mix import stereo_project, inspect_stereo  # noqa: F401 - shared fixture


def test_actual_stereo_transport_parity(stereo_project):  # noqa: F811
    root, request = stereo_project
    expected = inspect_stereo(root, Client().sound_mix_render(request, str(root)))
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
            "mix-render",
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
    cli = inspect_stereo(root, json.loads(result.stdout))
    request["output_path"] = "mcp.zip"
    mcp = inspect_stereo(root, asyncio.run(asyncio.wait_for(_mcp(root, request), 45)))
    assert expected["media"] == cli["media"] == mcp["media"]
    assert expected["frame_count"] == cli["frame_count"] == mcp["frame_count"]
    assert expected["source_windows"] == cli["source_windows"] == mcp["source_windows"]


async def _mcp(root, request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        response = await session.call_tool("sound_mix_render", {"request": request, "project_root": str(root)})
        assert not response.isError
        payload = response.structuredContent or json.loads(response.content[0].text)
        result = payload.get("result", payload)
        assert result.pop("success", True) is True
        return result
