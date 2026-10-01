"""Fixed bandlimited PCM preprocessing inside the existing owned ASR pipeline."""

import re
from pathlib import Path

from kinocut_sound.defaults import (
    DEFAULT_ASR_SAMPLE_RATE_HZ,
    DEFAULT_ASR_RESAMPLER_FILTER_SIZE,
    DEFAULT_ASR_RESAMPLER_PHASE_SHIFT,
    DEFAULT_ASR_RESAMPLER_CUTOFF,
    DEFAULT_ASR_RESAMPLER_GUARD_FRAMES,
)
from kinocut_sound.post._subprocess import resolve_binary
from kinocut_sound.post._errors import PostError
from kinocut_sound.public.asr_request import asr_error

RESAMPLING_ID = "ffmpeg-swr-bandlimited-16khz-v1"


def installed_resampler():
    try:
        return str(Path(resolve_binary("ffmpeg")).resolve(strict=True))
    except (PostError, OSError) as exc:
        raise asr_error("installed FFmpeg resampler unavailable", "asr_unavailable") from exc


def backend_version(raw):
    try:
        words = raw.decode("utf-8").splitlines()[0].split()
    except (UnicodeError, IndexError) as exc:
        raise asr_error("resampler version unavailable", "asr_unavailable") from exc
    if len(words) < 3 or words[:2] != ["ffmpeg", "version"] or not re.fullmatch(r"[A-Za-z0-9._+:-]{1,80}", words[2]):
        raise asr_error("resampler version unavailable", "asr_unavailable")
    return words[2]


def command(binary, job):
    count = round(job.duration * DEFAULT_ASR_SAMPLE_RATE_HZ)
    # Zero guard lets the FIR flush without changing the declared output length.
    filt = (
        f"apad=pad_len={DEFAULT_ASR_RESAMPLER_GUARD_FRAMES},"
        f"aresample={DEFAULT_ASR_SAMPLE_RATE_HZ}:resampler=swr:"
        f"filter_size={DEFAULT_ASR_RESAMPLER_FILTER_SIZE}:"
        f"phase_shift={DEFAULT_ASR_RESAMPLER_PHASE_SHIFT}:cutoff={DEFAULT_ASR_RESAMPLER_CUTOFF},"
        f"atrim=end_sample={count}"
    )
    return [
        binary,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-f",
        "s16le",
        "-ar",
        str(job.rate),
        "-ac",
        "1",
        "-i",
        str(job.root / "source.pcm"),
        "-af",
        filt,
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        str(job.root / "source.f32"),
    ]
