"""Source windows and combined ambience through actual public transports."""

from array import array
import asyncio
import hashlib
import json
import subprocess
import sys
import zipfile

from kinocut import Client
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav
from tests.test_sound_public_mix import mix_project  # noqa: F401 - shared real fixture


def _inspect(root, result):
    path = root / result["output_path"]
    assert result["output_sha256"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, rate = parse_wav(archive.read("master.wav"))
        for name, metadata in receipt["media"].items():
            data = archive.read(name)
            assert metadata["sha256"] == "sha256:" + hashlib.sha256(data).hexdigest()
    assert pcm[0] == 310
    assert pcm[2204] == 2514
    assert pcm[2205] == 100  # Selected source exhausted; only bed remains.
    assert pcm[4410] == -5900  # Ambience clip plus bed, never overwritten.
    assert not any(pcm[8820:])
    assert rate == 22050
    assert receipt["source_windows"][0] == {
        "cue_id": "a",
        "in_sample": 220,
        "out_sample": 2425,
        "sample_count": 2205,
        "sample_rate_hz": rate,
    }
    return pcm


def test_real_public_trim_and_additive_bed_parity(mix_project):  # noqa: F811 - pytest injects imported fixture
    root, request = mix_project
    data = pcm_to_wav(array("h", range(-10, 6605)), sample_rate_hz=22050)
    (root / "a.wav").write_bytes(data)
    request["clips"][0]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    request["clips"][0]["stem_id"] = "ambience"
    request["clips"][1]["stem_id"] = "ambience"
    cue = request["plan"]["timeline"]["cues"][0]
    cue.update(in_point_seconds=220 / 22050, out_point_seconds=2425 / 22050)
    request["transitions"] = []
    bed = pcm_to_wav(array("h", [100] * 8820), sample_rate_hz=22050)
    (root / "bed.wav").write_bytes(bed)
    request["bed"] = {"path": "bed.wav", "sha256": "sha256:" + hashlib.sha256(bed).hexdigest()}
    request["plan"]["beds"] = ["bed.wav"]
    request["duck_bed"] = True
    expected = _inspect(root, Client().sound_mix_render(request, str(root)))
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
            "sound-mix-render",
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
    assert _inspect(root, json.loads(completed.stdout)) == expected
    request["output_path"] = "mcp.zip"
    result = asyncio.run(asyncio.wait_for(_mcp(root, request), timeout=45))
    assert _inspect(root, result) == expected


async def _mcp(root, request):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        response = await session.call_tool("sound_mix_render", {"request": request, "project_root": str(root)})
        assert not response.isError
        payload = response.structuredContent or json.loads(response.content[0].text)
        return payload.get("result", payload)
