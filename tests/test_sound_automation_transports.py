"""Actual automated PCM and parent-proof cancellation across public transports."""

import asyncio
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
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project  # noqa: F401
from tests.test_sound_automation_public import automated_project  # noqa: F401
from tests.test_sound_routing_transports import _mcp


def inspect(root, result, stereo):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, rate, channels = decode_pcm_wav(archive.read("master.wav"))
    assert rate == 22050 and channels == (2 if stereo else 1)
    assert list(pcm[:channels]) == ([4000, 2000] if stereo else [4000])
    assert result["automation_sha256"] == canonical_digest(receipt["routing"]["automation"])
    assert result["routing_sha256"] == canonical_digest(receipt["routing"])
    return receipt


@pytest.mark.parametrize("stereo", [False, True])
def test_actual_automation_python_cli_mcp_parity(automated_project, stereo):  # noqa: F811
    root, request = automated_project
    if stereo:
        make_stereo(root, request)
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
    for key in ("routing", "media", "source_windows", "frame_count", "channel_count"):
        assert expected[key] == cli[key] == mcp[key]


def test_parent_automation_read_cancellation_cleans_and_resumes(automated_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_job, mix_automation_receipt

    root, request = automated_project
    original = mix_automation_receipt.verified_automation_windows

    def cancelling_windows(*args):
        for window in original(*args):
            asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
            yield window

    async def scenario():
        monkeypatch.setattr(mix_automation_receipt, "verified_automation_windows", cancelling_windows)
        task = asyncio.create_task(mix_job.render_mix_request_async(request, str(root)))
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 15)
        assert not (root / request["output_path"]).exists()
        assert not list(root.glob(".kinocut-mix-*"))
        monkeypatch.setattr(mix_automation_receipt, "verified_automation_windows", original)
        return await mix_job.render_mix_request_async(request, str(root))

    inspect(root, asyncio.run(asyncio.wait_for(scenario(), 30)), False)
