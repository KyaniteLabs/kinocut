"""Cached local recognition through actual Python, CLI and MCP surfaces."""

import asyncio
import json
import subprocess
import sys

from kinocut import Client
from tests.test_sound_asr_public import asr_project  # noqa: F401


def test_actual_asr_transport_parity(asr_project):  # noqa: F811
    root, prepare = asr_project
    request = prepare()
    expected = Client().sound_qa_asr(request=request, project_root=str(root))
    request["output_path"] = "cli.zip"
    path = root / "request.json"
    path.write_text(json.dumps(request))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "sound",
            "qa-asr",
            "--request-json",
            str(path),
            "--project-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr
    cli = json.loads(completed.stdout)
    request["output_path"] = "mcp.zip"
    mcp = asyncio.run(asyncio.wait_for(_mcp(root, request), 45))
    for key in ("transcript_sha256", "comparison", "backend", "verification_status"):
        assert expected[key] == cli[key] == mcp[key]


async def _mcp(root, request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        response = await session.call_tool("sound_qa_asr", {"request": request, "project_root": str(root)})
        assert not response.isError
        payload = response.structuredContent or json.loads(response.content[0].text)
        result = payload.get("result", payload)
        assert result.pop("success", True) is True
        return result
