"""Local caption speech with shared safe files and directly supervised children."""

from __future__ import annotations

from array import array
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
import time

from kinocut_sound.defaults import (
    DEFAULT_DUB_AMPLITUDE,
    DEFAULT_DUB_SAMPLE_RATE_HZ,
    DEFAULT_DUB_TOTAL_TIMEOUT_SECONDS,
    DEFAULT_DUB_WORDS_PER_MINUTE,
)
from kinocut_sound.limits import (
    DUB_ASSEMBLY_MEMORY_MULTIPLIER,
    MAX_DUB_CAPTION_BYTES,
    MAX_DUB_MEMORY_BYTES,
    MAX_DUB_WAV_BYTES,
)
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix._wav import parse_wav
from kinocut_sound.public.dub_bundle import finish_bundle
from kinocut_sound.public.dub_process import engine_version, remaining, resolve_engine, run_async, run_sync
from kinocut_sound.public.dub_request import load_dub_request, parse_captions
from kinocut_sound.public.mix_files import _read_regular_file, open_parent, open_root, read_asset, staged_output


@dataclass
class _DubJob:
    request: object
    cues: tuple
    pcm: array
    engine: str
    workspace: Path
    workspace_fd: int
    parent_fd: int
    output_name: str
    stage_fd: int
    stage_name: str
    deadline: float
    version: str = ""
    wav_bytes: int = 0
    media: dict = field(default_factory=dict)
    cue_proofs: list = field(default_factory=list)

    def command(self, index):
        output = self.workspace / f"cue-{index:04d}.wav"
        return [
            self.engine,
            "--stdin",
            "-b",
            "1",
            "-v",
            self.request.selected_voice,
            "-s",
            str(DEFAULT_DUB_WORDS_PER_MINUTE),
            "-a",
            str(DEFAULT_DUB_AMPLITUDE),
            "-D",
            "-w",
            str(output),
        ]

    def accept(self, index, cue):
        remaining(self.deadline)
        raw = _read_regular_file(self.workspace_fd, f"cue-{index:04d}.wav", MAX_DUB_WAV_BYTES - self.wav_bytes)
        size = len(raw)
        pcm, rate = parse_wav(raw)
        if rate != DEFAULT_DUB_SAMPLE_RATE_HZ or not pcm or not any(pcm):
            raise mix_error("speech engine returned empty, silent or unexpected-rate audio", "dub_invalid_audio")
        start, end = cue.start_ms * rate // 1000, cue.end_ms * rate // 1000
        if len(pcm) > end - start:
            raise mix_error(f"caption cue {index} speech exceeds its exact sample window", "dub_slot_overflow")
        self.pcm[start : start + len(pcm)] = pcm
        member = f"clips/cue-{index:04d}.wav"
        self.media[member] = raw
        self.wav_bytes += size
        self.cue_proofs.append(
            {"cue_index": index, "start_sample": start, "end_sample": end, "speech_samples": len(pcm), "path": member}
        )
        remaining(self.deadline)


def _check_output(parent_fd, name):
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise mix_error("speech output exists; choose a new path", "mix_output_conflict")


@contextmanager
def _job(payload, project_root):
    deadline = time.monotonic() + DEFAULT_DUB_TOTAL_TIMEOUT_SECONDS
    request = load_dub_request(payload)
    if not isinstance(project_root, str) or not project_root:
        raise mix_error("caption speech requires an explicit project root", MIX_INPUT_INVALID)
    try:
        with open_root(project_root) as root, open_parent(root, request.output_path) as (parent, name):
            _check_output(parent, name)
            raw = read_asset(root, request.source.path, request.source.sha256, MAX_DUB_CAPTION_BYTES)
            cues = parse_captions(raw)
            samples = cues[-1].end_ms * DEFAULT_DUB_SAMPLE_RATE_HZ // 1000
            if samples * 2 * DUB_ASSEMBLY_MEMORY_MULTIPLIER + MAX_DUB_WAV_BYTES > MAX_DUB_MEMORY_BYTES:
                raise mix_error("caption assembly exceeds memory estimate", MIX_OVER_LIMIT)
            engine = resolve_engine()
            remaining(deadline)
            with (
                tempfile.TemporaryDirectory(prefix="kinocut-speech-") as folder,
                open_root(folder) as workspace_fd,
                staged_output(parent) as (fd, stage),
            ):
                yield _DubJob(
                    request,
                    cues,
                    array("h", [0]) * samples,
                    engine,
                    Path(folder),
                    workspace_fd,
                    parent,
                    name,
                    fd,
                    stage,
                    deadline,
                )
    except OSError as exc:
        raise mix_error("caption speech files could not be read or published", "dub_file_failed") from exc


def render_dub_request(payload, project_root):
    with _job(payload, project_root) as job:
        job.version = engine_version(run_sync([job.engine, "--version"], b"", job.deadline))
        for index, cue in enumerate(job.cues, start=1):
            run_sync(job.command(index), cue.text.encode("utf-8"), job.deadline)
            job.accept(index, cue)
        return finish_bundle(job)


async def render_dub_request_async(payload, project_root):
    with _job(payload, project_root) as job:
        job.version = engine_version(await run_async([job.engine, "--version"], b"", job.deadline))
        for index, cue in enumerate(job.cues, start=1):
            await run_async(job.command(index), cue.text.encode("utf-8"), job.deadline)
            job.accept(index, cue)
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        return finish_bundle(job)
