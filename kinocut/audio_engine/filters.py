"""Filter, delay, reverb and tone DSP for the audio engine (numpy path).

These were split out of :mod:`core` so each module stays under the project's
size limit; :mod:`core` re-exports them.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kinocut.errors import MCPVideoError
from kinocut.validation_errors import rejected_value

DEFAULT_SAMPLE_RATE = 44100


def _require_cutoff(cutoff: Any, sample_rate: int) -> float:
    """A filter cutoff must be a real frequency below Nyquist."""
    try:
        value = float(cutoff)
    except (TypeError, ValueError):
        value = math.nan
    nyquist = sample_rate / 2.0
    if not (0.0 < value < nyquist):
        raise MCPVideoError(
            f"Filter cutoff must be greater than 0 and below the Nyquist frequency ({nyquist:g} Hz), "
            f"got {rejected_value(cutoff)}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return value


def _one_pole_lowpass(samples: np.ndarray, cutoff: float, sample_rate: int) -> np.ndarray:
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / sample_rate
    alpha = dt / (rc + dt)
    result = np.zeros_like(samples)
    result[0] = samples[0]
    for i in range(1, len(samples)):
        result[i] = result[i - 1] + alpha * (samples[i] - result[i - 1])
    return result


def apply_lowpass(
    samples: np.ndarray,
    cutoff: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Butterworth lowpass filter (2-pole); single-pole RC without scipy."""
    cutoff = _require_cutoff(cutoff, sample_rate)
    try:
        from scipy import signal
    except ImportError:
        return _one_pole_lowpass(samples, cutoff, sample_rate)
    sos = signal.butter(2, cutoff, btype="low", fs=sample_rate, output="sos")
    return signal.sosfiltfilt(sos, samples)


def apply_highpass(
    samples: np.ndarray,
    cutoff: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Butterworth highpass filter (2-pole); single-pole RC without scipy."""
    cutoff = _require_cutoff(cutoff, sample_rate)
    try:
        from scipy import signal
    except ImportError:
        rc = 1.0 / (2.0 * math.pi * cutoff)
        dt = 1.0 / sample_rate
        alpha = rc / (rc + dt)
        result = np.zeros_like(samples)
        result[0] = samples[0]
        for i in range(1, len(samples)):
            result[i] = alpha * (result[i - 1] + samples[i] - samples[i - 1])
        return result
    sos = signal.butter(2, cutoff, btype="high", fs=sample_rate, output="sos")
    return signal.sosfiltfilt(sos, samples)


def _block_feedback(samples: np.ndarray, delay: int, step: Any) -> np.ndarray:
    """Run a recursion whose feedback is exactly ``delay`` samples behind, a block at a time.

    Inside any block of ``delay`` samples every delayed value comes from the
    previous block, so ``step(x_block, state_prev) -> (y_block, state)`` can
    be whole-array arithmetic. That keeps these effects O(n) in numpy with
    no per-sample Python loop and no scipy.
    """
    n = len(samples)
    if n == 0:
        return samples
    x = np.zeros(((n + delay - 1) // delay) * delay, dtype=np.float64)
    x[:n] = samples
    out = np.zeros_like(x)
    state = np.zeros(delay)
    for start in range(0, x.size, delay):
        block = x[start : start + delay]
        out[start : start + delay], state = step(block, state)
    return out[:n]


def _comb_step(gain: float, damp: float) -> Any:
    """Freeverb comb: ``y = x + g*s[n-d]``, ``s = (1-damp)*y + damp*s[n-d]``."""

    def step(block: np.ndarray, state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        y = block + gain * state
        return y, (1.0 - damp) * y + damp * state

    return step


@staticmethod
def _allpass_step(block: np.ndarray, state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Schroeder all-pass: ``y = s[n-d] - 0.5*x``, ``s = x + 0.5*s[n-d]``."""
    return state - 0.5 * block, block + 0.5 * state


def apply_reverb(
    samples: np.ndarray,
    room_size: float = 0.5,
    damping: float = 0.5,
    wet_level: float = 0.2,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Freeverb-style reverb: 8 comb filters + 4 all-pass filters.

    Each stage is the classic feedback delay line, processed block-wise so
    the result matches the per-sample loop it replaces.
    """
    wet = np.zeros(len(samples), dtype=np.float64)
    # Comb filter delays (in samples) — classic Freeverb values scaled by room_size
    comb_delays = [1557, 1617, 1491, 1422, 1277, 1356, 1188, 1116]
    for delay in comb_delays:
        d = max(1, int(delay * (0.5 + room_size)))
        wet += _block_feedback(samples, d, _comb_step(0.84 * room_size, damping))
    wet /= 8.0

    for delay in (225, 556, 441, 341):
        wet = _block_feedback(wet, delay, _allpass_step)

    # Mix wet and dry
    return samples * (1.0 - wet_level) + wet * wet_level


def apply_delay(
    samples: np.ndarray,
    delay_time: float = 0.3,
    feedback: float = 0.4,
    mix: float = 0.3,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """Delay line with feedback: ``s[n] = x[n] + f*s[n-d]``, ``y[n] = s[n-d]``."""
    delay_samp = max(1, int(delay_time * sample_rate))

    def step(block: np.ndarray, state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return state, block + feedback * state

    wet = _block_feedback(samples, delay_samp, step)
    return samples * (1.0 - mix) + wet * mix


def apply_tone(
    samples: np.ndarray,
    tone: float = 0.5,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """One-pole low-pass tilt: ``tone`` 0 rolls off from 500 Hz, 1 from 12 kHz."""
    x = np.asarray(samples, dtype=np.float64)
    if x.size == 0:
        return x
    cutoff = 500.0 * (12000.0 / 500.0) ** min(max(float(tone), 0.0), 1.0)
    cutoff = min(cutoff, sample_rate / 2.0 * 0.95)
    try:
        from scipy import signal

        alpha = (2.0 * math.pi * cutoff / sample_rate) / (2.0 * math.pi * cutoff / sample_rate + 1.0)
        return signal.lfilter([alpha], [1.0, -(1.0 - alpha)], x)
    except ImportError:
        spectrum = np.fft.rfft(x)
        freqs = np.fft.rfftfreq(x.size, 1.0 / sample_rate)
        return np.fft.irfft(spectrum / np.sqrt(1.0 + (freqs / cutoff) ** 2), n=x.size)
