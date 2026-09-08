"""Stereo masters and actual source measurement across public transports."""

import asyncio
import json
import subprocess
import sys

from kinocut import Client
from tests.test_sound_master_public import master_project, inspect_master  # noqa: F401
from tests.test_sound_stereo_mastering import stereo_master_project  # noqa: F401


def test_actual_stereo_master_transport_parity(stereo_master_project):  # noqa: F811
    root, request = stereo_master_project
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
    for key in (
        "schema_version",
        "channel_count",
        "frame_count",
        "interleaved_sample_count",
        "input_frame_count",
        "input_interleaved_sample_count",
    ):
        assert expected[key] == cli[key] == mcp[key]


async def _mcp(root, request, tool="sound_master_render"):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        response = await session.call_tool(tool, {"request": request, "project_root": str(root)})
        assert not response.isError
        payload = response.structuredContent or json.loads(response.content[0].text)
        result = payload.get("result", payload)
        assert result.pop("success", True) is True
        return result


def test_actual_stereo_meter_transport_parity(stereo_master_project):  # noqa: F811
    root, master_request = stereo_master_project
    request = {"source": master_request["source"]}
    expected = Client().sound_qa_loudness(request=request, project_root=str(root))
    path = root / "meter-request.json"
    path.write_text(json.dumps(request))
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "sound",
            "qa-loudness",
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
    cli = json.loads(run.stdout)
    mcp = asyncio.run(asyncio.wait_for(_mcp(root, request, "sound_qa_loudness"), 45))
    for key in (
        "schema_version",
        "channel_count",
        "frame_count",
        "interleaved_sample_count",
        "source_sha256",
        "integrated_lufs",
        "true_peak_dbtp",
        "within_tolerance",
        "sample_rate_hz",
    ):
        assert expected[key] == cli[key] == mcp[key]
