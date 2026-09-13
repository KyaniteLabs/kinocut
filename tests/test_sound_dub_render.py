"""Real stock speech, public parity, retained-media handoff and hostile failure cases."""

import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import zipfile

import pytest

from kinocut import Client
from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import parse_wav
from kinocut_sound.public import invoke_sound_operation
from kinocut_sound.public.dub_job import render_dub_request, render_dub_request_async
from kinocut_sound.public.mix_files import require_safe_filesystem


@pytest.fixture
def dub_project(tmp_path):
    try:
        require_safe_filesystem()
    except MixError:
        pytest.skip("descriptor-relative publication unavailable")
    raw = b"1\n00:00:00,123 --> 00:00:04,001\nHola mundo\n\n2\n00:00:04,501 --> 00:00:08,001\nGracias\n"
    (tmp_path / "captions.srt").write_bytes(raw)
    request = {
        "source": {"path": "captions.srt", "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()},
        "target_lang": "es",
        "output_path": "speech.zip",
    }
    return tmp_path, request


def _require_engine():
    if shutil.which("espeak-ng") is None:
        pytest.skip("optional real espeak-ng engine unavailable")


def _inspect(root, result):
    assert result["demo"] is False
    path = root / result["output_path"]
    assert result["output_sha256"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        manifest = json.loads(archive.read("mix-request.json"))
        dialogue = archive.read("dialogue.wav")
        for name, proof in receipt["media"].items():
            data = archive.read(name)
            assert proof == {"bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    pcm, rate = parse_wav(dialogue)
    assert len(pcm) == 8001 * rate // 1000
    assert len(set(pcm)) > 100  # Real varying speech waveform, not an empty file.
    assert not any(pcm[: 123 * rate // 1000])
    assert not any(pcm[4001 * rate // 1000 : 4501 * rate // 1000])
    assert receipt["translation_applied"] is False
    assert receipt["mastering_status"] == "not_applied"
    assert not list(root.glob(".kinocut-mix-*"))
    assert str(root) not in json.dumps(receipt)
    assert "Hola mundo" not in json.dumps(receipt)
    return pcm, dialogue, manifest


@pytest.mark.parametrize("language", ["en", "es"])
def test_real_python_cli_mcp_speech_and_public_mix_handoff(dub_project, language):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _require_engine()
    root, request = dub_project
    request["target_lang"] = language
    if language == "en":
        raw = (
            (root / "captions.srt")
            .read_bytes()
            .replace(b"Hola mundo", b"Hello world")
            .replace(b"Gracias", b"Thank you")
        )
        (root / "captions.srt").write_bytes(raw)
        request["source"]["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    expected, dialogue, manifest = _inspect(root, Client().sound_voice_batch(request=request, project_root=str(root)))
    (root / "dialogue.wav").write_bytes(dialogue)
    mixed = Client().sound_mix_render(manifest, str(root))
    with zipfile.ZipFile(root / mixed["output_path"]) as archive:
        assert parse_wav(archive.read("master.wav"))[0] == expected
    request["output_path"] = "cli.zip"
    source = root / "request.json"
    source.write_text(json.dumps(request))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "sound-voice-batch",
            "--request-json",
            str(source),
            "--project-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert _inspect(root, json.loads(result.stdout))[0] == expected
    request["output_path"] = "mcp.zip"

    async def call():
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool("sound_voice_batch", {"request": request, "project_root": str(root)})

    response = asyncio.run(asyncio.wait_for(call(), timeout=30))
    assert not response.isError
    payload = response.structuredContent or json.loads(response.content[0].text)
    assert _inspect(root, payload.get("result", payload))[0] == expected


@pytest.mark.parametrize(
    "arguments",
    [
        {"request": None},
        {"request": {}},
        {"project_root": "."},
        {"request": {}, "project_root": ".", "plan": {}},
        {"ignore": "SUCCESS"},
    ],
)
def test_invalid_real_modes_never_select_synthetic_demo(arguments):
    with pytest.raises(MixError):
        invoke_sound_operation("sound-voice-batch", **arguments)


def test_legacy_batch_is_labelled_and_does_not_claim_retained_speech():
    result = Client().sound_voice_batch()
    assert result["demo"] is True and result["audio_retained"] is False
    assert result["synthesis_kind"] == "deterministic_tone"


def test_absent_engine_fails_before_stage_or_output(dub_project, monkeypatch):
    from kinocut_sound.public import dub_process

    root, request = dub_project
    monkeypatch.setattr(dub_process.shutil, "which", lambda _: None)
    with pytest.raises(MixError) as failure:
        render_dub_request(request, str(root))
    assert failure.value.code == "dub_backend_unavailable"
    assert not (root / "speech.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_hash_change_and_existing_output_preserve_files(dub_project):
    root, request = dub_project
    (root / "captions.srt").write_text("changed")
    with pytest.raises(MixError):
        render_dub_request(request, str(root))
    (root / "speech.zip").write_bytes(b"owner output")
    with pytest.raises(MixError) as failure:
        render_dub_request(request, str(root))
    assert failure.value.code == "mix_output_conflict"
    assert (root / "speech.zip").read_bytes() == b"owner output"


def test_real_speech_overflow_is_not_truncated(dub_project):
    _require_engine()
    root, request = dub_project
    raw = b"1\n00:00:00,000 --> 00:00:00,001\nHola mundo\n"
    (root / "captions.srt").write_bytes(raw)
    request["source"]["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    with pytest.raises(MixError) as failure:
        render_dub_request(request, str(root))
    assert failure.value.code == "dub_slot_overflow"
    assert not (root / "speech.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_real_engine_timeout_cleans_stage(dub_project, monkeypatch):
    from kinocut_sound.public import dub_process

    _require_engine()
    root, request = dub_project
    monkeypatch.setattr(dub_process, "DEFAULT_DUB_UTTERANCE_TIMEOUT_SECONDS", 0.000001)
    with pytest.raises(MixError) as failure:
        render_dub_request(request, str(root))
    assert failure.value.code == "dub_timeout"
    assert not (root / "speech.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_repeated_cancel_during_speech_reaps_then_allows_resume(dub_project, monkeypatch):
    from kinocut_sound.public import dub_process

    _require_engine()
    root, request = dub_project
    original = asyncio.create_subprocess_exec
    workers = []
    release = asyncio.Event()
    reaping = asyncio.Event()

    async def stopped(*args, **kwargs):
        process = await original(*args, **kwargs)
        if "--stdin" in args:
            os.kill(process.pid, signal.SIGSTOP)
            original_wait = process.wait

            async def delayed_wait():
                reaping.set()
                await release.wait()
                return await original_wait()

            process.wait = delayed_wait
            workers.append(process)
        return process

    async def run():
        monkeypatch.setattr(dub_process.asyncio, "create_subprocess_exec", stopped)
        task = asyncio.create_task(render_dub_request_async(request, str(root)))
        while not workers:
            await asyncio.sleep(0.01)
        task.cancel()
        await reaping.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()  # Second cancel cannot unwind before owned reaping.
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert workers[0].returncode is not None
        assert not (root / "speech.zip").exists()
        assert not list(root.glob(".kinocut-mix-*"))
        monkeypatch.setattr(dub_process.asyncio, "create_subprocess_exec", original)
        return await render_dub_request_async(request, str(root))

    _inspect(root, asyncio.run(asyncio.wait_for(run(), timeout=15)))
