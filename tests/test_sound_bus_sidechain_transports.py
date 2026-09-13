"""Real bus-sidechain media and recovery evidence across transports."""

from array import array
import asyncio
import hashlib
import json
import subprocess
import sys
import zipfile
import pytest

from kinocut import Client
from kinocut_sound._canonical import canonical_digest
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_bus_sidechains_public import sidechain_project  # noqa: F401
from tests.test_sound_routing_transports import _mcp


def inspect(root, result, stereo):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, rate, channels = decode_pcm_wav(archive.read("stems/ambience.wav"))
    assert rate == 22050 and channels == (2 if stereo else 1)
    assert list(pcm[:channels]) == ([9996, -4998] if stereo else [9996])
    assert result["sidechains_sha256"] == canonical_digest(receipt["routing"]["sidechains"])
    assert result["sidechain_measurements_sha256"] == canonical_digest(
        {"measurements": receipt["bus_sidechain_measurements"]}
    )
    return receipt


@pytest.mark.parametrize("stereo", [False, True])
def test_actual_sidechain_python_cli_mcp_parity(sidechain_project, stereo):  # noqa: F811
    root, request = sidechain_project
    if stereo:
        make_stereo(root, request)
        data = pcm_to_wav(array("h", [10000, -5000] * 13230), sample_rate_hz=22050, channel_count=2)
        (root / "bed.wav").write_bytes(data)
        request["bed"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    expected = inspect(root, Client().sound_mix_render(request, str(root)), stereo)
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
    cli = inspect(root, json.loads(run.stdout), stereo)
    request["output_path"] = "mcp.zip"
    mcp = inspect(root, asyncio.run(asyncio.wait_for(_mcp(root, request), 45)), stereo)
    for key in ("routing", "media", "bus_sidechain_measurements", "frame_count", "channel_count"):
        assert expected[key] == cli[key] == mcp[key]
