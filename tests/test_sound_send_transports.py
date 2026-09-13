"""Actual send output and exclusive publication across Python, CLI and MCP."""

import asyncio
import json
import subprocess
import sys
import zipfile

import pytest

from kinocut import Client
from kinocut_sound._canonical import canonical_digest
from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import decode_pcm_wav
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_sends_public import sent_project  # noqa: F401
from tests.test_sound_routing_transports import _mcp


def inspect(root, result, stereo):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, rate, channels = decode_pcm_wav(archive.read("stems/ambience.wav"))
    assert rate == 22050 and channels == (2 if stereo else 1)
    assert list(pcm[:channels]) == ([4000, 2000] if stereo else [8000])
    assert result["sends_sha256"] == canonical_digest(receipt["routing"]["sends"])
    assert result["send_count"] == 1
    return receipt


@pytest.mark.parametrize("stereo", [False, True])
def test_actual_send_python_cli_mcp_parity(sent_project, stereo):  # noqa: F811
    root, request = sent_project
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
    for key in ("routing", "media", "frame_count", "channel_count"):
        assert expected[key] == cli[key] == mcp[key]
    before = (root / request["output_path"]).read_bytes()
    with pytest.raises(MixError) as failure:
        Client().sound_mix_render(request, str(root))
    assert failure.value.code == "mix_output_conflict"
    assert (root / request["output_path"]).read_bytes() == before


def test_send_worker_cancellation_reaps_and_resumes(sent_project, monkeypatch):  # noqa: F811
    import os
    import signal
    from kinocut_sound.public import mix_job

    root, request = sent_project
    original = asyncio.create_subprocess_exec
    workers = []

    async def stopped(*args, **kwargs):
        process = await original(*args, **kwargs)
        os.kill(process.pid, signal.SIGSTOP)
        workers.append(process)
        return process

    async def scenario():
        monkeypatch.setattr(mix_job.asyncio, "create_subprocess_exec", stopped)
        task = asyncio.create_task(mix_job.render_mix_request_async(request, str(root)))
        for _ in range(100):
            if workers:
                break
            await asyncio.sleep(0.01)
        assert workers
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert workers[0].returncode is not None
        assert not (root / request["output_path"]).exists()
        assert not list(root.glob(".kinocut-mix-*"))
        monkeypatch.setattr(mix_job.asyncio, "create_subprocess_exec", original)
        return await mix_job.render_mix_request_async(request, str(root))

    inspect(root, asyncio.run(asyncio.wait_for(scenario(), 20)), False)
