"""Actual FFmpeg EBU R128 analysis of unchanged validated source bytes."""

from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
import shutil
import tempfile

from kinocut_sound._errors import SoundContractError
from kinocut_sound.defaults import DEFAULT_LOUDNESS_METER_TIMEOUT_SECONDS, DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS
from kinocut_sound.limits import (
    MAX_MIX_DURATION_SECONDS,
    MAX_MIX_INPUT_BYTES,
    MAX_MIX_SAMPLE_RATE_HZ,
    MIN_MIX_SAMPLE_RATE_HZ,
    MIN_LOUDNESS_MATERIAL_SECONDS,
    MIN_MEASURABLE_INTEGRATED_LUFS,
)
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.qa._errors import QA_INPUT_INVALID, QA_UNAVAILABLE, qa_error
from kinocut_sound.qa.meter_process import run_meter_async, run_meter_sync
from kinocut_sound.validation import EBUR128_SUMMARY_RE, FFMPEG_METER_VERSION_RE, PCM_MIX_CHANNEL_COUNTS


def validate_material(data, *, channel_counts=PCM_MIX_CHANNEL_COUNTS):
    if not isinstance(data, bytes) or len(data) > MAX_MIX_INPUT_BYTES:
        raise qa_error("meter input must be bounded WAV bytes", QA_INPUT_INVALID)
    try:
        samples, rate, channels = decode_pcm_wav(data)
    except SoundContractError as exc:
        raise qa_error("meter input must be valid mono or stereo PCM16 WAV", QA_INPUT_INVALID) from exc
    if channels not in channel_counts:
        raise qa_error("input WAV channel layout is unsupported for this operation", QA_INPUT_INVALID)
    if not MIN_MIX_SAMPLE_RATE_HZ <= rate <= MAX_MIX_SAMPLE_RATE_HZ:
        raise qa_error("meter sample rate exceeds supported limits", QA_INPUT_INVALID)
    frames = len(samples) // channels
    if frames / rate > MAX_MIX_DURATION_SECONDS:
        raise qa_error("meter input exceeds duration limit", QA_INPUT_INVALID)
    if frames / rate < MIN_LOUDNESS_MATERIAL_SECONDS or not any(samples):
        raise qa_error("meter requires non-silent material of at least three seconds", "qa_unmeasurable")
    return rate, frames, channels


def parse_summary(output):
    text = output.decode("utf-8", errors="replace")
    if "Summary:" not in text:
        raise qa_error("meter returned no final summary", "qa_meter_invalid_output")
    summary = text.rsplit("Summary:", 1)[1].lstrip()
    match = EBUR128_SUMMARY_RE.match(summary)
    if match is None:
        raise qa_error("meter returned incomplete summary", "qa_meter_invalid_output")
    try:
        integrated, lra, peak = map(float, match.groups())
    except ValueError as exc:
        raise qa_error("meter returned invalid metrics", "qa_meter_invalid_output") from exc
    if not all(math.isfinite(x) for x in (integrated, peak, lra)) or integrated <= MIN_MEASURABLE_INTEGRATED_LUFS:
        raise qa_error("meter could not measure gated material", "qa_unmeasurable")
    if lra < 0:
        raise qa_error("meter returned invalid loudness range", "qa_meter_invalid_output")
    return integrated, peak, lra


def _version(output):
    match = FFMPEG_METER_VERSION_RE.match(output.decode("utf-8", errors="replace"))
    if match is None:
        raise qa_error("meter returned invalid backend version", "qa_meter_invalid_output")
    return match[1]


def measurement_args(binary, path):
    return [
        binary,
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-i",
        str(path),
        "-af",
        "ebur128=peak=true:framelog=verbose",
        "-f",
        "null",
        "-",
    ]


@contextmanager
def _input(data):
    validate_material(data)
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise qa_error("loudness measurement requires FFmpeg", QA_UNAVAILABLE)
    try:
        with tempfile.TemporaryDirectory(prefix="kinocut-meter-") as folder:
            path = Path(folder) / "source.wav"
            path.write_bytes(data)
            args = measurement_args(binary, path)
            yield binary, args
    except OSError as exc:
        raise qa_error("meter private workspace unavailable", QA_UNAVAILABLE) from exc


def measure_with_identity(data):
    with _input(data) as (binary, args):
        version = _version(run_meter_sync([binary, "-version"], DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS))
        metrics = parse_summary(run_meter_sync(args, DEFAULT_LOUDNESS_METER_TIMEOUT_SECONDS))
    return metrics, version


async def measure_with_identity_async(data):
    with _input(data) as (binary, args):
        version = _version(await run_meter_async([binary, "-version"], DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS))
        metrics = parse_summary(await run_meter_async(args, DEFAULT_LOUDNESS_METER_TIMEOUT_SECONDS))
    return metrics, version
