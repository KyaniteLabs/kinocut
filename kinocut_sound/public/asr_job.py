"""One shared owned recognition pipeline for synchronous and async public callers."""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from kinocut_sound.defaults import (
    DEFAULT_ASR_TOTAL_TIMEOUT_SECONDS,
    DEFAULT_ASR_PROBE_TIMEOUT_SECONDS,
    DEFAULT_ASR_THREADS,
    DEFAULT_ASR_SAMPLE_RATE_HZ,
    DEFAULT_ASR_DECODE,
)
from kinocut_sound.limits import (
    MAX_ASR_DURATION_SECONDS,
    MAX_ASR_SAMPLE_RATE_HZ,
    MAX_ASR_TEXT_BYTES,
    MAX_ASR_OUTPUT_BYTES,
    MAX_ASR_STAGING_BYTES,
    ASR_MEMORY_ESTIMATE_BYTES,
    MAX_MIX_INPUT_BYTES,
)
from kinocut_sound.mix._wav import parse_wav
from kinocut_sound.public.asr_bundle import prepare_bundle
from kinocut_sound.public.asr_compare import compare, remaining, validate_segments, words
from kinocut_sound.public.asr_request import load_asr_request, asr_error
from kinocut_sound.public.asr_runtime import copy_checkpoint, interpreters, parse_probe
from kinocut_sound.public.mix_files import (
    open_root,
    open_parent,
    read_asset,
    staged_output,
    _read_regular_file,
    publish,
)
from kinocut_sound.qa import QaError
from kinocut_sound.qa.meter import validate_material
from kinocut_sound.qa.meter_process import run_meter_sync, run_meter_async


@dataclass
class _AsrJob:
    request: object
    root: Path
    workspace_fd: int
    parent_fd: int
    output_name: str
    stage_fd: int
    stage_name: str
    deadline: float
    reference: str
    duration: float
    rate: int
    pcm_bytes: int


@contextmanager
def _job(payload, project_root):
    deadline = time.monotonic() + DEFAULT_ASR_TOTAL_TIMEOUT_SECONDS
    request = load_asr_request(payload, project_root)
    with open_root(project_root) as root:
        data = read_asset(root, request.source.path, request.source.sha256, MAX_MIX_INPUT_BYTES)
        validate_material(data)
        samples, rate = parse_wav(data)
        duration = len(samples) / rate
        if duration > MAX_ASR_DURATION_SECONDS or rate > MAX_ASR_SAMPLE_RATE_HZ:
            raise asr_error("ASR audio exceeds rate or duration bound", "asr_over_limit")
        raw_reference = read_asset(root, request.reference.path, request.reference.sha256, MAX_ASR_TEXT_BYTES)
        try:
            reference = raw_reference.decode("utf-8")
        except UnicodeError as exc:
            raise asr_error("ASR reference must be UTF-8 text") from exc
        if not words(reference):
            raise asr_error("ASR reference must contain words")
        with open_parent(root, request.output_path) as (parent, name):
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise asr_error("ASR output exists; choose a new path", "asr_output_conflict")
            with tempfile.TemporaryDirectory(prefix="kinocut-asr-") as temporary, staged_output(parent) as stage:
                folder = Path(temporary)
                if sys.byteorder != "little":
                    samples.byteswap()
                (folder / "source.pcm").write_bytes(samples.tobytes())
                (folder / "worker.py").write_bytes(Path(__file__).with_name("asr_worker.py").read_bytes())
                with open_root(temporary) as workspace:
                    yield _AsrJob(
                        request,
                        folder,
                        workspace,
                        parent,
                        name,
                        *stage,
                        deadline,
                        reference,
                        duration,
                        rate,
                        len(samples) * 2,
                    )


def _pipeline(job):
    worker = str(job.root / "worker.py")
    runtime = None
    for interpreter in interpreters():
        raw = yield ([interpreter, "-I", worker, "probe"], True)
        if raw is not None:
            runtime = parse_probe(raw)
            if runtime:
                break
    if runtime is None:
        raise asr_error("installed Whisper runtime unavailable", "asr_unavailable")
    digest = runtime["models"][job.request.model]
    model_bytes = copy_checkpoint(job.request.model, digest, job.root / "checkpoint.pt", job.deadline)
    decoded_bytes = round(job.duration * DEFAULT_ASR_SAMPLE_RATE_HZ) * 4
    if model_bytes + job.pcm_bytes + decoded_bytes + MAX_ASR_OUTPUT_BYTES > MAX_ASR_STAGING_BYTES:
        raise asr_error("ASR staging exceeds bound", "asr_over_limit")
    config = {
        "threads": DEFAULT_ASR_THREADS,
        "source_rate": job.rate,
        "target_rate": DEFAULT_ASR_SAMPLE_RATE_HZ,
        "model_digest": digest,
        "language": job.request.language,
        "decode": DEFAULT_ASR_DECODE,
        "max_output_bytes": MAX_ASR_OUTPUT_BYTES,
    }
    (job.root / "config.json").write_text(json.dumps(config))
    raw = yield ([interpreter, "-I", worker, "recognize"], False)
    if json.loads(raw) != {"recognized": True}:
        raise asr_error("recognizer did not return valid output", "asr_invalid_output")
    data = _read_regular_file(job.workspace_fd, "recognition.json", MAX_ASR_OUTPUT_BYTES)
    transcript, segments = validate_segments(json.loads(data), job.duration, job.rate)
    comparison = compare(job.reference, transcript, job.deadline)
    backend = {
        "id": "openai-whisper",
        "version": runtime["version"],
        "model": job.request.model,
        "model_sha256": "sha256:" + digest,
        "device": "cpu",
        "dtype": "float32",
        "threads": DEFAULT_ASR_THREADS,
        "language": job.request.language,
        "decode": DEFAULT_ASR_DECODE,
        "resampling": "linear-interpolation-16khz",
        "working_memory_estimate_bytes": ASR_MEMORY_ESTIMATE_BYTES,
    }
    return prepare_bundle(job, transcript, segments, comparison, backend)


def recognize_sync(payload, project_root):
    try:
        with _job(payload, project_root) as job:
            pipeline, output = _pipeline(job), None
            try:
                while True:
                    try:
                        args, probe = pipeline.send(output)
                    except StopIteration as result:
                        remaining(job.deadline)
                        publish(job.parent_fd, job.stage_name, job.output_name)
                        return result.value
                    timeout = remaining(job.deadline)
                    try:
                        output = run_meter_sync(
                            args, min(timeout, DEFAULT_ASR_PROBE_TIMEOUT_SECONDS) if probe else timeout
                        )
                    except QaError:
                        if not probe:
                            raise
                        output = None
            finally:
                pipeline.close()
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise asr_error("ASR execution returned invalid data", "asr_invalid_output") from exc


async def recognize_async(payload, project_root):
    try:
        with _job(payload, project_root) as job:
            pipeline, output = _pipeline(job), None
            try:
                while True:
                    await asyncio.sleep(0)
                    try:
                        args, probe = pipeline.send(output)
                    except StopIteration as result:
                        await asyncio.sleep(0)
                        remaining(job.deadline)
                        publish(job.parent_fd, job.stage_name, job.output_name)
                        return result.value
                    timeout = remaining(job.deadline)
                    try:
                        output = await run_meter_async(
                            args, min(timeout, DEFAULT_ASR_PROBE_TIMEOUT_SECONDS) if probe else timeout
                        )
                    except QaError:
                        if not probe:
                            raise
                        output = None
            finally:
                pipeline.close()
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise asr_error("ASR execution returned invalid data", "asr_invalid_output") from exc
