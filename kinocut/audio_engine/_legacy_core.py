"""Legacy pure-Python audio synthesis fallback.

This compatibility-focused engine intentionally avoids NumPy and external
dependencies. It trades performance for availability when the professional DSP
backend cannot be imported.
"""

from __future__ import annotations

import math
import random
import struct
import wave

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_output_path


# ---------------------------------------------------------------------------
# Audio Constants
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit


def _require_positive_frequency(frequency: float) -> None:
    if frequency <= 0:
        raise MCPVideoError(
            "frequency must be greater than 0",
            error_type="validation_error",
            code="invalid_frequency",
        )


# ---------------------------------------------------------------------------
# Waveform Generation
# ---------------------------------------------------------------------------


def generate_sine(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a sine wave."""
    num_samples = int(sample_rate * duration)
    samples = []

    for i in range(num_samples):
        t = i / sample_rate
        value = amplitude * math.sin(2 * math.pi * frequency * t)
        samples.append(value)

    return _float_to_pcm(samples)


def generate_square(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a square wave."""
    num_samples = int(sample_rate * duration)
    samples = []

    for i in range(num_samples):
        t = i / sample_rate
        value = amplitude * (1 if math.sin(2 * math.pi * frequency * t) >= 0 else -1)
        samples.append(value)

    return _float_to_pcm(samples)


def generate_sawtooth(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a sawtooth wave."""
    _require_positive_frequency(frequency)
    num_samples = int(sample_rate * duration)
    samples = []
    period = sample_rate / frequency

    for i in range(num_samples):
        value = amplitude * (2 * ((i % period) / period) - 1)
        samples.append(value)

    return _float_to_pcm(samples)


def generate_triangle(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a triangle wave."""
    _require_positive_frequency(frequency)
    num_samples = int(sample_rate * duration)
    samples = []
    period = sample_rate / frequency

    for i in range(num_samples):
        phase = (i % period) / period
        if phase < 0.25:
            value = 4 * phase
        elif phase < 0.75:
            value = 2 - 4 * phase
        else:
            value = 4 * phase - 4
        samples.append(amplitude * value)

    return _float_to_pcm(samples)


def generate_noise(
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.3,
) -> bytes:
    """Generate white noise."""
    num_samples = int(sample_rate * duration)
    samples = []

    for _ in range(num_samples):
        value = amplitude * (random.random() * 2 - 1)
        samples.append(value)

    return _float_to_pcm(samples)


def generate_pulse(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
    width: float = 0.25,
) -> bytes:
    """Generate a pulse wave."""
    _require_positive_frequency(frequency)
    width = max(0.01, min(0.99, width))
    num_samples = int(sample_rate * duration)
    period = sample_rate / frequency
    samples = []
    for i in range(num_samples):
        phase = (i % period) / period
        samples.append(amplitude * (1.0 if phase < width else -1.0))
    return _float_to_pcm(samples)


def generate_supersaw(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
    detune: float = 0.02,
    voices: int = 7,
) -> bytes:
    """Generate detuned sawtooth voices."""
    _require_positive_frequency(frequency)
    voices = max(1, int(voices))
    num_samples = int(sample_rate * duration)
    samples = []
    for i in range(num_samples):
        value = 0.0
        for voice in range(voices):
            spread = (voice - (voices - 1) / 2) / ((voices - 1) / 2) if voices > 1 else 0.0
            detuned_frequency = frequency * (1.0 + spread * detune)
            if detuned_frequency <= 0:
                raise MCPVideoError(
                    "detune produces a non-positive voice frequency",
                    error_type="validation_error",
                    code="invalid_detune",
                )
            period = sample_rate / detuned_frequency
            value += 2 * ((i % period) / period) - 1
        samples.append(amplitude * value / voices)
    return _float_to_pcm(samples)


def generate_colored_noise(
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.3,
    color: str = "white",
) -> bytes:
    """Generate white, pink-ish, brown, or blue noise."""
    num_samples = int(sample_rate * duration)
    white = [random.random() * 2 - 1 for _ in range(num_samples)]
    if color == "brown":
        acc = 0.0
        samples = []
        for sample in white:
            acc = max(-1.0, min(1.0, acc + sample * 0.02))
            samples.append(acc)
    elif color == "blue":
        prev = white[0] if white else 0.0
        samples = []
        for sample in white:
            samples.append(sample - prev)
            prev = sample
    elif color == "pink":
        samples = _smooth_samples(white, window=8)
    else:
        samples = white
    return _float_to_pcm(_normalize_samples(samples, amplitude))


def generate_pluck(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
    decay: float = 0.995,
) -> bytes:
    """Generate a simple Karplus-Strong pluck."""
    _require_positive_frequency(frequency)
    delay = max(1, int(sample_rate / frequency))
    buffer = [random.random() * 2 - 1 for _ in range(delay)]
    samples = []
    index = 0
    for _ in range(int(sample_rate * duration)):
        sample = buffer[index]
        next_index = (index + 1) % delay
        buffer[index] = decay * 0.5 * (sample + buffer[next_index])
        samples.append(sample)
        index = next_index
    return _float_to_pcm(_normalize_samples(samples, amplitude))


def generate_fm(
    frequency: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.5,
    ratio: float = 2.0,
    index: float = 5.0,
) -> bytes:
    """Generate a two-operator FM tone."""
    _require_positive_frequency(frequency)
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        carrier = 2 * math.pi * frequency * t
        modulator = index * math.sin(2 * math.pi * frequency * ratio * t)
        samples.append(amplitude * math.sin(carrier + modulator))
    return _float_to_pcm(samples)


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


def apply_envelope(
    samples: list[float],
    attack: float,
    decay: float,
    sustain: float,
    release: float,
    duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Apply ADSR envelope to samples."""
    total_samples = len(samples)
    attack_samples = int(attack * sample_rate)
    decay_samples = int(decay * sample_rate)
    release_samples = int(release * sample_rate)
    sustain_samples = total_samples - attack_samples - decay_samples - release_samples

    result = []
    for i, sample in enumerate(samples):
        if i < attack_samples and attack_samples > 0:
            # Attack phase
            env = i / attack_samples
        elif i < attack_samples + decay_samples and decay_samples > 0:
            # Decay phase
            decay_progress = (i - attack_samples) / decay_samples
            env = 1 - (1 - sustain) * decay_progress
        elif i < attack_samples + decay_samples + max(0, sustain_samples):
            # Sustain phase
            env = sustain
        elif release_samples > 0:
            # Release phase
            release_progress = (i - attack_samples - decay_samples - sustain_samples) / release_samples
            env = sustain * (1 - release_progress)
        else:
            env = 0

        result.append(sample * env)

    return result


def apply_fade(samples: list[float], fade_in: float, fade_out: float, duration: float, sample_rate: int) -> list[float]:
    """Apply fade in/out to samples."""
    total_samples = len(samples)
    fade_in_samples = int(fade_in * sample_rate)
    fade_out_samples = int(fade_out * sample_rate)

    result = []
    for i, sample in enumerate(samples):
        envelope = 1.0

        if fade_in_samples > 0 and i < fade_in_samples:
            envelope = i / fade_in_samples

        if fade_out_samples > 0 and i >= total_samples - fade_out_samples:
            envelope = (total_samples - i) / fade_out_samples

        result.append(sample * envelope)

    return result


def apply_lowpass(samples: list[float], cutoff: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> list[float]:
    """Simple lowpass filter."""
    rc = 1.0 / (2 * math.pi * cutoff)
    dt = 1.0 / sample_rate
    alpha = dt / (rc + dt)

    result = [samples[0]]
    for i in range(1, len(samples)):
        result.append(result[-1] + alpha * (samples[i] - result[-1]))

    return result


def apply_highpass(samples: list[float], cutoff: float, sample_rate: int = DEFAULT_SAMPLE_RATE) -> list[float]:
    """Simple highpass filter."""
    rc = 1.0 / (2 * math.pi * cutoff)
    dt = 1.0 / sample_rate
    alpha = rc / (rc + dt)

    result = [samples[0]]
    for i in range(1, len(samples)):
        result.append(alpha * (result[-1] + samples[i] - samples[i - 1]))

    return result


def apply_reverb(
    samples: list[float],
    room_size: float = 0.5,
    damping: float = 0.5,
    wet_level: float = 0.2,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Simple comb filter reverb."""
    delay_samples = max(1, int(0.03 * sample_rate * max(0.0, room_size)))  # ~30ms base
    comb1 = _comb_filter(samples, max(1, int(delay_samples * 1.0)), 0.805, damping)
    comb2 = _comb_filter(samples, max(1, int(delay_samples * 0.97)), 0.827, damping)
    comb3 = _comb_filter(samples, max(1, int(delay_samples * 0.94)), 0.783, damping)
    comb4 = _comb_filter(samples, max(1, int(delay_samples * 0.91)), 0.812, damping)

    combined = [(c1 + c2 + c3 + c4) / 4 for c1, c2, c3, c4 in zip(comb1, comb2, comb3, comb4, strict=False)]

    # Mix wet and dry
    result = []
    for dry, wet in zip(samples, combined, strict=False):
        result.append(dry * (1 - wet_level) + wet * wet_level)

    return result


def apply_delay(
    samples: list[float],
    delay_time: float = 0.3,
    feedback: float = 0.4,
    mix: float = 0.3,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Apply a basic feedback delay."""
    delay = max(1, int(delay_time * sample_rate))
    buffer = [0.0] * delay
    index = 0
    result = []
    for sample in samples:
        delayed = buffer[index]
        buffer[index] = sample + delayed * feedback
        index = (index + 1) % delay
        result.append(sample * (1.0 - mix) + delayed * mix)
    return result


def apply_chorus(
    samples: list[float],
    rate: float = 1.5,
    depth: float = 0.002,
    voices: int = 3,
    mix: float = 0.5,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Apply a lightweight modulated multi-voice delay."""
    voices = max(1, int(voices))
    max_delay = max(1, int((depth + 0.005) * sample_rate))
    padded = [0.0] * max_delay + samples
    result = []
    for i, sample in enumerate(samples):
        wet = 0.0
        for voice in range(voices):
            phase = voice * (2 * math.pi / voices)
            lfo = depth * sample_rate * (0.5 + 0.5 * math.sin(2 * math.pi * rate * i / sample_rate + phase))
            wet += padded[max_delay + i - min(max_delay, int(lfo))]
        result.append(sample * (1.0 - mix) + (wet / voices) * mix)
    return result


def apply_flanger(
    samples: list[float],
    rate: float = 0.5,
    depth: float = 0.003,
    feedback: float = 0.5,
    mix: float = 0.5,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Apply a lightweight flanger."""
    max_delay = max(1, int((depth + 0.002) * sample_rate))
    buffer = [0.0] * max_delay
    write_index = 0
    result = []
    for i, sample in enumerate(samples):
        lfo = depth * sample_rate * (0.5 + 0.5 * math.sin(2 * math.pi * rate * i / sample_rate))
        delay = min(max_delay - 1, int(lfo))
        read_index = (write_index + (max_delay - 1 - delay)) % max_delay
        delayed = buffer[read_index]
        output = sample + delayed * mix
        buffer[write_index] = sample + delayed * feedback
        write_index = (write_index + 1) % max_delay
        result.append(output)
    return _limit_samples(result)


def apply_distortion(
    samples: list[float],
    drive: float = 0.5,
    tone: float = 0.5,
    type_: str = "soft",
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Apply soft, tube-like, or bit-crush distortion."""
    del tone, sample_rate
    if type_ == "bit":
        steps = max(2, int(256 * (1.0 - min(0.95, drive))))
        return [round(sample * steps) / steps for sample in samples]
    amount = 1.0 + drive * (5.0 if type_ == "tube" else 10.0)
    return [math.tanh(sample * amount) for sample in samples]


def apply_compressor(
    samples: list[float],
    threshold: float = 0.5,
    ratio: float = 4.0,
    attack: float = 0.01,
    release: float = 0.1,
    makeup: float = 1.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Apply simple peak compression."""
    del attack, release, sample_rate
    result = []
    for sample in samples:
        magnitude = abs(sample)
        if magnitude > threshold:
            excess = magnitude - threshold
            magnitude = threshold + excess / max(1.0, ratio)
            sample = math.copysign(magnitude, sample)
        result.append(sample * makeup)
    return _limit_samples(result)


def apply_eq(
    samples: list[float],
    low_gain: float = 0.0,
    mid_gain: float = 0.0,
    high_gain: float = 0.0,
    low_freq: float = 200.0,
    high_freq: float = 4000.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[float]:
    """Apply a simple three-band gain approximation."""
    low = apply_lowpass(samples, low_freq, sample_rate)
    high = apply_highpass(samples, high_freq, sample_rate)
    mid = [sample - low_i - high_i for sample, low_i, high_i in zip(samples, low, high, strict=False)]
    low_mult = 10 ** (low_gain / 20)
    mid_mult = 10 ** (mid_gain / 20)
    high_mult = 10 ** (high_gain / 20)
    return _limit_samples(
        [
            low_i * low_mult + mid_i * mid_mult + high_i * high_mult
            for low_i, mid_i, high_i in zip(low, mid, high, strict=False)
        ]
    )


def apply_pan(samples: list[float], pan: float = 0.0) -> list[list[float]]:
    """Convert mono samples to constant-power stereo."""
    pan = max(-1.0, min(1.0, pan))
    angle = (pan + 1.0) * math.pi / 4.0
    return [[sample * math.cos(angle), sample * math.sin(angle)] for sample in samples]


def apply_width(samples: list[float] | list[list[float]], width: float = 1.0) -> list[float] | list[list[float]]:
    """Apply mid-side width to stereo samples."""
    if not samples or not isinstance(samples[0], list):
        return samples
    result = []
    for left, right in samples:  # type: ignore[misc]
        mid = (left + right) * 0.5
        side = (right - left) * 0.5 * width
        result.append([mid - side, mid + side])
    return result


def apply_tremolo(
    samples: list[float], rate: float = 5.0, depth: float = 0.5, sample_rate: int = DEFAULT_SAMPLE_RATE
) -> list[float]:
    """Apply amplitude modulation."""
    return [
        sample * (1.0 - depth + depth * math.sin(2 * math.pi * rate * i / sample_rate))
        for i, sample in enumerate(samples)
    ]


def apply_vibrato(
    samples: list[float], rate: float = 5.0, depth: float = 0.003, sample_rate: int = DEFAULT_SAMPLE_RATE
) -> list[float]:
    """Apply pitch vibrato using a modulated delay."""
    max_delay = max(1, int((depth + 0.002) * sample_rate))
    padded = [0.0] * max_delay + samples
    result = []
    for i, sample in enumerate(samples):
        lfo = depth * sample_rate * (0.5 + 0.5 * math.sin(2 * math.pi * rate * i / sample_rate))
        idx = max_delay + i - min(max_delay, int(lfo))
        result.append(padded[idx] if 0 <= idx < len(padded) else sample)
    return result


def _comb_filter(samples: list[float], delay: int, feedback: float, damping: float) -> list[float]:
    """Simple comb filter for reverb."""
    buffer = [0.0] * delay
    result = []

    for sample in samples:
        output = sample + buffer[0] * feedback
        buffer.append(output * (1 - damping))
        buffer.pop(0)
        result.append(output)

    return result


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _float_to_pcm(samples: list[float] | list[list[float]]) -> bytes:
    """Convert float samples (-1 to 1) to 16-bit PCM bytes."""
    pcm_data = []
    for sample in samples:
        values = sample if isinstance(sample, list) else [sample]
        for value in values:
            value = max(-1, min(1, value))
            pcm_data.append(struct.pack("<h", int(value * 32767)))
    return b"".join(pcm_data)


def _normalize_samples(samples: list[float], amplitude: float) -> list[float]:
    max_value = max(abs(sample) for sample in samples) if samples else 0.0
    if max_value == 0:
        return samples
    return [sample / max_value * amplitude for sample in samples]


def _smooth_samples(samples: list[float], window: int) -> list[float]:
    result = []
    for i in range(len(samples)):
        start = max(0, i - window)
        end = min(len(samples), i + window + 1)
        result.append(sum(samples[start:end]) / (end - start))
    return result


def _limit_samples(samples: list[float]) -> list[float]:
    return [max(-1.0, min(1.0, sample)) for sample in samples]


def _pcm_to_float(
    pcm_bytes: bytes, sample_width: int = DEFAULT_SAMPLE_WIDTH, channels: int = DEFAULT_CHANNELS
) -> list[float]:
    """Convert PCM bytes to mono float samples."""
    if sample_width not in {1, 2, 3, 4}:
        raise MCPVideoError(
            f"Unsupported PCM sample width: {sample_width}",
            error_type="validation_error",
            code="invalid_sample_width",
        )
    frame_width = sample_width * channels
    samples = []
    for frame_start in range(0, len(pcm_bytes), frame_width):
        frame = pcm_bytes[frame_start : frame_start + frame_width]
        if len(frame) < frame_width:
            break
        channel_values = []
        for channel in range(channels):
            start = channel * sample_width
            raw = frame[start : start + sample_width]
            if sample_width == 1:
                value = raw[0] - 128
                channel_values.append(value / 128)
            elif sample_width == 2:
                value = struct.unpack("<h", raw)[0]
                channel_values.append(value / 32767)
            elif sample_width == 3:
                value = int.from_bytes(raw, "little", signed=True)
                channel_values.append(value / 8388607)
            else:
                value = struct.unpack("<i", raw)[0]
                channel_values.append(value / 2147483647)
        samples.append(sum(channel_values) / len(channel_values))
    return samples


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


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------
