"""Privately normalize, measure final PCM, then exclusively publish a verified ZIP."""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
import time

from kinocut_sound.defaults import DEFAULT_MASTER_TOTAL_TIMEOUT_SECONDS, DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS
from kinocut_sound.limits import (
    MAX_MIX_INPUT_BYTES,
    MAX_MIX_MEMORY_BYTES,
    MAX_MASTER_WAV_HEADER_BYTES,
    MASTER_MEMORY_MULTIPLIER,
)
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.public.master_request import load_master_request, master_error
from kinocut_sound.public.master_render import (
    analysis_args,
    parse_normalization,
    remaining,
    render_args,
    run_async,
    run_sync,
)
from kinocut_sound.public.mix_files import (
    _read_regular_file,
    open_parent,
    open_root,
    read_asset,
    staged_output,
    publish,
)
from kinocut_sound.qa.loudness import evaluate_loudness
from kinocut_sound.qa.meter import _version, measurement_args, parse_summary, validate_material


@dataclass
class _MasterJob:
    request: object
    binary: str
    source: Path
    output: Path
    workspace_fd: int
    parent_fd: int
    output_name: str
    stage_fd: int
    stage_name: str
    deadline: float
    input_count: int
    input_rate: int
    output_rate: int
    output_count: int
    output_limit: int
    channel_count: int

    @property
    def base(self):
        return [self.binary, "-hide_banner", "-nostdin", "-nostats", "-y", "-i", str(self.source)]

    def accept(self):
        remaining(self.deadline)
        data = _read_regular_file(self.workspace_fd, "master.wav", self.output_limit)
        samples, rate, channels = decode_pcm_wav(data)
        if rate != self.output_rate or channels != self.channel_count or len(samples) != self.output_count * channels:
            raise master_error("normalizer returned unexpected audio format or frame count", "master_invalid_output")
        validate_material(data)
        remaining(self.deadline)
        return data


def _check_absent(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise master_error("master output exists; choose a new path", "master_output_conflict")


@contextmanager
def _job(payload, project_root):
    deadline = time.monotonic() + DEFAULT_MASTER_TOTAL_TIMEOUT_SECONDS
    request = load_master_request(payload, project_root)
    try:
        with open_root(project_root) as root, open_parent(root, request.output_path) as (parent, name):
            _check_absent(parent, name)
            data = read_asset(root, request.source.path, request.source.sha256, MAX_MIX_INPUT_BYTES)
            rate, count, channels = validate_material(data)
            output_rate = request.output_sample_rate_hz or rate
            output_count = round(count * output_rate / rate)
            output_limit = output_count * channels * 2 + MAX_MASTER_WAV_HEADER_BYTES
            if (
                output_limit > MAX_MIX_INPUT_BYTES
                or MASTER_MEMORY_MULTIPLIER * (len(data) + output_limit) > MAX_MIX_MEMORY_BYTES
            ):
                raise master_error("mastering exceeds input/output memory estimate", "master_over_limit")
            binary = shutil.which("ffmpeg")
            if binary is None:
                raise master_error("mastering requires installed FFmpeg", "master_unavailable")
            remaining(deadline)
            with tempfile.TemporaryDirectory(prefix="kinocut-master-") as folder, open_root(folder) as workspace:
                source, output = Path(folder) / "source.wav", Path(folder) / "master.wav"
                source.write_bytes(data)
                del data
                with staged_output(parent) as (fd, stage):
                    yield _MasterJob(
                        request,
                        binary,
                        source,
                        output,
                        workspace,
                        parent,
                        name,
                        fd,
                        stage,
                        deadline,
                        count,
                        rate,
                        output_rate,
                        output_count,
                        output_limit,
                        channels,
                    )
    except OSError as exc:
        raise master_error("mastering files could not be read or published", "master_file_failed") from exc


def _report(job, measured):
    report = evaluate_loudness(parse_summary(measured), job.request.delivery)
    if not report.within_tolerance:
        raise master_error("final mastered audio does not meet the requested targets", "master_target_unmet")
    return report


def render_master_request(payload, project_root):
    from kinocut_sound.public.master_bundle import prepare_bundle

    with _job(payload, project_root) as job:
        version_deadline = min(job.deadline, time.monotonic() + DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS)
        version = _version(run_sync([job.binary, "-version"], version_deadline))
        measurements, _ = parse_normalization(run_sync(analysis_args(job), job.deadline))
        rendered = run_sync(render_args(job, measurements), job.deadline)
        data = job.accept()
        _, mode = parse_normalization(rendered)
        report = _report(job, run_sync(measurement_args(job.binary, job.output), job.deadline))
        result = prepare_bundle(job, data, report, version, mode)
        remaining(job.deadline)
        publish(job.parent_fd, job.stage_name, job.output_name)
        return result


async def render_master_request_async(payload, project_root):
    from kinocut_sound.public.master_bundle import prepare_bundle

    with _job(payload, project_root) as job:
        version_deadline = min(job.deadline, time.monotonic() + DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS)
        version = _version(await run_async([job.binary, "-version"], version_deadline))
        measurements, _ = parse_normalization(await run_async(analysis_args(job), job.deadline))
        rendered = await run_async(render_args(job, measurements), job.deadline)
        data = job.accept()
        _, mode = parse_normalization(rendered)
        report = _report(job, await run_async(measurement_args(job.binary, job.output), job.deadline))
        await asyncio.sleep(0)
        result = prepare_bundle(job, data, report, version, mode)
        await asyncio.sleep(0)
        remaining(job.deadline)
        publish(job.parent_fd, job.stage_name, job.output_name)
        return result
