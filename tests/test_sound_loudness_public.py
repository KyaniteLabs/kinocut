"""Real bytes and persisted requests across Python, CLI and MCP inspection."""

import asyncio
import hashlib
import json
import subprocess
import sys

import pytest

from kinocut import Client
from kinocut_sound._canonical import canonical_digest
from kinocut_sound._errors import SoundContractError
from kinocut_sound.delivery import DeliveryPolicy
from kinocut_sound.public import invoke_sound_operation
from kinocut_sound.public.mix_files import require_safe_filesystem
from tests.test_sound_measured_loudness import calibration_wave  # noqa: F401 - pytest fixture


@pytest.fixture
def meter_project(tmp_path, calibration_wave):  # noqa: F811 - pytest fixture injection
    try:
        require_safe_filesystem()
    except SoundContractError:
        pytest.skip("descriptor-relative source read unavailable")
    (tmp_path / "source.wav").write_bytes(calibration_wave)
    request = {"source": {"path": "source.wav", "sha256": "sha256:" + hashlib.sha256(calibration_wave).hexdigest()}}
    return tmp_path, request


def _inspect(root, result):
    assert result["demo"] is False
    assert result["within_tolerance"] is False
    assert result["integrated_lufs"] == pytest.approx(-23, abs=0.2)
    assert result["true_peak_dbtp"] == pytest.approx(-20, abs=0.1)
    assert result["lra_lu"] == pytest.approx(0, abs=0.2)
    assert result["source_sha256"] == "sha256:" + hashlib.sha256((root / "source.wav").read_bytes()).hexdigest()
    assert result["policy_hash"] == canonical_digest(DeliveryPolicy().model_dump(mode="json"))
    assert result["backend_version"]
    return result


def test_actual_public_loudness_parity(meter_project):
    root, request = meter_project
    expected = _inspect(root, Client().sound_qa_loudness(request=request, project_root=str(root)))
    assert _inspect(root, Client().sound_qa_loudness((root / "source.wav").read_bytes())) == expected
    path = root / "request.json"
    path.write_text(json.dumps(request))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "sound-qa-loudness",
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
    assert _inspect(root, json.loads(result.stdout)) == expected
    assert _inspect(root, asyncio.run(asyncio.wait_for(_mcp(root, request), 45))) == expected


async def _mcp(root, request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        response = await session.call_tool("sound_qa_loudness", {"request": request, "project_root": str(root)})
        assert not response.isError
        payload = response.structuredContent or json.loads(response.content[0].text)
        result = payload.get("result", payload)
        assert result.pop("success", True) is True
        return result


@pytest.mark.parametrize(
    "kwargs", [{"wav_bytes": b""}, {"wav_bytes": None}, {"request": {}}, {"surprise": "SUCCESS"}, {"delivery": False}]
)
def test_explicit_invalid_inputs_cannot_fall_back_to_demo(kwargs):
    with pytest.raises(SoundContractError):
        invoke_sound_operation("sound-qa-loudness", **kwargs)


def test_changed_hash_and_conflicting_modes_fail(meter_project):
    root, request = meter_project
    with pytest.raises(SoundContractError):
        Client().sound_qa_loudness(b"x", request=request, project_root=str(root))
    request["source"]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(SoundContractError):
        Client().sound_qa_loudness(request=request, project_root=str(root))


def test_demo_is_labelled_and_not_automatically_compliant():
    result = Client().sound_qa_loudness()
    assert result["demo"] is True
    assert result["meter"] == "ffmpeg_ebur128_true_peak"
    assert isinstance(result["within_tolerance"], bool)


@pytest.mark.parametrize("root", [None, "", "   "])
def test_shared_request_boundary_requires_explicit_root(meter_project, root):
    from kinocut_sound.public.loudness_request import inspect_loudness, inspect_loudness_async

    _, request = meter_project
    with pytest.raises(SoundContractError):
        inspect_loudness(request=request, project_root=root)
    with pytest.raises(SoundContractError):
        asyncio.run(inspect_loudness_async(request=request, project_root=root))


def test_actual_mcp_rejects_missing_or_empty_root(meter_project):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, request = meter_project

    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            for arguments in ({"request": request}, {"request": request, "project_root": ""}):
                response = await session.call_tool("sound_qa_loudness", arguments)
                payload = response.structuredContent or json.loads(response.content[0].text)
                result = payload.get("result", payload)
                assert response.isError or result.get("success") is False
                assert "TypeError" not in str(result)

    asyncio.run(asyncio.wait_for(scenario(), 10))
