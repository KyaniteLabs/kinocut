"""Preprocessing shares the deadline, cancellation and exclusive receipt seam."""

import asyncio
import hashlib
from pathlib import Path
import sys

import pytest

from kinocut_sound.mix._wav import synthesize_tone
from kinocut_sound.public import asr_job, asr_resample
from kinocut_sound._errors import SoundContractError
from kinocut_sound.qa.meter_process import run_meter_sync, run_meter_async
from tests.test_sound_asr_failures import fake_asr  # noqa: F401
from tests.test_sound_asr_cancellation import child_args, assert_gone


@pytest.fixture
def resampled_asr(fake_asr):  # noqa: F811
    root, request, payload, original = fake_asr
    audio = synthesize_tone(duration_seconds=3, sample_rate_hz=24000)
    (root / "source.wav").write_bytes(audio)
    request["source"]["sha256"] = "sha256:" + hashlib.sha256(audio).hexdigest()
    return root, request, payload, original


def test_actual_preprocessing_recorded_in_receipt_with_private_source_excluded(resampled_asr, monkeypatch):
    root, request, _, original = resampled_asr
    calls = []

    def backend(args, timeout):
        calls.append(args)
        if args[-1] in {"probe", "recognize"}:
            return original(args, timeout)
        return run_meter_sync(args, timeout)

    monkeypatch.setattr(asr_job, "run_meter_sync", backend)
    result = asr_job.recognize_sync(request, str(root))
    assert result["backend"]["resampling"].startswith(asr_resample.RESAMPLING_ID + ";ffmpeg=")
    assert len(calls) == 4  # probe, resampler version, preprocessing, recognition
    assert str(root) not in str(result)
    assert result["human_review_required"]
    assert (root / "output.zip").is_file()


@pytest.mark.parametrize("kind", ["short", "oversized", "missing", "nonzero"])
def test_invalid_preprocessor_output_never_publishes(resampled_asr, monkeypatch, kind):
    root, request, _, original = resampled_asr
    recognized = False

    def backend(args, timeout):
        nonlocal recognized
        if args[-1] == "probe":
            return original(args, timeout)
        if args[-1] == "-version":
            return b"ffmpeg version test\n"
        if args[-1] == "recognize":
            recognized = True
            return original(args, timeout)
        if kind == "nonzero":
            return run_meter_sync([sys.executable, "-c", "raise SystemExit(7)"], timeout)
        output = Path(args[-1])
        if kind != "missing":
            output.write_bytes(bytes(3 * 16000 * 4 + (1 if kind == "oversized" else -1)))
        return b""

    monkeypatch.setattr(asr_job, "run_meter_sync", backend)
    with pytest.raises(SoundContractError):
        asr_job.recognize_sync(request, str(root))
    assert not recognized
    assert not (root / "output.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_preprocessing_timeout_reaps_child_and_cleans_workspace(resampled_asr, monkeypatch):
    root, request, _, original = resampled_asr
    pid, workspaces = root / "child.pid", []
    monkeypatch.setattr(asr_job, "DEFAULT_ASR_TOTAL_TIMEOUT_SECONDS", 0.3)

    def backend(args, timeout):
        if args[-1] == "probe":
            return original(args, timeout)
        if args[-1] == "-version":
            return b"ffmpeg version test\n"
        workspaces.append(Path(args[-1]).parent)
        return run_meter_sync(child_args(pid), timeout)

    monkeypatch.setattr(asr_job, "run_meter_sync", backend)
    with pytest.raises(SoundContractError):
        asr_job.recognize_sync(request, str(root))
    assert_gone(root, pid, workspaces)


def test_preprocessing_repeated_cancellation_reaps_child(resampled_asr, monkeypatch):
    root, request, _, original = resampled_asr
    pid, workspaces = root / "child.pid", []

    async def backend(args, timeout):
        if args[-1] == "probe":
            return original(args, timeout)
        if args[-1] == "-version":
            return b"ffmpeg version test\n"
        workspaces.append(Path(args[-1]).parent)
        return await run_meter_async(child_args(pid), timeout)

    monkeypatch.setattr(asr_job, "run_meter_async", backend)

    async def exercise():
        task = asyncio.create_task(asr_job.recognize_async(request, str(root)))
        for _ in range(100):
            if pid.exists():
                break
            await asyncio.sleep(0.01)
        assert pid.exists()
        task.cancel()
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert_gone(root, pid, workspaces)


def test_source_byte_cap_rejects_sparse_file_before_validator_or_pcm_allocation(tmp_path):
    from kinocut_sound.limits import MAX_ASR_INPUT_BYTES
    from kinocut_sound.public.mix_files import open_root, read_asset

    source = tmp_path / "huge.wav"
    with source.open("wb") as output:
        output.truncate(MAX_ASR_INPUT_BYTES + 1)
    called = False

    def validator(*_):
        nonlocal called
        called = True

    with open_root(str(tmp_path)) as root, pytest.raises(SoundContractError):
        read_asset(root, source.name, "sha256:" + "0" * 64, MAX_ASR_INPUT_BYTES, validator=validator)
    assert not called


def test_read_validator_restores_position_and_keeps_hash_verification(tmp_path):
    from kinocut_sound.public.mix_files import open_root, read_asset

    material = b"stable same-descriptor contents"
    (tmp_path / "source").write_bytes(material)
    digest = "sha256:" + hashlib.sha256(material).hexdigest()
    handles = []

    def validator(handle, size):
        handles.append(handle)
        assert size == len(material)
        handle.seek(size)

    with open_root(str(tmp_path)) as root:
        assert read_asset(root, "source", digest, len(material), validator=validator) == material
        with pytest.raises(SoundContractError, match="hash mismatch"):
            read_asset(root, "source", "sha256:" + "0" * 64, len(material), validator=validator)
    assert all(handle.closed for handle in handles)


def test_read_validator_exception_and_concurrent_mutation_cannot_return_material(tmp_path):
    from kinocut_sound.public.mix_files import open_root, read_asset
    from kinocut_sound.public.asr_request import asr_error

    source = tmp_path / "source"
    source.write_bytes(b"original")
    handles = []

    def invalid(handle, _size):
        handles.append(handle)
        raise asr_error("invalid input")

    def mutate(handle, _size):
        handles.append(handle)
        source.write_bytes(b"modified")

    with open_root(str(tmp_path)) as root:
        with pytest.raises(SoundContractError, match="invalid input"):
            read_asset(root, source.name, "sha256:" + "0" * 64, 8, validator=invalid)
        with pytest.raises(SoundContractError, match="changed during read"):
            read_asset(root, source.name, "sha256:" + "0" * 64, 8, validator=mutate)
    assert all(handle.closed for handle in handles)


def test_missing_resampler_fails_explicitly_without_publication(resampled_asr, monkeypatch):
    from kinocut_sound.public.asr_request import AsrError

    root, request, _, _ = resampled_asr
    monkeypatch.setattr(asr_resample, "resolve_binary", lambda _: str(root / "missing-ffmpeg"))
    with pytest.raises(AsrError) as failure:
        asr_job.recognize_sync(request, str(root))
    assert failure.value.code == "asr_unavailable"
    assert str(root) not in str(failure.value)
    assert not (root / "output.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_native_16khz_input_requires_no_resampler(fake_asr, monkeypatch):  # noqa: F811
    root, request, _, _ = fake_asr

    def unavailable():
        raise AssertionError("native PCM must bypass optional resampler")

    monkeypatch.setattr(asr_resample, "installed_resampler", unavailable)
    result = asr_job.recognize_sync(request, str(root))
    assert result["backend"]["resampling"] == "pcm16-normalization-no-resampling-v1"
