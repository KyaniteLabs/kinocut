"""Minimal mono 16-bit PCM WAV helpers for deterministic mix tests."""

from __future__ import annotations

import math
import struct
from array import array

from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error

DEFAULT_SAMPLE_RATE_HZ = 22050


def synthesize_tone(
    *,
    duration_seconds: float,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    frequency_hz: float = 440.0,
    amplitude: float = 0.25,
    seed: int = 0,
) -> bytes:
    """Return a mono PCM WAV of a pure tone (deterministic)."""

    if duration_seconds <= 0 or sample_rate_hz <= 0:
        raise mix_error("duration and sample rate must be positive", MIX_INPUT_INVALID)
    n = max(1, round(duration_seconds * sample_rate_hz))
    pcm = array("h")
    phase0 = (seed % 1000) * 0.001
    for i in range(n):
        t = i / sample_rate_hz
        sample = amplitude * math.sin(2.0 * math.pi * frequency_hz * t + phase0)
        pcm.append(int(max(-1.0, min(1.0, sample)) * 32767.0))
    return wav_from_pcm(pcm.tobytes(), sample_rate_hz=sample_rate_hz)


def silence_wav(
    *,
    duration_seconds: float,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
) -> bytes:
    if duration_seconds <= 0:
        raise mix_error("silence duration must be positive", MIX_INPUT_INVALID)
    n = max(1, round(duration_seconds * sample_rate_hz))
    return wav_from_pcm(bytes(n * 2), sample_rate_hz=sample_rate_hz)


def wav_from_pcm(pcm: bytes, *, sample_rate_hz: int, channel_count: int = 1) -> bytes:
    if channel_count != 1:
        raise mix_error("only mono WAV supported", MIX_INPUT_INVALID)
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channel_count,
        sample_rate_hz,
        sample_rate_hz * channel_count * 2,
        channel_count * 2,
        16,
        b"data",
        data_size,
    )
    return header + pcm


def parse_wav(wav_bytes: bytes) -> tuple[array, int]:
    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise mix_error("invalid WAV container", MIX_INPUT_INVALID)
    channels = struct.unpack_from("<H", wav_bytes, 22)[0]
    rate = struct.unpack_from("<I", wav_bytes, 24)[0]
    bits = struct.unpack_from("<H", wav_bytes, 34)[0]
    if channels != 1 or bits != 16:
        raise mix_error("WAV must be mono 16-bit PCM", MIX_INPUT_INVALID)
    offset = wav_bytes.find(b"data")
    if offset < 0:
        raise mix_error("WAV missing data chunk", MIX_INPUT_INVALID)
    size = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
    start = offset + 8
    samples = array("h")
    samples.frombytes(wav_bytes[start : start + size])
    return samples, rate


def duration_seconds(wav_bytes: bytes) -> float:
    samples, rate = parse_wav(wav_bytes)
    return len(samples) / float(rate)


def pcm_to_wav(samples: array, *, sample_rate_hz: int) -> bytes:
    return wav_from_pcm(samples.tobytes(), sample_rate_hz=sample_rate_hz)
