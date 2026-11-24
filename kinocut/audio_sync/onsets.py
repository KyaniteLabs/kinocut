"""Drum-stem onset detection and confidence-gated pocket locking."""

from __future__ import annotations

import math
import sys
import wave
from array import array
from bisect import bisect_left
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..bounded_process import run_bounded
from ..engine_runtime_utils import _ffmpeg
from ..errors import MCPVideoError
from ..publication import record_operation_input

_BANDS = {"kick": (40, 150), "snare": (180, 2000), "hat": (5000, 14000)}
_PCM_BYTE_LIMIT = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Onset:
    time_s: float
    band: str
    strength: float
    confidence: float


def _pcm_frames(raw: bytes, width: int, channels: int) -> array:
    if width == 1:
        values = [value - 128 for value in raw]
    elif width == 3:
        values = [int.from_bytes(raw[start : start + 3], "little", signed=True) for start in range(0, len(raw), 3)]
    else:
        values = array({2: "h", 4: "i"}[width])
        values.frombytes(raw)
        if sys.byteorder == "big":
            values.byteswap()
    divisor = channels * (1 << (8 * width - 1))
    if channels == 1:
        return array("f", (value / divisor for value in values))
    return array("f", (sum(values[start : start + channels]) / divisor for start in range(0, len(values), channels)))


def _read_wav(path: Path, rate: int) -> array | None:
    try:
        with wave.open(str(path), "rb") as stream:
            if stream.getframerate() != rate:
                return None
            channels, width = stream.getnchannels(), stream.getsampwidth()
            if stream.getnframes() * channels * width > _PCM_BYTE_LIMIT:
                raise MCPVideoError("WAV exceeds the audio sync decode limit", code="audio_decode_limit")
            return _pcm_frames(stream.readframes(stream.getnframes()), width, channels)
    except (EOFError, wave.Error):
        return None


def _read_mono(path: str | Path, rate: int) -> array:
    source = Path(path).absolute()
    record_operation_input(str(source))
    if source.suffix.lower() == ".wav" and (pcm := _read_wav(source, rate)) is not None:
        return pcm
    proc = run_bounded(
        [
            _ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "f32le",
            "-",
        ],
        timeout=120,
        text=False,
        stdout_limit=_PCM_BYTE_LIMIT,
    )
    if proc.returncode:
        raise MCPVideoError("FFmpeg could not decode the audio input", code="audio_decode_failed")
    pcm = array("f")
    pcm.frombytes(proc.stdout)
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm


def _biquad(samples, rate: int, cutoff: float, *, highpass: bool = False) -> array:
    angle = math.tau * cutoff / rate
    cosine, alpha = math.cos(angle), math.sin(angle) / math.sqrt(2)
    factor = 1 / (1 + alpha)
    edge = (1 + cosine if highpass else 1 - cosine) * factor / 2
    middle = (-2 if highpass else 2) * edge
    feedback1, feedback2 = -2 * cosine * factor, (1 - alpha) * factor
    state1 = state2 = 0.0
    result = array("f")
    for sample in samples:
        filtered = edge * sample + state1
        state1 = middle * sample - feedback1 * filtered + state2
        state2 = edge * sample - feedback2 * filtered
        result.append(filtered)
    return result


def _envelope(pcm: array, low: int, high: int, rate: int, hop: int) -> list[float]:
    for _ in range(2):
        pcm = _biquad(_biquad(pcm, rate, low, highpass=True), rate, high)
    return [
        math.sqrt(sum(value * value for value in pcm[start : start + hop]) / hop) for start in range(0, len(pcm), hop)
    ]


def _envelope_onsets(levels: list[float], band: str, step_s: float) -> list[Onset]:
    peak = max(levels, default=0.0)
    gate = max(0.002, peak * 0.08)
    baseline = 0.0
    last = -math.inf
    found = []
    for index, level in enumerate(levels):
        time_s = index * step_s
        if level >= gate and level > 1.5 * baseline and time_s - last >= 0.03:
            strength = max(levels[index : index + 8])
            confidence = min(1.0, strength / max(gate * 4, 2 * baseline))
            found.append(Onset(time_s, band, strength, confidence))
            last = time_s
        baseline = max(level, baseline * 0.9)
    return found


def detect_onsets(stem_path: str | Path) -> list[Onset]:
    """Find attacks on a 1 ms grid in kick, snare, and hat bands of a drum stem."""
    rate = 48000
    pcm = _read_mono(stem_path, rate)
    found = []
    for band, (low, high) in _BANDS.items():
        found.extend(_envelope_onsets(_envelope(pcm, low, high, rate, 48), band, 0.001))
    return sorted(found, key=lambda onset: (onset.time_s, onset.band))


def _nonnegative(value: float, name: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise MCPVideoError(f"{name} must be finite and nonnegative", code="invalid_parameter")
    return value


def _validate_confidence(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
        or not math.isfinite(value)
    ):
        raise MCPVideoError("Confidence must be a finite number between 0 and 1", code="invalid_parameter")


def _movement_bounds(original: float, budget_ms: float) -> tuple[float, float]:
    """Keep decimal millisecond boundaries inclusive without expanding a zero budget."""
    if not budget_ms:
        return original, original
    start = Decimal(str(float(original)))
    budget = Decimal(str(float(budget_ms))).scaleb(-3)
    return max(0.0, float(start - budget)), float(start + budget)


def _closest_onset(time_s, times, best_at):
    index = bisect_left(times, time_s)
    candidates = times[max(0, index - 1) : index + 1]
    if not candidates:
        return None
    if len(candidates) == 2 and math.isclose(time_s - candidates[0], candidates[1] - time_s, abs_tol=1e-12):
        return best_at[candidates[0]]
    return best_at[min(candidates, key=lambda time: abs(time - time_s))]


def pocket_lock(events, onsets, *, band="hat", max_window_ms=25.0, min_confidence=0.35, fine_grid_step_ms=None):
    """Copy events and return placement decisions; equal-distance matches favor earlier hits."""
    _nonnegative(max_window_ms, "max_window_ms")
    _validate_confidence(min_confidence)
    if fine_grid_step_ms is not None and not _nonnegative(fine_grid_step_ms, "fine_grid_step_ms"):
        raise MCPVideoError("fine_grid_step_ms must be positive", code="invalid_parameter")
    step = None if fine_grid_step_ms is None else fine_grid_step_ms / 1000
    best_at = {}
    for onset in onsets:
        _validate_confidence(onset.confidence)
        if onset.band == band and onset.confidence >= min_confidence:
            previous = best_at.get(onset.time_s)
            if previous is None or (onset.confidence, onset.strength) > (previous.confidence, previous.strength):
                best_at[_nonnegative(onset.time_s, "onset time_s")] = onset
    times = sorted(best_at)
    placed, decisions, unmatched = [], [], []
    for index, event in enumerate(events):
        original = _nonnegative(event["time_s"], "event time_s")
        lower, upper = _movement_bounds(original, max_window_ms)
        onset = _closest_onset(original, times, best_at) if not event.get("fixed", False) else None
        final = original
        if onset is not None and lower <= onset.time_s <= upper:
            final = onset.time_s
            if step:
                quantized = round(final / step) * step
                if lower <= quantized <= upper:
                    final = quantized
        else:
            onset = None
            unmatched.append(index)
        placed.append(dict(event, time_s=final))
        decisions.append(
            {
                "original_time_s": original,
                "final_time_s": final,
                "matched_onset_s": None if onset is None else onset.time_s,
                "confidence": None if onset is None else onset.confidence,
                "moved": final != original,
            }
        )
    return placed, {"events": decisions, "unmatched_events": unmatched}
