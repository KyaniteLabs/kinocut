"""Audio synthesis and sound design engine.

NumPy-based professional DSP with band-limited waveforms, high-quality effects,
and stereo support. Falls back to pure-Python legacy implementation if numpy
is not available.
"""

from __future__ import annotations

import math
import wave

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _atomic_output, _open_staged_writer
from kinocut.validation_errors import rejected_value

# ---------------------------------------------------------------------------
# Optional numpy import with graceful fallback
# ---------------------------------------------------------------------------
try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False

# ---------------------------------------------------------------------------
# Audio Constants
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit


# ---------------------------------------------------------------------------
# Fallback re-export if numpy unavailable
# ---------------------------------------------------------------------------
if not _HAS_NUMPY:
    from ._legacy_core import (  # type: ignore[no-redef]
        apply_envelope,
        apply_fade,
        apply_chorus,
        apply_compressor,
        apply_delay,
        apply_distortion,
        apply_eq,
        apply_flanger,
        apply_highpass,
        apply_lowpass,
        apply_pan,
        apply_reverb,
        apply_tremolo,
        apply_vibrato,
        apply_width,
        generate_colored_noise,
        generate_fm,
        generate_noise,
        generate_pluck,
        generate_pulse,
        generate_sawtooth,
        generate_sine,
        generate_square,
        generate_supersaw,
        generate_triangle,
        write_wav,
        _float_to_pcm,
        _pcm_to_float,
    )

    __all__ = [
        "_float_to_pcm",
        "_pcm_to_float",
        "apply_chorus",
        "apply_compressor",
        "apply_delay",
        "apply_distortion",
        "apply_envelope",
        "apply_eq",
        "apply_fade",
        "apply_flanger",
        "apply_highpass",
        "apply_lowpass",
        "apply_pan",
        "apply_reverb",
        "apply_tremolo",
        "apply_vibrato",
        "apply_width",
        "generate_colored_noise",
        "generate_fm",
        "generate_noise",
        "generate_pluck",
        "generate_pulse",
        "generate_sawtooth",
        "generate_sine",
        "generate_square",
        "generate_supersaw",
        "generate_triangle",
        "write_wav",
    ]
else:
    # =====================================================================
    # NumPy-based Professional DSP
    # =====================================================================

    # Filters, delays, reverb and the tone tilt live in their own module; they
    # are re-exported here so every existing ``core`` import keeps working.
    from .filters import (
        apply_delay,
        apply_highpass,
        apply_lowpass,
        apply_reverb,
        apply_tone,
    )

    # -----------------------------------------------------------------------
    # Waveform Generation
    # -----------------------------------------------------------------------

    def _polyblep(t: np.ndarray, dt: float) -> np.ndarray:
        """Polynomial band-limited step (polyBLEP) for anti-aliasing."""
        result = np.zeros_like(t)
        # Left side of discontinuity
        mask1 = (t < dt) & (t > -dt)
        x1 = t[mask1] / dt
        result[mask1] = x1 * x1 + x1 * 2.0 + 1.0
        # Right side of discontinuity
        mask2 = (t < 1.0 + dt) & (t > 1.0 - dt)
        x2 = (t[mask2] - 1.0) / dt
        result[mask2] = -x2 * x2 + x2 * 2.0 - 1.0
        return result

    def generate_sine(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
    ) -> bytes:
        """Generate a sine wave."""
        t = np.arange(int(sample_rate * duration)) / sample_rate
        samples = amplitude * np.sin(2.0 * np.pi * frequency * t)
        return _float_to_pcm(samples)

    def generate_square(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
    ) -> bytes:
        """Generate a band-limited square wave using polyBLEP."""
        n_samples = int(sample_rate * duration)
        t = np.arange(n_samples) / sample_rate
        phase = (t * frequency) % 1.0
        dt = frequency / sample_rate
        # Naive square
        samples = np.where(phase < 0.5, 1.0, -1.0).astype(np.float64)
        # Apply polyBLEP at rising and falling edges
        samples += _polyblep(phase, dt)
        samples -= _polyblep((phase + 0.5) % 1.0, dt)
        return _float_to_pcm(samples * amplitude)

    def generate_pulse(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
        width: float = 0.25,
    ) -> bytes:
        """Generate a band-limited pulse wave using polyBLEP."""
        n_samples = int(sample_rate * duration)
        t = np.arange(n_samples) / sample_rate
        phase = (t * frequency) % 1.0
        dt = frequency / sample_rate
        samples = np.where(phase < width, 1.0, -1.0).astype(np.float64)
        samples += _polyblep(phase, dt)
        samples -= _polyblep((phase + width) % 1.0, dt)
        return _float_to_pcm(samples * amplitude)

    def generate_sawtooth(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
    ) -> bytes:
        """Generate a band-limited sawtooth wave using polyBLEP."""
        n_samples = int(sample_rate * duration)
        t = np.arange(n_samples) / sample_rate
        phase = (t * frequency) % 1.0
        dt = frequency / sample_rate
        samples = 2.0 * phase - 1.0
        samples -= _polyblep(phase, dt)
        return _float_to_pcm(samples * amplitude)

    def generate_triangle(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
    ) -> bytes:
        """Generate a band-limited triangle wave (integrated square)."""
        n_samples = int(sample_rate * duration)
        # Generate band-limited square then integrate
        square_pcm = generate_square(frequency, duration, sample_rate, 1.0)
        square_float = np.array(_pcm_to_float(square_pcm), dtype=np.float64)
        # Leaky integration to avoid DC drift: y[i] = leak*y[i-1] + x[i]
        leak = 0.995
        triangle = np.zeros(n_samples, dtype=np.float64)
        if n_samples > 0:
            triangle[0] = square_float[0]
            if n_samples > 1:
                try:
                    from scipy import signal

                    triangle = signal.lfilter([1.0], [1.0, -leak], square_float)
                except ImportError:
                    for i in range(1, n_samples):
                        triangle[i] = leak * triangle[i - 1] + square_float[i]
        # Normalize and remove DC
        triangle -= np.mean(triangle)
        max_val = np.max(np.abs(triangle))
        if max_val > 0:
            triangle /= max_val
        return _float_to_pcm(triangle * amplitude)

    def generate_supersaw(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
        detune: float = 0.02,
        voices: int = 7,
    ) -> bytes:
        """Generate a supersaw — detuned sawtooth voices with stereo spread."""
        n_samples = int(sample_rate * duration)
        t = np.arange(n_samples) / sample_rate
        samples = np.zeros(n_samples, dtype=np.float64)
        for i in range(voices):
            # Detune spread: center voice at 1.0, others +/-
            spread = (i - (voices - 1) / 2.0) / ((voices - 1) / 2.0) if voices > 1 else 0.0
            freq = frequency * (1.0 + spread * detune)
            phase = (t * freq) % 1.0
            dt = freq / sample_rate
            saw = 2.0 * phase - 1.0
            saw -= _polyblep(phase, dt)
            # Amplitude weighting: center louder
            weight = 1.0 - abs(spread) * 0.3
            samples += saw * weight
        samples /= np.max(np.abs(samples)) if np.max(np.abs(samples)) > 0 else 1.0
        return _float_to_pcm(samples * amplitude)

    def generate_colored_noise(
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.3,
        color: str = "white",
    ) -> bytes:
        """Generate colored noise: white, pink, brown, blue."""
        n_samples = int(sample_rate * duration)
        white = np.random.uniform(-1.0, 1.0, n_samples)

        if color == "white":
            samples = white
        elif color == "pink":
            # Voss-McCartney algorithm approximation
            samples = np.zeros(n_samples, dtype=np.float64)
            num_rows = 16
            rows = np.random.uniform(-1.0, 1.0, num_rows)
            for i in range(n_samples):
                samples[i] = sum(rows)
                # Update random row
                idx = int(np.random.randint(0, num_rows))
                rows[idx] = np.random.uniform(-1.0, 1.0)
            samples /= np.std(samples) if np.std(samples) > 0 else 1.0
        elif color == "brown":
            # Brown noise = integrated white noise
            samples = np.cumsum(white)
            samples -= np.mean(samples)
            max_val = np.max(np.abs(samples))
            if max_val > 0:
                samples /= max_val
        elif color == "blue":
            # Blue noise = differentiated white noise
            samples = np.diff(white, prepend=white[0])
            samples /= np.max(np.abs(samples)) if np.max(np.abs(samples)) > 0 else 1.0
        else:
            samples = white

        return _float_to_pcm(samples * amplitude)

    def generate_noise(
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.3,
    ) -> bytes:
        """Generate white noise (backward compatible)."""
        return generate_colored_noise(duration, sample_rate, amplitude, color="white")

    def generate_pluck(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
        decay: float = 0.995,
    ) -> bytes:
        """Karplus-Strong string synthesis."""
        n_samples = int(sample_rate * duration)
        delay_line_len = max(1, int(sample_rate / frequency))
        delay_line = np.random.uniform(-1.0, 1.0, delay_line_len)
        samples = np.zeros(n_samples, dtype=np.float64)
        ptr = 0
        for i in range(n_samples):
            samples[i] = delay_line[ptr]
            next_ptr = (ptr + 1) % delay_line_len
            # Average with next sample (lowpass filter)
            delay_line[ptr] = decay * 0.5 * (delay_line[ptr] + delay_line[next_ptr])
            ptr = next_ptr
        # Normalize
        max_val = np.max(np.abs(samples))
        if max_val > 0:
            samples /= max_val
        return _float_to_pcm(samples * amplitude)

    def generate_fm(
        frequency: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        amplitude: float = 0.5,
        ratio: float = 2.0,
        index: float = 5.0,
    ) -> bytes:
        """2-operator FM synthesis."""
        n_samples = int(sample_rate * duration)
        t = np.arange(n_samples) / sample_rate
        carrier = 2.0 * np.pi * frequency * t
        modulator = index * np.sin(2.0 * np.pi * frequency * ratio * t)
        samples = np.sin(carrier + modulator)
        return _float_to_pcm(samples * amplitude)

    # -----------------------------------------------------------------------
    # Effects
    # -----------------------------------------------------------------------

    def apply_envelope(
        samples: np.ndarray,
        attack: float,
        decay: float,
        sustain: float,
        release: float,
        duration: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Apply ADSR envelope with exponential curves.

        Attack ramps 0 -> 1, decay 1 -> sustain, sustain holds, and release
        falls from sustain to exactly 0, so the clip does not end on a click.
        When the three stages do not fit the clip they are shortened
        proportionally instead of producing a negative-length stage.
        """
        n = len(samples)
        if n == 0:
            return samples
        env = np.ones(n, dtype=np.float64)
        # Leave room for at least one sustain sample so every stage has somewhere to land.
        budget = max(n - 1, 0)
        wanted = np.array([max(attack, 0.0), max(decay, 0.0), max(release, 0.0)]) * sample_rate
        stage_total = float(wanted.sum())
        if stage_total > budget:
            wanted = wanted * (budget / stage_total)
        a_samp, d_samp, r_samp = (int(value) for value in wanted)
        d_end = a_samp + d_samp
        s_end = max(n - r_samp, d_end)
        if a_samp > 0:
            env[:a_samp] = 1.0 - np.exp(-5.0 * np.arange(a_samp) / a_samp)
        if d_samp > 0:
            env[a_samp:d_end] = 1.0 - (1.0 - sustain) * (1.0 - np.exp(-5.0 * np.arange(d_samp) / d_samp))
        env[d_end:s_end] = sustain
        if s_end < n:
            k = np.arange(n - s_end)
            env[s_end:] = sustain * (np.exp(-5.0 * k / k[-1]) - np.exp(-5.0)) / (1.0 - np.exp(-5.0))

        return samples * env

    def apply_fade(
        samples: np.ndarray,
        fade_in: float,
        fade_out: float,
        duration: float,
        sample_rate: int,
    ) -> np.ndarray:
        """Apply fade in/out with exponential curves that reach 1 and 0 exactly.

        Overlapping fades multiply instead of the later one overwriting the earlier.
        """
        n = len(samples)
        if n == 0:
            return samples
        envelope = np.ones(n, dtype=np.float64)
        fi_samp = min(max(int(fade_in * sample_rate), 0), n)
        fo_samp = min(max(int(fade_out * sample_rate), 0), n)
        if fi_samp > 0:
            k = np.arange(fi_samp)
            envelope[:fi_samp] = (1.0 - np.exp(-5.0 * k / max(fi_samp - 1, 1))) / (1.0 - np.exp(-5.0))
        if fo_samp > 0:
            k = np.arange(fo_samp)
            envelope[-fo_samp:] *= (np.exp(-5.0 * k / max(fo_samp - 1, 1)) - np.exp(-5.0)) / (1.0 - np.exp(-5.0))

        return samples * envelope

    def apply_chorus(
        samples: np.ndarray,
        rate: float = 1.5,
        depth: float = 0.002,
        voices: int = 3,
        mix: float = 0.5,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Chorus effect using modulated delay lines."""
        n = len(samples)
        wet = np.zeros(n, dtype=np.float64)
        max_delay = int((depth + 0.005) * sample_rate)
        buffer = np.zeros(n + max_delay, dtype=np.float64)
        buffer[max_delay : max_delay + n] = samples

        for v in range(voices):
            phase_offset = v * (2.0 * math.pi / voices)
            for i in range(n):
                lfo = (
                    depth * sample_rate * 0.5 * (1.0 + math.sin(2.0 * math.pi * rate * i / sample_rate + phase_offset))
                )
                delay_idx = max_delay + i - int(lfo)
                frac = lfo - int(lfo)
                if 0 <= delay_idx < len(buffer) - 1:
                    wet[i] += buffer[delay_idx] * (1.0 - frac) + buffer[delay_idx + 1] * frac

        wet /= voices
        return samples * (1.0 - mix) + wet * mix

    def apply_flanger(
        samples: np.ndarray,
        rate: float = 0.5,
        depth: float = 0.003,
        feedback: float = 0.5,
        mix: float = 0.5,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Flanger effect using modulated delay with feedback."""
        n = len(samples)
        max_delay = int((depth + 0.002) * sample_rate)
        buffer = np.zeros(n + max_delay * 2, dtype=np.float64)
        output = np.zeros(n, dtype=np.float64)

        for i in range(n):
            lfo = depth * sample_rate * 0.5 * (1.0 + math.sin(2.0 * math.pi * rate * i / sample_rate))
            delay_idx = max_delay + i - int(lfo)
            frac = lfo - int(lfo)
            if 0 <= delay_idx < len(buffer) - 1:
                delayed = buffer[delay_idx] * (1.0 - frac) + buffer[delay_idx + 1] * frac
            else:
                delayed = 0.0
            output[i] = samples[i] + delayed * mix
            buffer[max_delay + i] = samples[i] + delayed * feedback

        return output

    def apply_distortion(
        samples: np.ndarray,
        drive: float = 0.5,
        tone: float = 0.5,
        type_: str = "soft",
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Distortion: soft clip, tube, or bit-crush, followed by the ``tone`` tilt.

        ``tone`` (0-1) sets the cutoff of a one-pole low-pass on the shaped
        signal, from 500 Hz to 12 kHz; an unknown ``type_`` is an error rather
        than a silent no-op.
        """
        if type_ == "soft":
            shaped = np.tanh(samples * (1.0 + drive * 10.0))
        elif type_ == "tube":
            # Asymmetric tube distortion
            s = samples * (1.0 + drive * 5.0)
            shaped = np.where(s >= 0, np.tanh(s), np.tanh(s * 1.5) / 1.5)
        elif type_ == "bit":
            bits = max(1, int(16 * (1.0 - drive)))
            max_val = 2.0 ** (bits - 1)
            shaped = np.round(samples * max_val) / max_val
        else:
            raise MCPVideoError(
                f"distortion type must be one of ['bit', 'soft', 'tube'], got {rejected_value(type_)}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        return apply_tone(shaped, tone, sample_rate)

    def apply_compressor(
        samples: np.ndarray,
        threshold: float = 0.5,
        ratio: float = 4.0,
        attack: float = 0.01,
        release: float = 0.1,
        makeup: float = 1.0,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """RMS compressor with attack/release envelope.

        The running RMS is a prefix sum (vectorised); only the one-pole
        envelope follower stays a per-sample loop. Attack and release are
        never shorter than one sample, so 0 no longer divides by zero.
        """
        n = len(samples)
        if n == 0:
            return samples
        # Attack/release of at least one sample (0 would raise ZeroDivisionError).
        attack = max(float(attack), 1.0 / sample_rate)
        release = max(float(release), 1.0 / sample_rate)
        attack_coef = np.exp(-1.0 / (attack * sample_rate))
        release_coef = np.exp(-1.0 / (release * sample_rate))
        envelope = np.zeros(n, dtype=np.float64)
        gain = np.ones(n, dtype=np.float64)

        # RMS over a trailing 10 ms window via prefix sums
        window = max(1, int(0.01 * sample_rate))
        idx = np.arange(n)
        start = np.maximum(0, idx - window)
        prefix = np.concatenate([[0.0], np.cumsum(np.asarray(samples, dtype=np.float64) ** 2)])
        rms = np.sqrt((prefix[idx + 1] - prefix[start]) / (idx - start + 1))

        previous = 0.0
        for i in range(n):
            coefficient = attack_coef if rms[i] > previous else release_coef
            envelope[i] = coefficient * previous + (1.0 - coefficient) * rms[i]
            previous = envelope[i]
            if envelope[i] > threshold:
                db_reduction = (np.log10(envelope[i] / threshold) * 20.0) * (1.0 - 1.0 / ratio) / 20.0
                gain[i] = 10.0 ** (-db_reduction)

        return samples * gain * makeup

    def apply_eq(
        samples: np.ndarray,
        low_gain: float = 0.0,
        mid_gain: float = 0.0,
        high_gain: float = 0.0,
        low_freq: float = 200.0,
        high_freq: float = 4000.0,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """3-band parametric EQ: low/high shelves and a mid peak one octave-band wide."""
        try:
            from scipy import signal
        except ImportError as exc:
            from .._install_hints import pip_install_hint

            raise MCPVideoError(
                f"The eq effect needs scipy. Install with: {pip_install_hint('audio-enhanced')}",
                error_type="dependency_error",
                code="missing_scipy",
                suggested_action={"auto_fix": False, "description": "Install the audio-enhanced extra."},
            ) from exc

        if not 0.0 < low_freq < high_freq < sample_rate / 2.0:
            raise MCPVideoError(
                f"low_freq and high_freq must satisfy 0 < low_freq < high_freq < {sample_rate / 2.0:g} Hz, "
                f"got {rejected_value(low_freq)} and {rejected_value(high_freq)}",
                error_type="validation_error",
                code="invalid_parameter",
            )

        result = samples.copy()
        # Low shelf
        if low_gain != 0.0:
            sos = signal.butter(1, low_freq, btype="low", fs=sample_rate, output="sos")
            low = signal.sosfiltfilt(sos, samples)
            result += low * (10.0 ** (low_gain / 20.0) - 1.0)
        # High shelf
        if high_gain != 0.0:
            sos = signal.butter(1, high_freq, btype="high", fs=sample_rate, output="sos")
            high = signal.sosfiltfilt(sos, samples)
            result += high * (10.0 ** (high_gain / 20.0) - 1.0)
        # Mid peaking: iirpeak's second argument is Q, not octave bandwidth
        if mid_gain != 0.0:
            mid_freq = (low_freq * high_freq) ** 0.5
            octaves = np.log2(high_freq / low_freq)
            bandwidth_hz = mid_freq * (2.0 ** (octaves / 2.0) - 2.0 ** (-octaves / 2.0))
            b, a = signal.iirpeak(mid_freq, mid_freq / bandwidth_hz, fs=sample_rate)
            mid = signal.filtfilt(b, a, samples)
            result += mid * (10.0 ** (mid_gain / 20.0) - 1.0)
        return result

    def apply_pan(
        samples: np.ndarray,
        pan: float = 0.0,
    ) -> np.ndarray:
        """Convert mono to stereo with constant-power panning.

        pan: -1 (full left) to 1 (full right), 0 = center.
        """
        angle = (pan + 1.0) * math.pi / 4.0
        left = samples * math.cos(angle)
        right = samples * math.sin(angle)
        return np.stack([left, right], axis=1)

    def apply_width(
        samples: np.ndarray,
        width: float = 1.0,
    ) -> np.ndarray:
        """Mid-side stereo width control.

        samples: 2D array shape (n, 2)
        width: 0 = mono, 1 = original, >1 = wider
        """
        if samples.ndim != 2 or samples.shape[1] != 2:
            return samples
        mid = (samples[:, 0] + samples[:, 1]) * 0.5
        side = (samples[:, 1] - samples[:, 0]) * 0.5
        new_side = side * width
        left = mid - new_side
        right = mid + new_side
        return np.stack([left, right], axis=1)

    def apply_tremolo(
        samples: np.ndarray,
        rate: float = 5.0,
        depth: float = 0.5,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Amplitude modulation (tremolo)."""
        t = np.arange(len(samples)) / sample_rate
        lfo = 1.0 - depth + depth * np.sin(2.0 * math.pi * rate * t)
        return samples * lfo

    def apply_vibrato(
        samples: np.ndarray,
        rate: float = 5.0,
        depth: float = 0.003,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Pitch vibrato via modulated delay line."""
        n = len(samples)
        max_delay = int((depth + 0.002) * sample_rate)
        buffer = np.zeros(n + max_delay * 2, dtype=np.float64)
        buffer[max_delay : max_delay + n] = samples
        output = np.zeros(n, dtype=np.float64)

        for i in range(n):
            lfo = depth * sample_rate * 0.5 * (1.0 + math.sin(2.0 * math.pi * rate * i / sample_rate))
            delay_idx = max_delay + i - int(lfo)
            frac = lfo - int(lfo)
            if 0 <= delay_idx < len(buffer) - 1:
                output[i] = buffer[delay_idx] * (1.0 - frac) + buffer[delay_idx + 1] * frac
            else:
                output[i] = samples[i]

        return output

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    def _float_to_pcm(samples: np.ndarray) -> bytes:
        """Convert float samples (-1 to 1) to 16-bit PCM bytes.

        Rounds instead of truncating, and maps NaN/inf to silence/full scale
        first so a NaN can never leak into the integer conversion.
        """
        finite = np.nan_to_num(np.asarray(samples, dtype=np.float64), nan=0.0, posinf=1.0, neginf=-1.0)
        clipped = np.clip(finite, -1.0, 1.0)
        int16 = np.round(clipped * 32767.0).astype(np.int16)
        return int16.tobytes()

    def _pcm_to_float(
        pcm_bytes: bytes,
        sample_width: int = DEFAULT_SAMPLE_WIDTH,
        channels: int = DEFAULT_CHANNELS,
    ) -> list[float] | np.ndarray:
        """Convert PCM bytes to mono float samples."""
        if sample_width == 2:
            dtype = np.int16
        elif sample_width == 1:
            dtype = np.uint8
        elif sample_width == 3:
            octets = np.frombuffer(pcm_bytes, dtype=np.uint8, count=len(pcm_bytes) // 3 * 3).reshape(-1, 3)
            high = octets[:, 2].view(np.int8).astype(np.int32)
            raw = ((high << 16) | (octets[:, 1].astype(np.int32) << 8) | octets[:, 0]).astype(np.float64)
            raw = raw.reshape(-1, channels) if channels > 1 else raw
            mono = raw.mean(axis=1) if channels > 1 else raw
            return mono / 8388607.0
        elif sample_width == 4:
            dtype = np.int32
        else:
            raise MCPVideoError(
                f"Unsupported PCM sample width: {sample_width}",
                error_type="validation_error",
                code="invalid_sample_width",
            )

        raw = np.frombuffer(pcm_bytes, dtype=dtype).astype(np.float64)
        if channels > 1:
            raw = raw.reshape(-1, channels)
            raw = raw.mean(axis=1)

        if sample_width == 1:
            return (raw - 128.0) / 128.0
        elif sample_width == 2:
            return raw / 32767.0
        else:
            return raw / 2147483647.0

    def write_wav(
        pcm_data: bytes,
        output_path: str,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
    ) -> str:
        """Write PCM data to a WAV file."""
        with (
            _atomic_output(output_path) as staged,
            _open_staged_writer(staged) as stream,
            wave.open(stream, "wb") as wav_file,
        ):
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(DEFAULT_SAMPLE_WIDTH)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return output_path

    __all__ = [
        "_float_to_pcm",
        "_pcm_to_float",
        "apply_chorus",
        "apply_compressor",
        "apply_delay",
        "apply_distortion",
        "apply_envelope",
        "apply_eq",
        "apply_fade",
        "apply_flanger",
        "apply_highpass",
        "apply_lowpass",
        "apply_pan",
        "apply_reverb",
        "apply_tremolo",
        "apply_vibrato",
        "apply_width",
        "generate_colored_noise",
        "generate_fm",
        "generate_noise",
        "generate_pluck",
        "generate_pulse",
        "generate_sawtooth",
        "generate_sine",
        "generate_square",
        "generate_supersaw",
        "generate_triangle",
        "write_wav",
    ]
