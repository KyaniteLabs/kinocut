"""Injected hostile backend outputs are failures even when the process claims success."""

from array import array
from pathlib import Path
from types import SimpleNamespace
import time
import os

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.public import dub_job, dub_process
from tests.test_sound_dub_render import dub_project as dub_project


def _fake_engine(monkeypatch, output):
    generated = []
    monkeypatch.setattr(dub_job, "resolve_engine", lambda: "/test-owned/engine")

    def run(args, _text, _deadline):
        if "--version" in args:
            return b"eSpeak NG text-to-speech: 1.2.3 Data at: /private/engine-data"
        path = Path(args[-1])
        generated.append(path)
        if callable(output):
            output(path)
        else:
            path.write_bytes(output)
        return b"SUCCESS"

    monkeypatch.setattr(dub_job, "run_sync", run)
    return generated


@pytest.mark.parametrize(
    "output",
    [
        b"SUCCESS",
        pcm_to_wav(array("h", [0] * 100), sample_rate_hz=22050),
        pcm_to_wav(array("h", [100] * 100), sample_rate_hz=16000),
    ],
)
def test_success_text_cannot_substitute_for_valid_speech(dub_project, monkeypatch, output):
    root, request = dub_project
    generated = _fake_engine(monkeypatch, output)
    with pytest.raises(MixError):
        dub_job.render_dub_request(request, str(root))
    assert not (root / "speech.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))
    assert all(not path.parent.exists() for path in generated)


def test_generated_size_is_checked_before_read(dub_project, monkeypatch):
    root, request = dub_project
    _fake_engine(monkeypatch, b"x" * 100)
    monkeypatch.setattr(dub_job, "MAX_DUB_WAV_BYTES", 50)

    def forbidden_read(_path):
        pytest.fail("oversized generated media was read before its byte ceiling")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    with pytest.raises(MixError) as failure:
        dub_job.render_dub_request(request, str(root))
    assert failure.value.code == "mix_over_limit"
    assert not (root / "speech.zip").exists()


def test_cumulative_wav_limit_is_enforced_between_cues(dub_project, monkeypatch):
    root, request = dub_project
    generated = _fake_engine(monkeypatch, pcm_to_wav(array("h", [100] * 600), sample_rate_hz=22050))
    monkeypatch.setattr(dub_job, "MAX_DUB_WAV_BYTES", 2000)
    with pytest.raises(MixError) as failure:
        dub_job.render_dub_request(request, str(root))
    assert failure.value.code == "mix_over_limit"
    assert len(generated) == 2
    assert not (root / "speech.zip").exists()


def test_memory_limit_precedes_backend_execution(dub_project, monkeypatch):
    root, request = dub_project
    monkeypatch.setattr(dub_job, "MAX_DUB_MEMORY_BYTES", 1)
    monkeypatch.setattr(dub_job, "resolve_engine", lambda: pytest.fail("memory rejection came too late"))
    with pytest.raises(MixError) as failure:
        dub_job.render_dub_request(request, str(root))
    assert failure.value.code == "mix_over_limit"


def test_nonzero_exit_and_invalid_engine_identity_fail(monkeypatch):
    monkeypatch.setattr(
        dub_process.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=b"SUCCESS", stderr=b"")
    )
    with pytest.raises(MixError) as failure:
        dub_process.run_sync(["fixture"], b"", time.monotonic() + 5)
    assert failure.value.code == "dub_backend_failed"
    with pytest.raises(MixError):
        dub_process.engine_version(b"SUCCESS /private/engine-path")


def test_overall_deadline_includes_publication_preparation(dub_project, monkeypatch):
    from kinocut_sound.public import dub_bundle

    root, request = dub_project
    _fake_engine(monkeypatch, pcm_to_wav(array("h", [100] * 100), sample_rate_hz=22050))
    original = dub_bundle.mix_manifest

    def slow_preparation(*args, **kwargs):
        manifest = original(*args, **kwargs)
        monkeypatch.setattr(dub_process.time, "monotonic", lambda: float("inf"))
        return manifest

    monkeypatch.setattr(dub_bundle, "mix_manifest", slow_preparation)
    with pytest.raises(MixError) as failure:
        dub_job.render_dub_request(request, str(root))
    assert failure.value.code == "dub_timeout"
    assert not (root / "speech.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_faulty_backend_special_file_cannot_block_or_escape(dub_project, monkeypatch, kind):
    root, request = dub_project
    owner = root / "owner.wav"
    owner.write_bytes(b"preserve owner")
    _fake_engine(monkeypatch, lambda path: os.mkfifo(path) if kind == "fifo" else path.symlink_to(owner))
    with pytest.raises(MixError):
        dub_job.render_dub_request(request, str(root))
    assert owner.read_bytes() == b"preserve owner"
    assert not (root / "speech.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_growing_file_metadata_is_rejected(dub_project, monkeypatch):
    from kinocut_sound.public import mix_files

    root, _ = dub_project
    original = os.fstat
    calls = 0

    def changed(fd):
        nonlocal calls
        info = original(fd)
        calls += 1
        if calls == 2:
            fields = {
                name: getattr(info, name) for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            }
            fields["st_size"] += 1
            return SimpleNamespace(**fields)
        return info

    with mix_files.open_root(str(root)) as fd:
        monkeypatch.setattr(mix_files.os, "fstat", changed)
        with pytest.raises(MixError):
            mix_files._read_regular_file(fd, "captions.srt", 1000)


def test_diagnostics_are_read_with_a_byte_ceiling():
    class OversizedDiagnostic:
        def seek(self, offset):
            assert offset == 0

        def read(self, limit):
            assert limit == dub_process.MAX_MIX_WORKER_MESSAGE_BYTES + 1
            return b"x" * limit

    with pytest.raises(MixError):
        dub_process._read_diagnostics(0, OversizedDiagnostic(), OversizedDiagnostic())


def test_exit_race_still_reaps():
    import asyncio

    class Exited:
        returncode = None
        waited = False

        def kill(self):
            raise ProcessLookupError

        async def wait(self):
            self.waited = True
            self.returncode = 0
            return 0

    process = Exited()
    assert asyncio.run(dub_process._reap(process)) is False
    assert process.waited
