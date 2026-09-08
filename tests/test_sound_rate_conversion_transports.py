"""Actual Python, CLI and MCP V4 output agrees on converted PCM and evidence."""

import asyncio
import json
import subprocess
import sys
import zipfile
import pytest

from kinocut import Client
from kinocut_sound.mix._wav import decode_pcm_wav
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_rate_conversion_public import converted_project  # noqa: F401
from tests.test_sound_routing_transports import _mcp


def _inspect(root, result, channels):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, rate, actual_channels = decode_pcm_wav(archive.read("master.wav"))
        receipt = json.loads(archive.read("receipt.json"))
    assert rate == 32000 and actual_channels == channels and len(pcm) == 19200 * channels
    assert result["converted_source_count"] == 2
    return receipt


@pytest.mark.parametrize("stereo", [False, True])
def test_real_v4_python_cli_mcp_parity(converted_project, stereo):  # noqa: F811
    root, request = converted_project
    if stereo:
        make_stereo(root, request)
    channels = 2 if stereo else 1
    expected = _inspect(root, Client().sound_mix_render(request, str(root)), channels)
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
    cli = _inspect(root, json.loads(run.stdout), channels)
    request["output_path"] = "mcp.zip"
    mcp = _inspect(root, asyncio.run(asyncio.wait_for(_mcp(root, request), 45)), channels)
    for key in ("source_resampling", "sources", "media", "source_windows", "routing"):
        assert expected[key] == cli[key] == mcp[key]
