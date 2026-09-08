"""Actual routed media and compact evidence across Python, CLI and MCP."""

import asyncio
import hashlib
import json
import subprocess
import sys
import zipfile

import pytest

from kinocut import Client
from kinocut_sound._canonical import canonical_digest
from kinocut_sound.mix._wav import decode_pcm_wav
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401


def inspect_routed(root, result, stereo):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, _, channels = decode_pcm_wav(archive.read("master.wav"))
        for name, metadata in receipt["media"].items():
            data = archive.read(name)
            assert metadata == {"bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    assert tuple(pcm[:channels]) == ((8000, 4000) if stereo else (16000,))
    assert result["routing_sha256"] == canonical_digest(receipt["routing"])
    assert result["schema_version"] == receipt["schema_version"] == 3
    assert result["request_schema_version"] == 2 and result["routed_cue_count"] == 2
    assert "routing" not in result  # Large details stay in the retained archive.
    return receipt


@pytest.mark.parametrize("stereo", [False, True])
def test_actual_routing_transport_parity(routed_project, stereo):  # noqa: F811
    root, request = routed_project
    if stereo:
        make_stereo(root, request)
    expected = inspect_routed(root, Client().sound_mix_render(request, str(root)), stereo)
    request["output_path"] = "cli.zip"
    path = root / "request.json"
    path.write_text(json.dumps(request))
    run = subprocess.run(
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
    assert run.returncode == 0, run.stderr
    cli = inspect_routed(root, json.loads(run.stdout), stereo)
    request["output_path"] = "mcp.zip"
    mcp = inspect_routed(root, asyncio.run(asyncio.wait_for(_mcp(root, request), 45)), stereo)
    for key in ("media", "routing", "channel_count", "frame_count", "interleaved_sample_count"):
        assert expected[key] == cli[key] == mcp[key]


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
