"""Fixed guarded resampling through one directly owned backend child."""

from dataclasses import asdict, dataclass
import shutil

from kinocut_sound.post._subprocess import ffmpeg_filter_number
from kinocut_sound.defaults import (
    DEFAULT_MIX_CONVERSION_THREADS,
    DEFAULT_MIX_CONVERSION_PRECISION,
    DEFAULT_MIX_CONVERSION_CUTOFF,
    DEFAULT_MIX_CONVERSION_CHEBY,
    DEFAULT_MIX_CONVERSION_DITHER_METHOD,
)
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MixError, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav, wav_from_pcm
from kinocut_sound.public.mix_conversion_shape import ConversionShape, conversion_shape
from kinocut_sound.public.mix_process import remaining, run_worker_sync
from kinocut_sound.public.mix_process_async import run_worker_async


@dataclass(frozen=True)
class ConvertedAudio:
    wav_bytes: bytes
    shape: ConversionShape
    raw_frames: int


def _resolve_backend():
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise mix_error("sample-rate backend is unavailable", "mix_conversion_unavailable")
    return binary


def _checked_shape(data, shape):
    if not isinstance(shape, ConversionShape) or any(type(value) is not int for value in asdict(shape).values()):
        raise mix_error("conversion requires a strict frame shape", MIX_INPUT_INVALID)
    pcm, rate, channels = decode_pcm_wav(data)
    expected = conversion_shape(len(pcm) // channels, rate, shape.target_rate, channels)
    if expected != shape:
        raise mix_error("conversion source shape changed", MIX_INPUT_INVALID)


def _conversion_args(binary, shape):
    if binary is None:
        raise mix_error("sample-rate backend is unavailable", "mix_conversion_unavailable")
    guard = ffmpeg_filter_number(shape.guard_frames, digits=0)
    rate = ffmpeg_filter_number(shape.target_rate, digits=0)
    options = {
        "precision": DEFAULT_MIX_CONVERSION_PRECISION,
        "cutoff": DEFAULT_MIX_CONVERSION_CUTOFF,
        "cheby": int(DEFAULT_MIX_CONVERSION_CHEBY),
        "dither_method": DEFAULT_MIX_CONVERSION_DITHER_METHOD,
    }
    fixed = ":".join(
        f"{name}={ffmpeg_filter_number(value, digits=0 if type(value) is int else 2)}"
        for name, value in options.items()
    )
    filt = f"apad=pad_len={guard},aresample=osr={rate}:resampler=soxr:{fixed}"
    threads = str(DEFAULT_MIX_CONVERSION_THREADS)
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
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    ]


def _converted_output(raw, shape, returncode):
    if returncode:
        raise mix_error("sample-rate backend rejected the conversion", "mix_conversion_failed")
    raw.flush()
    size = raw.seek(0, 2)
    frame_bytes = 2 * shape.channels
    frames, partial = divmod(size, frame_bytes)
    if partial or frames not in (shape.raw_min, shape.raw_max) or frames < shape.target_frames:
        raise mix_error("resampler output is outside its frame envelope", "mix_conversion_failed")
    raw.seek(0)
    wanted = frame_bytes * shape.target_frames
    pcm = raw.read(wanted)
    if len(pcm) != wanted:
        raise mix_error("resampler output was truncated", "mix_conversion_failed")
    return ConvertedAudio(
        wav_from_pcm(pcm, sample_rate_hz=shape.target_rate, channel_count=shape.channels),
        shape,
        frames,
    )


def _conversion_failure(error):
    code = "mix_timeout" if error.code == "mix_timeout" else "mix_conversion_failed"
    return mix_error("sample-rate backend failed or exceeded its deadline", code)


def _convert_sync(data, shape, raw, binary, deadline):
    _checked_shape(data, shape)
    if not shape.changed:
        return ConvertedAudio(data, shape, shape.source_frames)
    try:
        code, _status = run_worker_sync(
            _conversion_args(binary, shape),
            data,
            (),
            remaining(deadline),
            stdout_sink=raw,
            stdout_limit=shape.raw_byte_limit,
        )
    except MixError as exc:
        raise _conversion_failure(exc) from exc
    return _converted_output(raw, shape, code)


async def _convert_async(data, shape, raw, binary, deadline):
    _checked_shape(data, shape)
    if not shape.changed:
        return ConvertedAudio(data, shape, shape.source_frames)
    try:
        code, _status = await run_worker_async(
            _conversion_args(binary, shape),
            data,
            (),
            remaining(deadline),
            stdout_sink=raw,
            stdout_limit=shape.raw_byte_limit,
        )
    except MixError as exc:
        raise _conversion_failure(exc) from exc
    return _converted_output(raw, shape, code)
