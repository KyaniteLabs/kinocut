"""Fixed two-pass normalization commands and strict backend summary parsing."""

import json
import math
import time

from kinocut_sound.defaults import (
    DEFAULT_MASTER_LIMITER_ATTACK_MS,
    DEFAULT_MASTER_LIMITER_RELEASE_MS,
    DEFAULT_MASTER_LRA_LU,
)
from kinocut_sound.post._subprocess import ffmpeg_filter_number
from kinocut_sound.public.master_request import internal_peak, master_error
from kinocut_sound.qa.meter_process import run_meter_async, run_meter_sync


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise master_error("mastering exceeded its total deadline", "master_timeout")
    return seconds


def run_sync(args, deadline):
    return run_meter_sync(args, remaining(deadline))


async def run_async(args, deadline):
    return await run_meter_async(args, remaining(deadline))


def parse_normalization(output):
    try:
        text = output.decode("utf-8", errors="strict")
        fields, _ = json.JSONDecoder().raw_decode(text[text.rindex("{") :])
        names = (
            "input_i",
            "input_tp",
            "input_lra",
            "input_thresh",
            "target_offset",
            "output_i",
            "output_tp",
            "output_lra",
            "output_thresh",
        )
        if any(isinstance(fields[name], bool) for name in names):
            raise ValueError("invalid numeric summary")
        values = {name: float(fields[name]) for name in names}
        mode = fields["normalization_type"]
        if mode not in {"linear", "dynamic"} or not all(math.isfinite(v) for v in values.values()):
            raise ValueError("invalid normalization summary")
        if values["input_lra"] < 0 or values["output_lra"] < 0:
            raise ValueError("negative loudness range")
        return values, mode
    except (UnicodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise master_error("normalizer returned no complete finite summary", "master_invalid_analysis") from exc


def _target(policy):
    number = ffmpeg_filter_number
    return (
        f"loudnorm=I={number(policy.loudness.integrated_lufs, digits=6)}"
        f":TP={number(internal_peak(policy), digits=6)}"
        f":LRA={number(DEFAULT_MASTER_LRA_LU)}"
    )


def analysis_args(job):
    return [*job.base, "-af", _target(job.request.delivery) + ":print_format=json", "-f", "null", "-"]


def render_args(job, measurements):
    pairs = (
        ("measured_I", "input_i"),
        ("measured_TP", "input_tp"),
        ("measured_LRA", "input_lra"),
        ("measured_thresh", "input_thresh"),
        ("offset", "target_offset"),
    )
    number = ffmpeg_filter_number
    measured = ":".join(f"{key}={number(measurements[name], digits=6)}" for key, name in pairs)
    peak = internal_peak(job.request.delivery)
    filt = (
        _target(job.request.delivery) + ":" + measured + ":linear=true:print_format=json"
        f",alimiter=limit={number(10 ** (peak / 20), digits=6)}"
        f":attack={number(DEFAULT_MASTER_LIMITER_ATTACK_MS)}"
        f":release={number(DEFAULT_MASTER_LIMITER_RELEASE_MS)}:level=false:latency=true"
    )
    return [
        *job.base,
        "-af",
        filt,
        "-ar",
        str(job.output_rate),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-fs",
        str(job.output_limit),
        str(job.output),
    ]
