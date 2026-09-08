"""Real spatial speech is equivalent through Python, CLI and MCP, then mixing."""

import asyncio
import hashlib
import json
import subprocess
import sys
import zipfile
import pytest

from kinocut import Client
from kinocut_sound.mix._wav import parse_wav
from tests.test_sound_dub_render import dub_project, _require_engine, _inspect  # noqa: F401
from tests.test_sound_speech_spatial_public import spatial_project  # noqa: F401


def _evidence(root, result):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        return json.loads(archive.read("receipt.json"))["spatial"]


async def _mcp(root, request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        response = await session.call_tool("sound_voice_batch", {"request": request, "project_root": str(root)})
    assert not response.isError
    value = response.structuredContent or json.loads(response.content[0].text)
    return value.get("result", value)


@pytest.mark.parametrize("language", ["en", "es"])
def test_real_spatial_speech_transport_and_mix_handoff(spatial_project, language):  # noqa: F811
    _require_engine()
    root, request = spatial_project
    request["target_lang"] = language
    if language == "en":
        data = (
            (root / "captions.srt")
            .read_bytes()
            .replace(b"Hola mundo", b"Hello world")
            .replace(b"Gracias", b"Thank you")
        )
        (root / "captions.srt").write_bytes(data)
        request["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    result = Client().sound_voice_batch(request=request, project_root=str(root))
    expected, dialogue, manifest = _inspect(root, result)
    evidence = _evidence(root, result)
    (root / "dialogue.wav").write_bytes(dialogue)
    mixed = Client().sound_mix_render(manifest, str(root))
    with zipfile.ZipFile(root / mixed["output_path"]) as archive:
        assert parse_wav(archive.read("master.wav"))[0] == expected
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
            "sound-voice-batch",
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
    assert _inspect(root, cli)[0] == expected and _evidence(root, cli) == evidence
    request["output_path"] = "mcp.zip"
    mcp = asyncio.run(asyncio.wait_for(_mcp(root, request), 45))
    assert _inspect(root, mcp)[0] == expected and _evidence(root, mcp) == evidence
