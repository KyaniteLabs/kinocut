"""Minimal mono 16-bit PCM WAV helpers for deterministic mix tests."""

from __future__ import annotations

import math
import struct
import sys
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
    """Decode bounded, structurally valid integer mono PCM16 RIFF/WAVE bytes."""
    if not isinstance(wav_bytes, bytes) or len(wav_bytes) < 44:
        raise mix_error("invalid WAV container", MIX_INPUT_INVALID)
    if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise mix_error("invalid WAV container", MIX_INPUT_INVALID)
    if struct.unpack_from("<I", wav_bytes, 4)[0] + 8 != len(wav_bytes):
        raise mix_error("WAV container length mismatch", MIX_INPUT_INVALID)
    chunks = {}
    offset = 12
    while offset < len(wav_bytes):
        if offset + 8 > len(wav_bytes):
            raise mix_error("truncated WAV chunk", MIX_INPUT_INVALID)
        kind, size = struct.unpack_from("<4sI", wav_bytes, offset)
        start = offset + 8
        end = start + size
        offset = end + (size % 2)
        if offset > len(wav_bytes):
            raise mix_error("truncated WAV chunk", MIX_INPUT_INVALID)
        if kind in (b"fmt ", b"data"):
            if kind in chunks:
                raise mix_error("duplicate WAV chunk", MIX_INPUT_INVALID)
            chunks[kind] = (start, size)
    if b"fmt " not in chunks or b"data" not in chunks or chunks[b"fmt "][1] < 16:
        raise mix_error("WAV requires format and data chunks", MIX_INPUT_INVALID)
    tag, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", wav_bytes, chunks[b"fmt "][0])
    if (tag, channels, bits, align) != (1, 1, 16, 2) or rate <= 0 or byte_rate != rate * align:
        raise mix_error("WAV must be mono 16-bit PCM", MIX_INPUT_INVALID)
    start, size = chunks[b"data"]
    if size % align:
        raise mix_error("WAV sample alignment mismatch", MIX_INPUT_INVALID)
    samples = array("h")
    samples.frombytes(wav_bytes[start : start + size])
    if sys.byteorder != "little":  # pragma: no cover - big-endian hosts
        samples.byteswap()
    return samples, rate


def duration_seconds(wav_bytes: bytes) -> float:
    samples, rate = parse_wav(wav_bytes)
    return len(samples) / float(rate)


def pcm_to_wav(samples: array, *, sample_rate_hz: int) -> bytes:
    if sys.byteorder != "little":  # pragma: no cover - big-endian hosts
        samples = array("h", samples)
        samples.byteswap()
    return wav_from_pcm(samples.tobytes(), sample_rate_hz=sample_rate_hz)
