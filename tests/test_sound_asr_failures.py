"""Hostile recognition output and precommit cancellation cannot publish evidence."""

import asyncio
import hashlib
import json
from pathlib import Path
import sys

import pytest

from kinocut_sound.mix._wav import synthesize_tone
from kinocut_sound.public import asr_job
from kinocut_sound.public.asr_request import AsrError
from kinocut_sound._errors import SoundContractError


@pytest.fixture
def fake_asr(tmp_path, monkeypatch):
    audio = synthesize_tone(duration_seconds=3, sample_rate_hz=16000)
    (tmp_path / "source.wav").write_bytes(audio)
    (tmp_path / "reference.txt").write_text("hello")

    def asset(name):
        return {"path": name, "sha256": "sha256:" + hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()}

    request = {
        "schema_version": 1,
        "source": asset("source.wav"),
        "reference": asset("reference.txt"),
        "language": "en",
        "model": "base.en",
        "output_path": "output.zip",
    }
    monkeypatch.setattr(asr_job, "interpreters", lambda: [sys.executable])
    monkeypatch.setattr(asr_job, "copy_checkpoint", lambda *args: 1)
    payload = {"text": "hello", "segments": [{"start": 0, "end": 2, "text": "hello"}]}

    def backend(args, timeout):
        if args[-1] == "probe":
            return json.dumps(
                {"available": True, "version": "test", "models": {"base": "0" * 64, "base.en": "0" * 64}}
            ).encode()
        output = Path(args[-2]).parent / "recognition.json"
        output.write_text(json.dumps(payload))
        return b'{"recognized":true}'

    monkeypatch.setattr(asr_job, "run_meter_sync", backend)

    async def backend_async(args, timeout):
        return backend(args, timeout)

    monkeypatch.setattr(asr_job, "run_meter_async", backend_async)
    return tmp_path, request, payload, backend


@pytest.mark.parametrize("kind", ["huge_integer", "nan", "contradiction", "overlap", "words"])
def test_hostile_output_fails_without_publication(fake_asr, kind):
    root, request, payload, _ = fake_asr
    if kind == "huge_integer":
        payload["segments"][0]["end"] = 10**400
    elif kind == "nan":
        payload["segments"][0]["end"] = float("nan")
    elif kind == "contradiction":
        payload["text"] = "different"
    elif kind == "overlap":
        payload["segments"].append({"start": 1, "end": 2, "text": "hello"})
    else:
        payload["text"] = "x " * 2049
    with pytest.raises(AsrError):
        asr_job.recognize_sync(request, str(root))
    assert not (root / "output.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


@pytest.mark.parametrize("kind", ["nested", "symlink", "fifo", "oversized"])
def test_backend_file_guards(fake_asr, monkeypatch, kind):
    root, request, _, original = fake_asr

    def backend(args, timeout):
        if args[-1] == "probe":
            return original(args, timeout)
        path = Path(args[-2]).parent / "recognition.json"
        if kind == "nested":
            path.write_text("[" * 2000 + "]" * 2000)
        elif kind == "symlink":
            path.symlink_to(root / "reference.txt")
        elif kind == "fifo":
            import os

            os.mkfifo(path)
        else:
            path.write_bytes(b"x" * 1048577)
        return b'{"recognized":true}'

    monkeypatch.setattr(asr_job, "run_meter_sync", backend)
    with pytest.raises(SoundContractError):
        asr_job.recognize_sync(request, str(root))
    assert not (root / "output.zip").exists()


def test_cancellation_queued_during_comparison_prevents_commit(fake_asr, monkeypatch):
    root, request, _, _ = fake_asr
    original = asr_job.compare

    def compare(*args):
        asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
        return original(*args)

    monkeypatch.setattr(asr_job, "compare", compare)

    async def exercise():
        with pytest.raises(asyncio.CancelledError):
            await asr_job.recognize_async(request, str(root))

    asyncio.run(exercise())
    assert not (root / "output.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))
