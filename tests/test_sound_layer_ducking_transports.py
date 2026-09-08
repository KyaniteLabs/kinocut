"""Ducked PCM, recovery summaries and cancellation through real public paths."""

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
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project  # noqa: F401
from tests.test_sound_routing_transports import _mcp


def inspect(root, result, stereo):
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, rate, channels = decode_pcm_wav(archive.read("stems/ambience.wav"))
    assert rate == 22050 and channels == (2 if stereo else 1)
    assert list(pcm[:channels]) == ([9996, -4998] if stereo else [9996])
    assert result["layer_ducking_sha256"] == canonical_digest(receipt["layers"]["ducking"])
    assert result["layers_sha256"] == canonical_digest(receipt["layers"])
    assert receipt["layers"]["ducking"]["summary"]["recovery_status"] == "pass"
    return receipt


@pytest.mark.parametrize("stereo", [False, True])
def test_actual_ducking_python_cli_mcp_parity(ducked_project, stereo):  # noqa: F811
    root, request = ducked_project
    if stereo:
        make_stereo(root, request)
        data = pcm_to_wav(array("h", [10000, -5000] * 13230), sample_rate_hz=22050, channel_count=2)
        (root / "layer.wav").write_bytes(data)
        request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
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
    for key in ("layers", "routing", "media", "frame_count", "channel_count"):
        assert expected[key] == cli[key] == mcp[key]


def test_ducked_parent_cancellation_cleans_and_resumes(ducked_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_job, mix_layer_receipt

    root, request = ducked_project
    original = mix_layer_receipt.verified_layer_shapes

    def cancelling_shapes(*args):
        for shape in original(*args):
            asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
            yield shape

    async def scenario():
        monkeypatch.setattr(mix_layer_receipt, "verified_layer_shapes", cancelling_shapes)
        task = asyncio.create_task(mix_job.render_mix_request_async(request, str(root)))
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 15)
        assert not (root / request["output_path"]).exists()
        assert not list(root.glob(".kinocut-mix-*"))
        monkeypatch.setattr(mix_layer_receipt, "verified_layer_shapes", original)
        return await mix_job.render_mix_request_async(request, str(root))

    inspect(root, asyncio.run(asyncio.wait_for(scenario(), 30)), False)
