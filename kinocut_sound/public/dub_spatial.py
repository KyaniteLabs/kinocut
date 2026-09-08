"""Versioned spatial processing for real, already synthesized cue PCM."""

import hashlib
import shutil
from tempfile import TemporaryFile

from kinocut_sound.defaults import (
    DEFAULT_DUB_SAMPLE_RATE_HZ,
    DEFAULT_DUB_SPATIAL_THREADS,
    DEFAULT_SPATIAL_CROSSOVER_HZ,
    DEFAULT_SPATIAL_ROLLOFF_DB,
    DEFAULT_SPATIAL_DISTANCE_Q,
)
from kinocut_sound._errors import SoundContractError
from kinocut_sound.limits import (
    DUB_ASSEMBLY_MEMORY_MULTIPLIER,
    MAX_DUB_WAV_BYTES,
    MAX_DUB_MEMORY_BYTES,
    DUB_SPATIAL_NATIVE_MEMORY_BYTES,
    DUB_SPATIAL_METADATA_BYTES,
    DUB_SPATIAL_IO_BYTES,
)
from kinocut_sound.mix._errors import MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix._wav import wav_from_pcm
from kinocut_sound.post.spatial import _distance_filter, MAX_DISTANCE_PCT
from kinocut_sound.public.dub_job import _validated_cue
from kinocut_sound.public.dub_process import remaining
from kinocut_sound.public.mix_files import _read_regular_file
from kinocut_sound.public.mix_process import run_worker_sync
from kinocut_sound.public.mix_process_async import run_worker_async
from kinocut_sound.qa.meter import _version


def _sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _dry_cue(job, index, cue):
    remaining(job.deadline)
    data = _read_regular_file(job.workspace_fd, f"cue-{index:04d}.wav", MAX_DUB_WAV_BYTES - job.wav_bytes)
    pcm, _rate, _start, _end = _validated_cue(data, index, cue)
    frames = len(pcm)
    if job.request.spatial_profile != "close_mic_dry":
        header = len(wav_from_pcm(b"", sample_rate_hz=DEFAULT_DUB_SAMPLE_RATE_HZ))
        processed = header + frames * 2
        peak = (
            len(job.pcm) * 2 * DUB_ASSEMBLY_MEMORY_MULTIPLIER
            + job.wav_bytes
            + 4 * len(data)
            + 4 * processed
            + DUB_SPATIAL_NATIVE_MEMORY_BYTES
            + DUB_SPATIAL_METADATA_BYTES
            + DUB_SPATIAL_IO_BYTES
        )
        if peak > MAX_DUB_MEMORY_BYTES or processed > MAX_DUB_WAV_BYTES - job.wav_bytes:
            raise mix_error("speech spatial processing exceeds memory or WAV limits", MIX_OVER_LIMIT)
    return data, frames


def _binary():
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise mix_error("distance speech requires FFmpeg", "dub_spatial_unavailable")
    return binary


def _args(binary):
    filt, _metrics = _distance_filter({"distance_pct": MAX_DISTANCE_PCT})
    threads = str(DEFAULT_DUB_SPATIAL_THREADS)
    return [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-threads",
        threads,
        "-filter_threads",
        threads,
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-af",
        filt,
        "-ar",
        str(DEFAULT_DUB_SAMPLE_RATE_HZ),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    ]


def _backend(job, code, output):
    if code:
        raise mix_error("spatial backend identity probe failed", "dub_spatial_failed")
    _filt, metrics = _distance_filter({"distance_pct": MAX_DISTANCE_PCT})
    job.spatial_backend = {
        "id": "ffmpeg",
        "version": _version(output),
        "adapter_id": "spatial_distance",
        "decoder_threads": DEFAULT_DUB_SPATIAL_THREADS,
        "filter_threads": DEFAULT_DUB_SPATIAL_THREADS,
        "metrics": metrics,
        "parameters": {
            "distance_pct": MAX_DISTANCE_PCT,
            "crossover_hz": DEFAULT_SPATIAL_CROSSOVER_HZ,
            "rolloff_db": DEFAULT_SPATIAL_ROLLOFF_DB,
            "q": DEFAULT_SPATIAL_DISTANCE_Q,
        },
    }


def _processed(raw, code, frames, index, cue):
    if code:
        raise mix_error("speech spatial backend failed", "dub_spatial_failed")
    raw.flush()
    if raw.seek(0, 2) != frames * 2:
        raise mix_error("spatial output changed cue frame count", "dub_spatial_failed")
    raw.seek(0)
    data = wav_from_pcm(raw.read(frames * 2), sample_rate_hz=DEFAULT_DUB_SAMPLE_RATE_HZ)
    pcm, _rate, _start, _end = _validated_cue(data, index, cue)
    if len(pcm) != frames:
        raise mix_error("spatial output was truncated", "dub_spatial_failed")
    return data


def _record(job, index, dry, processed, frames):
    job.spatial_cues.append(
        {
            "cue_index": index,
            "dry_sha256": _sha(dry),
            "processed_sha256": _sha(processed),
            "dry_frames": frames,
            "processed_frames": frames,
            "applied": job.request.spatial_profile != "close_mic_dry",
        }
    )
    return processed


def _failure(error):
    code = "dub_timeout" if error.code in ("mix_timeout", "dub_timeout") else "dub_spatial_failed"
    return mix_error("speech spatial backend failed or exceeded its deadline", code)


def _spatial_sync(job, index, cue):
    dry, frames = _dry_cue(job, index, cue)
    if job.request.spatial_profile == "close_mic_dry":
        return _record(job, index, dry, dry, frames)
    binary = _binary()
    try:
        if job.spatial_backend is None:
            _backend(job, *run_worker_sync([binary, "-version"], b"", (), remaining(job.deadline)))
        with TemporaryFile(dir=job.workspace) as raw:
            code, _out = run_worker_sync(
                _args(binary), dry, (), remaining(job.deadline), stdout_sink=raw, stdout_limit=frames * 2
            )
            processed = _processed(raw, code, frames, index, cue)
    except SoundContractError as exc:
        raise _failure(exc) from exc
    return _record(job, index, dry, processed, frames)


async def _spatial_async(job, index, cue):
    dry, frames = _dry_cue(job, index, cue)
    if job.request.spatial_profile == "close_mic_dry":
        return _record(job, index, dry, dry, frames)
    binary = _binary()
    try:
        if job.spatial_backend is None:
            _backend(job, *await run_worker_async([binary, "-version"], b"", (), remaining(job.deadline)))
        with TemporaryFile(dir=job.workspace) as raw:
            code, _out = await run_worker_async(
                _args(binary), dry, (), remaining(job.deadline), stdout_sink=raw, stdout_limit=frames * 2
            )
            processed = _processed(raw, code, frames, index, cue)
    except SoundContractError as exc:
        raise _failure(exc) from exc
    return _record(job, index, dry, processed, frames)
