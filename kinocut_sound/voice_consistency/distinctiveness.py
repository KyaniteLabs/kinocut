"""Cross-character spectral distinctiveness and collision detection.

Provides a lightweight, dependency-free spectral distance between two mono
16-bit PCM WAV byte strings. The distance is based on RMS energy, zero-crossing
rate, high-band energy, and a downsampled pitch-period proxy so the tests stay
deterministic without requiring NumPy, SciPy, or librosa.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_METRIC_INVALID,
    bounded_consistency_error,
)


def _parse_wav(wav_bytes: bytes) -> tuple[tuple[int, ...], int]:
    """Return mono 16-bit PCM samples and sample rate from ``wav_bytes``."""

    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise bounded_consistency_error(
            "wav_bytes must be a valid WAV container",
            CONSISTENCY_METRIC_INVALID,
        )
    audio_format = struct.unpack_from("<H", wav_bytes, 20)[0]
    if audio_format != 1:
        raise bounded_consistency_error(
            "wav_bytes must be PCM format",
            CONSISTENCY_METRIC_INVALID,
        )
    channel_count = struct.unpack_from("<H", wav_bytes, 22)[0]
    sample_rate = struct.unpack_from("<I", wav_bytes, 24)[0]
    bits_per_sample = struct.unpack_from("<H", wav_bytes, 34)[0]
    if channel_count != 1:
        raise bounded_consistency_error(
            "spectral_distance supports mono WAV only",
            CONSISTENCY_METRIC_INVALID,
        )
    if bits_per_sample != 16:
        raise bounded_consistency_error(
            "spectral_distance supports 16-bit PCM only",
            CONSISTENCY_METRIC_INVALID,
        )
    data_offset = wav_bytes.find(b"data")
    if data_offset < 0:
        raise bounded_consistency_error(
            "wav_bytes missing data chunk",
            CONSISTENCY_METRIC_INVALID,
        )
    data_size = struct.unpack_from("<I", wav_bytes, data_offset + 4)[0]
    start = data_offset + 8
    count = data_size // 2
    samples = tuple(
        struct.unpack_from("<h", wav_bytes, start + i * 2)[0] for i in range(count)
    )
    return samples, sample_rate


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _features(samples: tuple[int, ...], sample_rate: int) -> tuple[float, float, float, float]:
    """Return (rms, zcr, highband_energy, pitch_proxy) features in [0, 1]."""

    n = len(samples)
    if n == 0:
        return (0.0, 0.0, 0.0, 0.0)
    sum_squares = sum(s * s for s in samples)
    rms = math.sqrt(sum_squares / n) / 32768.0
    crossings = sum(
        1 for i in range(1, n) if (samples[i - 1] >= 0) != (samples[i] >= 0)
    )
    zcr = crossings / n
    if n > 1:
        highband = sum(abs(samples[i] - samples[i - 1]) for i in range(1, n)) / (
            (n - 1) * 65536.0
        )
    else:
        highband = 0.0

    # Fast pitch proxy via decimated samples and a short lag window.
    factor = max(1, sample_rate // 5512)
    ds = samples[::factor]
    ds_rate = sample_rate / factor
    min_lag = max(1, int(ds_rate / 400))
    max_lag = min(len(ds) - 1, max(min_lag + 1, int(ds_rate / 80)))
    window = ds[: min(len(ds), 1024)]
    w = len(window)
    max_lag = min(max_lag, w - 1)
    denom = sum(s * s for s in window) or 1.0
    best = 0.0
    for lag in range(min_lag, max_lag + 1):
        corr = 0.0
        for i in range(w - lag):
            corr += window[i] * window[i + lag]
        best = max(best, corr / denom)
    pitch_proxy = _clamp(best, 0.0, 1.0)
    return (rms, zcr, highband, pitch_proxy)


def spectral_distance(wav_a: bytes, wav_b: bytes) -> float:
    """Return a bounded distance in ``[0, 1]`` between two WAV signals."""

    samples_a, rate_a = _parse_wav(wav_a)
    samples_b, rate_b = _parse_wav(wav_b)
    if rate_a != rate_b:
        raise bounded_consistency_error(
            "spectral_distance requires matching sample rates",
            CONSISTENCY_METRIC_INVALID,
        )
    feat_a = _features(samples_a, rate_a)
    feat_b = _features(samples_b, rate_b)
    # Weighted L1 over (rms, zcr, highband, pitch). ZCR/highband are amplified
    # so roster pitch/formant deltas separate above the collision threshold.
    weights = (2.0, 25.0, 25.0, 12.0)
    score = 0.0
    for i, weight in enumerate(weights):
        score += weight * abs(feat_a[i] - feat_b[i])
    return float(_clamp(score, 0.0, 1.0))


@dataclass(frozen=True)
class DistinctivenessReport:
    """Result of cross-character collision detection."""

    pairs: tuple[tuple[str, str], ...]
    distances: tuple[float, ...]
    threshold: float
    collisions: tuple[tuple[str, str], ...]
    has_collision: bool


def detect_collisions(
    pairs: tuple[tuple[str, bytes], ...],
    *,
    threshold: float = 0.05,
) -> DistinctivenessReport:
    """Flag character-slot pairs whose spectral distance falls below threshold."""

    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise bounded_consistency_error(
            "threshold must be a number",
            CONSISTENCY_METRIC_INVALID,
        )
    if not 0.0 <= threshold <= 1.0:
        raise bounded_consistency_error(
            "threshold must be in [0.0, 1.0]",
            CONSISTENCY_METRIC_INVALID,
        )
    if len(pairs) < 2:
        return DistinctivenessReport(
            pairs=(),
            distances=(),
            threshold=float(threshold),
            collisions=(),
            has_collision=False,
        )

    compared: list[tuple[str, str]] = []
    distances: list[float] = []
    collisions: list[tuple[str, str]] = []
    for i in range(len(pairs)):
        id_a, wav_a = pairs[i]
        for j in range(i + 1, len(pairs)):
            id_b, wav_b = pairs[j]
            dist = spectral_distance(wav_a, wav_b)
            compared.append((id_a, id_b))
            distances.append(dist)
            if dist < threshold:
                collisions.append((id_a, id_b))

    return DistinctivenessReport(
        pairs=tuple(compared),
        distances=tuple(distances),
        threshold=float(threshold),
        collisions=tuple(collisions),
        has_collision=len(collisions) > 0,
    )
