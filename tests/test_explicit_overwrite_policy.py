"""Hermes review: consent, file ownership, agent homes and publication races."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _atomic_artifact, _atomic_output, _reset_operation_inputs, _validate_output_path
from kinocut.output_policy import output_operation


@pytest.fixture(autouse=True)
def isolated_operation():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


@pytest.mark.parametrize("suffix", [".mp4", ".png", ".wav", ".json", ".txt", ".ts", ".csv"])
@pytest.mark.parametrize("overwrite", [False, True])
def test_preexisting_targets_require_consent_and_media_suffix(tmp_path, suffix, overwrite):
    target = tmp_path / f"user-file{suffix}"
    target.write_bytes(b"original")
    with output_operation(overwrite):
        if overwrite and suffix in {".mp4", ".png", ".wav"}:
            with _atomic_output(str(target)) as stage:
                Path(stage).write_bytes(b"rendered")
            assert target.read_bytes() == b"rendered"
        else:
            with pytest.raises(MCPVideoError), _atomic_output(str(target)):
                pytest.fail("User target must be rejected before a writer runs")
            assert target.read_bytes() == b"original"


@pytest.mark.parametrize(
    "home", [".hermes", ".claude", ".codex", ".cursor", ".gemini", ".kimi", ".opencode", ".openclaw"]
)
def test_agent_homes_stay_protected_even_with_consent(tmp_path, monkeypatch, home):
    monkeypatch.setenv("HOME", str(tmp_path))
    with output_operation(True), pytest.raises(MCPVideoError, match="sensitive home"):
        _validate_output_path(str(tmp_path / home / "sessions" / "token.json"))


def test_owned_nonmedia_requires_consent_and_cannot_cross_jobs(tmp_path):
    target = tmp_path / "receipt.json"
    with output_operation():
        with _atomic_artifact(str(target)) as stage:
            Path(stage).write_text("first")
        with pytest.raises(MCPVideoError, match="overwrite=true"), _atomic_artifact(str(target)):
            pytest.fail("Repeated final writes require consent")
        with output_operation(True), _atomic_artifact(str(target)) as stage:
            Path(stage).write_text("updated")
    with output_operation(True), pytest.raises(MCPVideoError), _atomic_artifact(str(target)):
        pytest.fail("A previous job's receipt is protected")
    assert target.read_text() == "updated"


def test_replaced_nonmedia_inode_is_not_owned(tmp_path):
    target = tmp_path / "receipt.json"
    with output_operation(True):
        with _atomic_artifact(str(target)) as stage:
            Path(stage).write_text("owned")
        replacement = tmp_path / "foreign.json"
        replacement.write_text("foreign")
        os.replace(replacement, target)
        with pytest.raises(MCPVideoError), _atomic_artifact(str(target)):
            pytest.fail("An owned filename must not authorize a replacement inode")
    assert target.read_text() == "foreign"


def test_target_created_during_publication_survives(tmp_path, monkeypatch):
    target = tmp_path / "render.mp4"
    link = os.link

    def racing_link(src, dst, **kwargs):
        target.write_bytes(b"racing-user-file")
        return link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    with output_operation(), pytest.raises(MCPVideoError), _atomic_output(str(target)) as stage:
        Path(stage).write_bytes(b"rendered")
    assert target.read_bytes() == b"racing-user-file"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_policy_wrapped_mcp_tool_retains_request_context():
    from typing import get_type_hints

    from mcp.server.fastmcp.utilities.context_injection import find_context_parameter

    from kinocut.server import mcp

    tool = mcp._tool_manager.get_tool("video_convert")
    assert "ctx" in get_type_hints(tool.fn)
    assert find_context_parameter(tool.fn) == "ctx"
    assert tool.context_kwarg == "ctx"
    assert "ctx" not in tool.parameters["properties"]


def test_mcp_schema_accepts_only_explicit_boolean_and_scopes_consent(sample_video, tmp_path):
    from kinocut.server import mcp

    async def exercise():
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        field = tools["video_trim"].inputSchema["properties"]["overwrite"]
        assert field["type"] == "boolean" and field["default"] is False
        target = tmp_path / "clip.mp4"
        target.write_bytes(b"original")
        args = {"input_path": sample_video, "start": "0", "duration": "0.2", "output_path": str(target)}
        for value in [None, "true", 1]:
            invalid = await mcp.call_tool("video_trim", {**args, "overwrite": value})
            assert invalid.isError
            assert target.read_bytes() == b"original"
        rejected = await mcp.call_tool("video_trim", args)
        assert "output_exists" in str(rejected)
        accepted = await mcp.call_tool("video_trim", {**args, "overwrite": True})
        assert "output_exists" not in str(accepted)
        assert target.stat().st_size > len(b"original")
        before = target.read_bytes()
        rejected = await mcp.call_tool("video_trim", args)
        assert "output_exists" in str(rejected)
        assert target.read_bytes() == before

    asyncio.run(exercise())


def test_client_requires_consent_without_leaking_it(sample_video, tmp_path):
    from kinocut import Client

    target = tmp_path / "client.mp4"
    target.write_bytes(b"original")
    client = Client()
    args = {"start": "0", "duration": "0.2", "output_path": str(target)}
    with pytest.raises(MCPVideoError, match="overwrite=true"):
        client.trim(sample_video, **args)
    client.trim(sample_video, **args, overwrite=True)
    rendered = target.read_bytes()
    assert rendered != b"original"
    with pytest.raises(MCPVideoError, match="overwrite=true"):
        client.trim(sample_video, **args)
    assert target.read_bytes() == rendered
    with pytest.raises(MCPVideoError, match="aliases an input"):
        client.trim(sample_video, start="0", duration="0.2", output_path=sample_video, overwrite=True)


def test_cli_requires_explicit_overwrite_flag(sample_video, tmp_path):
    target = tmp_path / "cli.mp4"
    target.write_bytes(b"original")
    args = ["trim", sample_video, "--start", "0", "--duration", "0.2", "--output", str(target)]
    refused = subprocess.run([sys.executable, "-m", "kinocut", *args], capture_output=True, timeout=30)
    assert refused.returncode != 0
    assert target.read_bytes() == b"original"
    accepted = subprocess.run([sys.executable, "-m", "kinocut", "--overwrite", *args], capture_output=True, timeout=30)
    assert accepted.returncode == 0, accepted.stderr.decode()
    assert target.stat().st_size > len(b"original")


def test_parallel_batch_inherits_explicit_consent(sample_video, sample_video_2, tmp_path):
    from kinocut.server import video_batch

    output_dir = tmp_path / "batch"
    inputs = [sample_video, sample_video_2]
    args = {"operation": "trim", "params": {"start": "0", "duration": "0.2"}, "output_dir": str(output_dir)}
    first = video_batch(inputs, **args)
    assert first["success"], first
    denied = video_batch(inputs, **args)
    assert denied["failed"] == 2
    permitted = video_batch(inputs, **args, overwrite=True)
    assert permitted["success"], permitted


def test_read_only_tools_offer_no_overwrite_consent():
    from kinocut.server import mcp
    from kinocut.tool_registry import configure_tool_surface

    async def schemas():
        return {tool.name: tool for tool in await mcp.list_tools()}

    configure_tool_surface()
    try:
        tools = asyncio.run(schemas())
    finally:
        configure_tool_surface("all")
    read_only = {"video_info", "video_doctor", "list_operations", "describe_operation"}
    for name in read_only:
        assert "overwrite" not in tools[name].inputSchema.get("properties", {}), name
    for name, tool in tools.items():
        if tool.annotations is not None and tool.annotations.readOnlyHint:
            assert "overwrite" not in tool.inputSchema.get("properties", {}), name
    assert "overwrite" in tools["video_trim"].inputSchema["properties"]


def test_read_only_hint_rejects_overwrite_consent():
    from mcp.types import ToolAnnotations

    from kinocut.server_tool_contracts import _ContractFastMCP

    def lookup(path: str) -> dict:
        return {"path": path}

    with pytest.raises(MCPVideoError):
        _ContractFastMCP("probe").add_tool(lookup, annotations=ToolAnnotations(readOnlyHint=True))
