"""Sample-domain alignment, low-band polarity checking, and peak-safe mixing."""

from __future__ import annotations

import math
import sys
import wave
from array import array
from collections.abc import Sequence
from pathlib import Path

from ..errors import MCPVideoError
from ..publication import atomic_output, open_staged_writer
from .onsets import _biquad, _read_mono

_LOW_BAND_TAIL_S = 0.05


def detect_sample_onset(samples: Sequence[float]) -> int | None:
    """Return the first sample at or above -60 dB relative to the layer peak, or None for silence."""
    peak = max((abs(sample) for sample in samples), default=0.0)
    threshold = max(peak * 0.001, 1e-7)
    return next((index for index, sample in enumerate(samples) if abs(sample) >= threshold), None)


def _mix_layers(layers, rate: int, check_polarity: bool):
    """Compare low-band energy over the full mix and the 250 Hz filter's decay."""
    aligned_layers = []
    for layer in layers:
        samples = _read_mono(layer, rate)
        onset = detect_sample_onset(samples)
        if onset is None:
            raise MCPVideoError("A stack layer has no detectable onset", code="silent_stack_layer")
        aligned_layers.append((layer, onset, samples[onset:]))
    duration = max(len(samples) for _, _, samples in aligned_layers)
    analysis_length = duration + math.ceil(rate * _LOW_BAND_TAIL_S)
    mixed = array("d")
    low_sum = array("d", [0.0]) * analysis_length if check_polarity else array("d")
    decisions = []
    for layer, onset, aligned in aligned_layers:
        inverted = False
        if check_polarity:
            padded = aligned + array("f", [0.0]) * (analysis_length - len(aligned))
            low = _biquad(_biquad(padded, rate, 250), rate, 250)
            inverted = math.fsum(prior * sample for prior, sample in zip(low_sum, low, strict=True)) < 0
            _accumulate(low_sum, low, -1 if inverted else 1)
        _accumulate(mixed, aligned, -1 if inverted else 1)
        decisions.append(
            {"source": str(layer), "onset_sample": onset, "offset_samples": -onset, "polarity_inverted": inverted}
        )
    return mixed, decisions


def _accumulate(target: array, samples: array, polarity: int) -> None:
    overlap = min(len(samples), len(target))
    for index in range(overlap):
        target[index] += polarity * samples[index]
    target.extend(polarity * samples[index] for index in range(overlap, len(samples)))


def _write_wav(path: Path, samples: array, rate: int, gain: float, ceiling: float) -> None:
    with atomic_output(str(path)) as stage, open_staged_writer(stage) as fd, wave.open(fd, "wb") as stream:
        stream.setparams((1, 2, rate, len(samples), "NONE", "not compressed"))
        max_positive = min(32767, math.floor(32768 * ceiling))
        max_negative = math.floor(32768 * ceiling)
        for start in range(0, len(samples), 32768):
            pcm = array(
                "h",
                (
                    max(-max_negative, min(max_positive, round(value * gain * 32768)))
                    for value in samples[start : start + 32768]
                ),
            )
            if sys.byteorder == "big":
                pcm.byteswap()
            stream.writeframesraw(pcm.tobytes())


def align_hit_stack(
    layers, output_path, *, sample_rate=48000, check_polarity=True, peak_limit_db=-0.5, on_clip="attenuate"
):
    """Trim leading room to align dry mono hits to sample zero, then publish a 16-bit WAV."""
    paths = list(layers)
    output = Path(output_path).absolute()
    if (
        not paths
        or type(sample_rate) is not int
        or not 1000 <= sample_rate <= 384000
        or output.suffix.lower() != ".wav"
        or not math.isfinite(peak_limit_db)
        or peak_limit_db > 0
        or on_clip not in ("attenuate", "fail")
    ):
        raise MCPVideoError(
            "Invalid hit stack layers, sample rate, WAV output, or peak policy", code="invalid_parameter"
        )
    mixed, decisions = _mix_layers(paths, sample_rate, check_polarity)
    peak = max(map(abs, mixed))
    peak_db = 20 * math.log10(peak) if peak else None
    gain_db = min(0.0, peak_limit_db - peak_db) if peak_db is not None else 0.0
    if gain_db < 0 and on_clip == "fail":
        raise MCPVideoError(
            f"Combined peak {peak_db:.2f} dBFS exceeds {peak_limit_db:.2f} dBFS", code="hit_stack_peak_limit"
        )
    _write_wav(output, mixed, sample_rate, 10 ** (gain_db / 20), 10 ** (peak_limit_db / 20))
    return {
        "output_path": str(output),
        "sample_rate": sample_rate,
        "layers": decisions,
        "combined_peak_dbfs": peak_db,
        "applied_gain_db": gain_db,
    }
