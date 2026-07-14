"""Deterministic synthetic audio fixtures and measurement helpers for tests.

This module generates reproducible WAV fixtures (tones, noise floors, sibilant
bursts, exponential-decay impulse responses) and provides bounded measurement
helpers (loudness, true-peak, band energy, spectral centroid, reverb tail).

Everything is deterministic: the same seed always produces the same bytes.

Nothing in this module imports from ``kinocut.*`` runtime.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import wave
from collections.abc import Sequence
from pathlib import Path

# numpy is a declared project dependency and is imported lazily so that
# runtime adapter modules do not pay the import cost.
import numpy as np

# --- Canonical sample format for fixtures ---

FIXTURE_SAMPLE_RATE_HZ: int = 44100
FIXTURE_CHANNEL_COUNT: int = 1

# --- Numeric envelopes ---
# TODO(controller): these post-chain envelopes are local to the fixture and
# measurement surface. When the controller centralizes post defaults, these
# should move alongside kinocut_sound.defaults / limits.
MIN_INTENSITY_PCT: float = 0.0
MAX_INTENSITY_PCT: float = 100.0


def _seed_from(*parts: str) -> int:
    """Derive a deterministic integer seed from bounded string parts."""

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")


def write_wav(
    path: str | Path,
    samples: np.ndarray,
    sample_rate_hz: int = FIXTURE_SAMPLE_RATE_HZ,
) -> Path:
    """Write a mono float64 array in ``[-1, 1]`` as a 16-bit PCM WAV."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clamped = np.clip(samples, -1.0, 1.0)
    pcm = (clamped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(pcm.tobytes())
    return path


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a mono PCM WAV into a float64 array plus its sample rate."""

    try:
        with wave.open(str(path), "rb") as wav:
            n_channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            sampwidth = wav.getsampwidth()
            raw = wav.readframes(wav.getnframes())
    except wave.Error as exc:
        if "unknown format: 65534" not in str(exc):
            raise
        return _read_wave_extensible(path)
    if sampwidth == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width: {sampwidth}")
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return data, sample_rate


def _read_wave_extensible(path: str | Path) -> tuple[np.ndarray, int]:
    """Read PCM WAVE_FORMAT_EXTENSIBLE on Python versions before 3.12."""
    from scipy.io import wavfile

    sample_rate, raw = wavfile.read(path)
    data = np.asarray(raw)
    if np.issubdtype(data.dtype, np.integer):
        scale = float(max(abs(np.iinfo(data.dtype).min), np.iinfo(data.dtype).max))
        data = data.astype(np.float64) / scale
    else:
        data = data.astype(np.float64)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, int(sample_rate)


def synthetic_clip(
    path: str | Path,
    *,
    duration_s: float = 2.0,
    sample_rate_hz: int = FIXTURE_SAMPLE_RATE_HZ,
    seed: int = 1337,
    frequencies: Sequence[float] = (110.0, 440.0, 2000.0, 6000.0, 9000.0),
    noise_floor_amplitude: float = 0.015,
) -> Path:
    """Generate a deterministic multi-tone clip with a noise floor.

    The clip carries energy in several frequency bands so EQ and de-ess tests
    can measure band-specific changes, a noise floor for denoise, and a smooth
    envelope to avoid click artefacts.
    """

    n = int(duration_s * sample_rate_hz)
    t = np.arange(n, dtype=np.float64) / sample_rate_hz
    rng = np.random.default_rng(seed)
    signal = np.zeros(n, dtype=np.float64)
    for freq in frequencies:
        signal += 0.12 * np.sin(2.0 * np.pi * freq * t)
    signal += noise_floor_amplitude * rng.standard_normal(n)
    # Smooth fade in/out (10 ms) to avoid clicks.
    fade = int(0.01 * sample_rate_hz)
    if fade > 0 and n > 2 * fade:
        envelope = np.ones(n)
        envelope[:fade] = np.linspace(0.0, 1.0, fade, endpoint=False)
        envelope[-fade:] = np.linspace(1.0, 0.0, fade, endpoint=True)
        signal *= envelope
    # Normalize to a safe peak (~-14 dBFS).
    peak = float(np.max(np.abs(signal)))
    if peak > 0.0:
        signal = signal * (0.2 / peak)
    return write_wav(path, signal, sample_rate_hz)


def synthetic_ir(
    path: str | Path,
    *,
    preset: str,
    sample_rate_hz: int = FIXTURE_SAMPLE_RATE_HZ,
    duration_s: float | None = None,
    seed: int | None = None,
) -> Path:
    """Generate a deterministic synthetic impulse response for a room preset.

    Each preset is an exponentially decaying noise burst with preset-specific
    decay time and HF damping. The result is a valid convolution IR that
    produces measurable reverberation when convolved with a dry signal.
    """

    _PRESETS = {
        "close": {"rt60_s": 0.08, "hf_damp_hz": 18000.0, "gain": 0.8},
        "small_room": {"rt60_s": 0.35, "hf_damp_hz": 9000.0, "gain": 0.55},
        "hall": {"rt60_s": 1.8, "hf_damp_hz": 4500.0, "gain": 0.40},
        "outdoor": {"rt60_s": 0.12, "hf_damp_hz": 3500.0, "gain": 0.35},
    }
    if preset not in _PRESETS:
        raise ValueError(f"unknown IR preset: {preset}")
    spec = _PRESETS[preset]
    rt60 = spec["rt60_s"] if duration_s is None else duration_s
    # Make the IR long enough to capture the decay tail.
    ir_duration = max(rt60 * 1.5, 0.15)
    n = int(ir_duration * sample_rate_hz)
    if seed is None:
        seed = _seed_from(preset)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n)
    # Exponential decay envelope from the RT60.
    decay = np.exp(-6.907755278982137 * np.arange(n) / (rt60 * sample_rate_hz))
    ir = noise * decay * spec["gain"]
    # Simple one-pole HF damping (low-pass) via cumulative moving average on HF.
    damp_hz = spec["hf_damp_hz"]
    if damp_hz < sample_rate_hz / 2.0:
        alpha = 2.0 * np.pi * damp_hz / sample_rate_hz
        smooth = 1.0 - np.exp(-alpha)
        filtered = np.zeros(n)
        prev = 0.0
        for i in range(n):
            prev = prev + smooth * (ir[i] - prev)
            filtered[i] = prev
        ir = filtered
    # Unit impulse at t=0 for the direct sound.
    ir[0] = 1.0 * spec["gain"]
    peak = float(np.max(np.abs(ir)))
    if peak > 0.0:
        ir = ir / peak
    return write_wav(path, ir, sample_rate_hz)


def synthetic_transient_clip(
    path: str | Path,
    *,
    duration_s: float = 3.0,
    burst_s: float = 0.3,
    sample_rate_hz: int = FIXTURE_SAMPLE_RATE_HZ,
    seed: int = 42,
    frequencies: Sequence[float] = (440.0, 2000.0, 6000.0),
) -> Path:
    """Generate a transient burst followed by silence for reverb testing.

    The signal has energy in the first ``burst_s`` seconds, then near-silence.
    A reverberant version will fill the silent tail with reverb decay energy.
    """

    n = int(duration_s * sample_rate_hz)
    burst_n = int(burst_s * sample_rate_hz)
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float64) / sample_rate_hz
    signal = np.zeros(n, dtype=np.float64)
    for freq in frequencies:
        signal[:burst_n] += 0.2 * np.sin(2.0 * np.pi * freq * t[:burst_n])
    signal[:burst_n] += 0.03 * rng.standard_normal(burst_n)
    # Apply a fast decay at the burst boundary to create a transient.
    decay_len = int(0.05 * sample_rate_hz)
    if burst_n > decay_len:
        signal[burst_n - decay_len : burst_n] *= np.linspace(1.0, 0.0, decay_len)
    # Normalize burst region.
    peak = float(np.max(np.abs(signal)))
    if peak > 0.0:
        signal = signal * (0.3 / peak)
    return write_wav(path, signal, sample_rate_hz)


def synthetic_dynamic_clip(
    path: str | Path,
    *,
    duration_s: float = 4.0,
    sample_rate_hz: int = FIXTURE_SAMPLE_RATE_HZ,
    seed: int = 99,
    frequencies: Sequence[float] = (220.0, 1000.0, 4000.0),
) -> Path:
    """Generate an amplitude-modulated clip with high LRA for compressor testing.

    The signal alternates between loud and quiet segments, creating a wide
    loudness range that dynamic compression should reduce.
    """

    n = int(duration_s * sample_rate_hz)
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float64) / sample_rate_hz
    signal = np.zeros(n, dtype=np.float64)
    for freq in frequencies:
        signal += 0.15 * np.sin(2.0 * np.pi * freq * t)
    signal += 0.01 * rng.standard_normal(n)
    # Create alternating loud/quiet segments.
    segment_len = int(0.5 * sample_rate_hz)
    gain_envelope = np.ones(n)
    for i in range(0, n, segment_len):
        segment_idx = i // segment_len
        end = min(i + segment_len, n)
        if segment_idx % 2 == 0:
            gain_envelope[i:end] = 1.0
        else:
            gain_envelope[i:end] = 0.15  # ~-16 dB quieter
    # Smooth the segment transitions.
    smooth_len = int(0.02 * sample_rate_hz)
    if smooth_len > 0:
        kernel = np.ones(smooth_len) / smooth_len
        gain_envelope = np.convolve(gain_envelope, kernel, mode="same")
    signal *= gain_envelope
    peak = float(np.max(np.abs(signal)))
    if peak > 0.0:
        signal = signal * (0.25 / peak)
    return write_wav(path, signal, sample_rate_hz)


def _ffmpeg_query_stderr(args: list[str], *, timeout: float = 15.0) -> str:
    """Run an ffmpeg measurement query and return its stderr (log output)."""

    import shutil

    binary_path = shutil.which("ffmpeg")
    if binary_path is None:
        raise RuntimeError("ffmpeg binary is not installed")
    cmd = [binary_path, "-hide_banner", "-nostdin", *args]
    try:
        proc = subprocess.run(  # noqa: S603 - measurement query list
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("measurement query timed out") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"measurement query failed: rc={proc.returncode}")
    return proc.stderr


def measure_loudness(path: str | Path) -> dict[str, float]:
    """Measure integrated loudness, LRA, and true-peak via ffmpeg ebur128."""

    log = _ffmpeg_query_stderr(
        [
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
    )
    integrated = _parse_ebur128_value(log, "I:")
    lra = _parse_ebur128_value(log, "LRA:")
    peak = _parse_ebur128_value(log, "Peak:")
    return {
        "integrated_lufs": integrated,
        "lra_lu": lra,
        "true_peak_dbfs": peak,
    }


def _parse_ebur128_value(log: str, label: str) -> float:
    """Parse the last numeric occurrence following ``label`` from ebur128 log."""

    pattern = re.compile(re.escape(label) + r"\s+(-?\d+(?:\.\d+)?)")
    matches = pattern.findall(log)
    if not matches:
        return float("nan")
    return float(matches[-1])


def measure_true_peak_dbtp(path: str | Path) -> float:
    """Measure the true-peak in dBTP via ffmpeg ebur128 (Peak: line)."""

    return measure_loudness(path)["true_peak_dbfs"]


def _band_rms_numpy(
    data: np.ndarray,
    sample_rate_hz: int,
    *,
    lo_hz: float,
    hi_hz: float,
) -> float:
    """Compute the in-band RMS level in dBFS via numpy FFT."""

    n = len(data)
    if n == 0:
        return float("-inf")
    spectrum = np.fft.rfft(data.astype(np.float64))
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    magnitude = np.abs(spectrum) / n * 2.0
    band_mask = (freqs >= lo_hz) & (freqs <= hi_hz)
    band_power = float(np.sum(magnitude[band_mask] ** 2))
    if band_power <= 0.0:
        return float("-inf")
    return float(10.0 * np.log10(band_power))


def measure_band_energy(
    path: str | Path,
    *,
    lo_hz: float,
    hi_hz: float,
) -> float:
    """Measure the total RMS energy in ``[lo_hz, hi_hz]`` in dBFS via numpy FFT."""

    data, sample_rate = read_wav(path)
    return _band_rms_numpy(data, sample_rate, lo_hz=lo_hz, hi_hz=hi_hz)


def measure_rms(path: str | Path) -> float:
    """Measure overall RMS level in dBFS via numpy."""

    data, _ = read_wav(path)
    if len(data) == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(data**2)))
    if rms <= 0.0:
        return float("-inf")
    return float(20.0 * np.log10(rms))


def measure_hf_energy(path: str | Path, *, crossover_hz: float = 5000.0) -> float:
    """Measure RMS energy above ``crossover_hz`` via numpy FFT."""

    data, sample_rate = read_wav(path)
    nyquist = sample_rate / 2.0
    return _band_rms_numpy(
        data,
        sample_rate,
        lo_hz=crossover_hz,
        hi_hz=nyquist,
    )


def measure_reverb_tail_energy(path: str | Path) -> float:
    """Measure the total energy in the tail region of the signal.

    A reverberant signal has more energy in its decay tail than a dry signal.
    We measure the RMS of the last 30% of the clip as a reverberation proxy.
    """

    data, _ = read_wav(path)
    n = len(data)
    if n < 10:
        return 0.0
    tail_start = int(n * 0.7)
    tail = data[tail_start:]
    rms = float(np.sqrt(np.mean(tail**2)))
    return rms


def measure_rms_variation_db(
    path: str | Path,
    *,
    window_ms: float = 200.0,
    sample_rate_hz: int | None = None,
) -> float:
    """Measure the dB range of short-window RMS levels (LRA proxy).

    Splits the signal into ``window_ms`` windows, computes RMS of each, and
    returns ``max(window_rms_db) - min(window_rms_db)``. A dynamic-range
    compressor should reduce this value. This is more reliable than ebur128
    LRA for short synthetic clips.
    """

    data, rate = read_wav(path) if sample_rate_hz is None else (read_wav(path)[0], sample_rate_hz)
    n = len(data)
    win_len = max(1, int(window_ms / 1000.0 * rate))
    if n < win_len:
        return 0.0
    n_windows = n // win_len
    trimmed = data[: n_windows * win_len]
    windows = trimmed.reshape(n_windows, win_len)
    rms_per_window = np.sqrt(np.mean(windows**2, axis=1))
    # Filter out near-silent windows.
    audible = rms_per_window[rms_per_window > 1e-8]
    if len(audible) < 2:
        return 0.0
    rms_db = 20.0 * np.log10(audible)
    return float(np.max(rms_db) - np.min(rms_db))


def sha256_of_file(path: str | Path) -> str:
    """Return ``sha256:<hex>`` of a file's bytes."""

    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


__all__ = [
    "FIXTURE_CHANNEL_COUNT",
    "FIXTURE_SAMPLE_RATE_HZ",
    "MAX_INTENSITY_PCT",
    "MIN_INTENSITY_PCT",
    "measure_band_energy",
    "measure_hf_energy",
    "measure_loudness",
    "measure_reverb_tail_energy",
    "measure_rms",
    "measure_rms_variation_db",
    "measure_true_peak_dbtp",
    "read_wav",
    "sha256_of_file",
    "synthetic_clip",
    "synthetic_dynamic_clip",
    "synthetic_ir",
    "synthetic_transient_clip",
    "write_wav",
]
