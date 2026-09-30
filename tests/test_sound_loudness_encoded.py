"""Encoded sources bind original bytes and genuine EBU R128 policy verdicts."""

import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from kinocut import Client
from kinocut.ffmpeg_helpers import _run_ffmpeg
from kinocut.sound_joins.loudness import inspect_loudness_async
from kinocut_sound._errors import SoundContractError
from tests.test_sound_loudness_public import _mcp


def _source(root, suffix, *, amplitude=0.1):
    path = root / f"source.{suffix}"
    args = ["-f", "lavfi", "-i", f"aevalsrc={amplitude}*sin(2*PI*997*t):s=48000:d=4", "-ac", "2"]
    if suffix == "mp4":
        args = ["-f", "lavfi", "-i", "color=c=black:s=32x32:r=5:d=4", *args, "-c:v", "libx264", "-c:a", "aac"]
    _run_ffmpeg([*args, str(path)])
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return path, {"source": {"path": path.name, "sha256": digest}}


@pytest.mark.parametrize("suffix", ["m4a", "mp3", "mp4"])
def test_encoded_public_parity_and_measured_policy(tmp_path, suffix):
    path, request = _source(tmp_path, suffix)
    expected = Client().sound_qa_loudness(request=request, project_root=str(tmp_path))
    assert expected["source_sha256"] == request["source"]["sha256"]
    assert expected["demo"] is False and expected["within_tolerance"] is False
    assert expected["channel_count"] == 2 and expected["audio_codec"]
    assert expected["meter"] == "ffmpeg_ebur128_true_peak" and expected["backend_version"]
    assert str(tmp_path) not in json.dumps(expected)
    assert expected == asyncio.run(inspect_loudness_async(request=request, project_root=str(tmp_path)))
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "sound-qa-loudness",
            "--request-json",
            str(request_path),
            "--project-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == expected
    assert asyncio.run(asyncio.wait_for(_mcp(tmp_path, request), 45)) == expected
    request["delivery"] = {
        "loudness": {"integrated_lufs": expected["integrated_lufs"], "tolerance_lu": 0.2, "true_peak_dbtp": -1}
    }
    assert Client().sound_qa_loudness(request=request, project_root=str(tmp_path))["within_tolerance"] is True
    request["delivery"]["true_peak_ceiling_dbtp"] = -30
    assert Client().sound_qa_loudness(request=request, project_root=str(tmp_path))["within_tolerance"] is False
    path.write_bytes(b"changed")
    with pytest.raises(SoundContractError):
        Client().sound_qa_loudness(request=request, project_root=str(tmp_path))


@pytest.mark.parametrize("content", [b"not media", b"#EXTM3U\nhttp://example.com/private\n"])
def test_invalid_encoded_media_never_certified(tmp_path, content):
    source = tmp_path / "bad.mp3"
    source.write_bytes(content)
    request = {"source": {"path": source.name, "sha256": "sha256:" + hashlib.sha256(content).hexdigest()}}
    with pytest.raises(SoundContractError) as error:
        Client().sound_qa_loudness(request=request, project_root=str(tmp_path))
    assert str(tmp_path) not in str(error.value)


def test_silent_encoded_audio_cannot_pass(tmp_path):
    _, request = _source(tmp_path, "m4a", amplitude=0)
    with pytest.raises(SoundContractError):
        Client().sound_qa_loudness(request=request, project_root=str(tmp_path))


def test_audio_absent_film_cannot_certify(tmp_path):
    source = tmp_path / "silent-film.mp4"
    _run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=32x32:r=5:d=4", "-an", str(source)])
    data = source.read_bytes()
    request = {"source": {"path": source.name, "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}}
    with pytest.raises(SoundContractError):
        Client().sound_qa_loudness(request=request, project_root=str(tmp_path))


def test_cancel_encoded_probe_owns_workspace_and_child(tmp_path, monkeypatch):
    from kinocut.sound_joins import loudness

    _, request = _source(tmp_path, "m4a")
    entered = asyncio.Event()
    folder = []

    async def wait_probe(args, _timeout):
        folder.append(str(Path(args[-1]).parent))
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(loudness, "run_meter_async", wait_probe)

    async def cancel():
        task = asyncio.create_task(inspect_loudness_async(request=request, project_root=str(tmp_path)))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not Path(folder[0]).exists()

    asyncio.run(cancel())
