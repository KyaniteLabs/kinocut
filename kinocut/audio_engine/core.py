"""Audio synthesis and sound design engine.

NumPy-based professional DSP with band-limited waveforms, high-quality effects,
and stereo support. Falls back to pure-Python legacy implementation if numpy
is not available.
"""

from __future__ import annotations

import math
import wave

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_output_path

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
        # Leaky integration to avoid DC drift
        triangle = np.zeros(n_samples, dtype=np.float64)
        leak = 0.995
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
        """Apply ADSR envelope with exponential curves."""
        n = len(samples)
        env = np.ones(n, dtype=np.float64)
        a_samp = int(attack * sample_rate)
        d_samp = int(decay * sample_rate)
        r_samp = int(release * sample_rate)
        s_start = a_samp + d_samp
        s_end = n - r_samp

        if a_samp > 0:
            env[:a_samp] = 1.0 - np.exp(-5.0 * np.arange(a_samp) / a_samp)
        if d_samp > 0 and s_start <= n:
            end_idx = min(s_start + d_samp, n)
            d_len = end_idx - s_start
            env[s_start:end_idx] = 1.0 - (1.0 - sustain) * (1.0 - np.exp(-5.0 * np.arange(d_len) / d_samp))
        if s_end > s_start:
            env[s_start:s_end] = sustain
        if r_samp > 0 and s_end < n:
            r_len = n - s_end
            env[s_end:] = sustain * np.exp(-5.0 * np.arange(r_len) / r_samp)

        return samples * env

    def apply_fade(
        samples: np.ndarray,
        fade_in: float,
        fade_out: float,
        duration: float,
        sample_rate: int,
    ) -> np.ndarray:
        """Apply fade in/out with exponential curves."""
        n = len(samples)
        envelope = np.ones(n, dtype=np.float64)
        fi_samp = int(fade_in * sample_rate)
        fo_samp = int(fade_out * sample_rate)

        if fi_samp > 0:
            fi_samp = min(fi_samp, n)
            envelope[:fi_samp] = 1.0 - np.exp(-5.0 * np.arange(fi_samp) / fi_samp)
        if fo_samp > 0:
            fo_samp = min(fo_samp, n)
            envelope[-fo_samp:] = np.exp(-5.0 * np.arange(fo_samp) / fo_samp)

        return samples * envelope

    def apply_lowpass(
        samples: np.ndarray,
        cutoff: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Butterworth lowpass filter (2-pole)."""
        try:
            from scipy import signal

            sos = signal.butter(2, cutoff, btype="low", fs=sample_rate, output="sos")
            return signal.sosfiltfilt(sos, samples)
        except ImportError:
            # Fallback to single-pole RC
            rc = 1.0 / (2.0 * math.pi * cutoff)
            dt = 1.0 / sample_rate
            alpha = dt / (rc + dt)
            result = np.zeros_like(samples)
            result[0] = samples[0]
            for i in range(1, len(samples)):
                result[i] = result[i - 1] + alpha * (samples[i] - result[i - 1])
            return result

    def apply_highpass(
        samples: np.ndarray,
        cutoff: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Butterworth highpass filter (2-pole)."""
        try:
            from scipy import signal

            sos = signal.butter(2, cutoff, btype="high", fs=sample_rate, output="sos")
            return signal.sosfiltfilt(sos, samples)
        except ImportError:
            rc = 1.0 / (2.0 * math.pi * cutoff)
            dt = 1.0 / sample_rate
            alpha = rc / (rc + dt)
            result = np.zeros_like(samples)
            result[0] = samples[0]
            for i in range(1, len(samples)):
                result[i] = alpha * (result[i - 1] + samples[i] - samples[i - 1])
            return result

    def apply_reverb(
        samples: np.ndarray,
        room_size: float = 0.5,
        damping: float = 0.5,
        wet_level: float = 0.2,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Freeverb-style reverb: 8 comb filters + 4 all-pass filters."""
        n = len(samples)
        wet = np.zeros(n, dtype=np.float64)

        # Comb filter delays (in samples) — classic Freeverb values scaled by room_size
        comb_delays = [1557, 1617, 1491, 1422, 1277, 1356, 1188, 1116]
        for delay in comb_delays:
            d = int(delay * (0.5 + room_size))
            buffer = np.zeros(d, dtype=np.float64)
            ptr = 0
            feedback = 0.84 * room_size
            for i in range(n):
                output = samples[i] + buffer[ptr] * feedback
                buffer[ptr] = output * (1.0 - damping) + buffer[ptr] * damping
                ptr = (ptr + 1) % d
                wet[i] += output
        wet /= 8.0

        # All-pass filters
        ap_delays = [225, 556, 441, 341]
        for delay in ap_delays:
            d = max(1, delay)
            buffer = np.zeros(d, dtype=np.float64)
            ptr = 0
            for i in range(n):
                buf_out = buffer[ptr]
                buffer[ptr] = wet[i] + buf_out * 0.5
                wet[i] = buf_out - wet[i] * 0.5
                ptr = (ptr + 1) % d

        # Mix wet and dry
        return samples * (1.0 - wet_level) + wet * wet_level

    def apply_delay(
        samples: np.ndarray,
        delay_time: float = 0.3,
        feedback: float = 0.4,
        mix: float = 0.3,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """Stereo ping-pong delay."""
        n = len(samples)
        delay_samp = int(delay_time * sample_rate)
        wet = np.zeros(n, dtype=np.float64)
        buffer = np.zeros(delay_samp, dtype=np.float64)
        ptr = 0
        for i in range(n):
            wet[i] = buffer[ptr]
            buffer[ptr] = samples[i] + buffer[ptr] * feedback
            ptr = (ptr + 1) % delay_samp
        return samples * (1.0 - mix) + wet * mix

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
        """Distortion: soft clip, tube, or bit-crush."""
        if type_ == "soft":
            # Soft clip using tanh
            return np.tanh(samples * (1.0 + drive * 10.0))
        elif type_ == "tube":
            # Asymmetric tube distortion
            s = samples * (1.0 + drive * 5.0)
            return np.where(s >= 0, np.tanh(s), np.tanh(s * 1.5) / 1.5)
        elif type_ == "bit":
            # Bit crush
            bits = max(1, int(16 * (1.0 - drive)))
            max_val = 2.0 ** (bits - 1)
            return np.round(samples * max_val) / max_val
        else:
            return samples

    def apply_compressor(
        samples: np.ndarray,
        threshold: float = 0.5,
        ratio: float = 4.0,
        attack: float = 0.01,
        release: float = 0.1,
        makeup: float = 1.0,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """RMS compressor with attack/release envelope."""
        n = len(samples)
        attack_coef = np.exp(-1.0 / (attack * sample_rate))
        release_coef = np.exp(-1.0 / (release * sample_rate))
        envelope = np.zeros(n, dtype=np.float64)
        gain = np.ones(n, dtype=np.float64)

        # RMS envelope
        window = int(0.01 * sample_rate)  # 10ms window
        for i in range(n):
            start = max(0, i - window)
            rms = np.sqrt(np.mean(samples[start : i + 1] ** 2))
            if rms > envelope[i - 1] if i > 0 else 0:
                envelope[i] = attack_coef * (envelope[i - 1] if i > 0 else 0) + (1.0 - attack_coef) * rms
            else:
                envelope[i] = release_coef * (envelope[i - 1] if i > 0 else 0) + (1.0 - release_coef) * rms

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
        """3-band parametric EQ using shelving filters."""
        try:
            from scipy import signal

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
            # Mid peaking
            if mid_gain != 0.0:
                mid_freq = (low_freq * high_freq) ** 0.5
                bw = np.log2(high_freq / low_freq)
                b, a = signal.iirpeak(mid_freq, bw, fs=sample_rate)
                mid = signal.filtfilt(b, a, samples)
                result += mid * (10.0 ** (mid_gain / 20.0) - 1.0)
            return result
        except ImportError:
            return samples

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
        """Convert float samples (-1 to 1) to 16-bit PCM bytes."""
        clipped = np.clip(samples, -1.0, 1.0)
        int16 = (clipped * 32767.0).astype(np.int16)
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
            # 24-bit: pad to 32-bit
            n = len(pcm_bytes) // 3
            arr = np.zeros(n, dtype=np.int32)
            for i in range(n):
                arr[i] = int.from_bytes(pcm_bytes[i * 3 : i * 3 + 3], "little", signed=True)
            raw = arr.astype(np.float64)
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
        _validate_output_path(output_path)
        with wave.open(output_path, "wb") as wav_file:
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
