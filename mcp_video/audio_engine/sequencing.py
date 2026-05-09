"""Audio synthesis and sound design engine.

Pure NumPy-based audio generation with no external dependencies.
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..validation import VALID_AUDIO_SEQUENCE_TYPES, VALID_WAVEFORMS
from .core import (
    _float_to_pcm,
    _pcm_to_float,
    apply_fade,
    apply_highpass,
    apply_lowpass,
    apply_reverb,
    generate_noise,
    generate_sawtooth,
    generate_sine,
    generate_square,
    generate_triangle,
    write_wav,
)
from .synthesis import audio_preset

# ---------------------------------------------------------------------------
# Audio Constants
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit


def _validate_audio_sequence(sequence: list[dict[str, Any]]) -> None:
    """Validate sequence events before generating any output file."""
    if not isinstance(sequence, list) or not sequence:
        raise MCPVideoError("Sequence cannot be empty", error_type="validation_error", code="invalid_parameter")

    for i, event in enumerate(sequence):
        if not isinstance(event, dict):
            raise MCPVideoError(
                f"sequence[{i}] must be a dict",
                error_type="validation_error",
                code="invalid_parameter",
            )

        event_type = event.get("type")
        if event_type not in VALID_AUDIO_SEQUENCE_TYPES:
            raise MCPVideoError(
                f"sequence[{i}].type must be one of {sorted(VALID_AUDIO_SEQUENCE_TYPES)}, got {event_type!r}",
                error_type="validation_error",
                code="invalid_parameter",
            )

        at = event.get("at")
        if not isinstance(at, (int, float)):
            raise MCPVideoError(
                f"sequence[{i}].at must be numeric",
                error_type="validation_error",
                code="invalid_parameter",
            )

        duration = event.get("duration", 1.0)
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise MCPVideoError(
                f"sequence[{i}].duration must be > 0",
                error_type="validation_error",
                code="invalid_parameter",
            )

        if event_type == "tone":
            waveform = event.get("waveform", "sine")
            if waveform not in VALID_WAVEFORMS:
                raise MCPVideoError(
                    f"sequence[{i}].waveform must be one of {sorted(VALID_WAVEFORMS)}, got {waveform!r}",
                    error_type="validation_error",
                    code="invalid_parameter",
                )


def audio_sequence(
    sequence: list[dict[str, Any]],
    output: str,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> str:
    """Compose multiple audio events into a timed sequence.

    Args:
        sequence: List of audio events with keys:
            - type: "tone", "preset", or "whoosh"
            - at: start time in seconds
            - duration: duration in seconds
            - freq/frequency: frequency for tones
            - name: preset name for presets
            - Other parameters as needed
        output: Output WAV file path
        sample_rate: Sample rate

    Returns:
        Path to generated WAV file
    """
    _validate_audio_sequence(sequence)

    # Calculate total duration
    max_end = max(event.get("at", 0) + event.get("duration", 1.0) for event in sequence)
    total_samples = int(max_end * sample_rate)

    # Initialize silent buffer
    mix_buffer = [0.0] * total_samples

    for event in sequence:
        start_time = event.get("at", 0)
        duration = event.get("duration", 1.0)
        event_type = event.get("type", "tone")

        start_sample = int(start_time * sample_rate)
        int(duration * sample_rate)

        # Generate based on type
        if event_type == "tone":
            freq = event.get("freq") or event.get("frequency", 440)
            volume = event.get("volume", 0.3)
            waveform = event.get("waveform", "sine")

            if waveform == "sine":
                pcm = generate_sine(freq, duration, sample_rate, volume)
            elif waveform == "square":
                pcm = generate_square(freq, duration, sample_rate, volume)
            elif waveform == "sawtooth":
                pcm = generate_sawtooth(freq, duration, sample_rate, volume)
            elif waveform == "triangle":
                pcm = generate_triangle(freq, duration, sample_rate, volume)
            elif waveform == "noise":
                pcm = generate_noise(duration, sample_rate, volume)

            samples = _pcm_to_float(pcm)

        elif event_type == "preset":
            # Create temp file and read back
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                audio_preset(
                    preset=event.get("name", "ui-blip"),
                    output=tmp_path,
                    duration=duration,
                    intensity=event.get("intensity", 0.5),
                )

                with wave.open(tmp_path, "rb") as wav_file:
                    frames = wav_file.readframes(wav_file.getnframes())
                    samples = _pcm_to_float(frames)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        elif event_type == "whoosh":
            # Simple whoosh using filtered noise
            event.get("direction", "up")
            volume = event.get("volume", 0.3)
            pcm = generate_noise(duration, sample_rate, volume)
            samples = _pcm_to_float(pcm)
            samples = apply_lowpass(samples, 2000, sample_rate)

        # Mix into buffer
        for i, sample in enumerate(samples):
            idx = start_sample + i
            if idx < len(mix_buffer):
                mix_buffer[idx] += sample

    # Normalize to prevent clipping
    max_val = max(abs(s) for s in mix_buffer) if mix_buffer else 1
    if max_val > 1:
        mix_buffer = [s / max_val for s in mix_buffer]

    pcm_data = _float_to_pcm(mix_buffer)
    return write_wav(pcm_data, output, sample_rate)


def audio_compose(
    tracks: list[dict[str, Any]],
    duration: float,
    output: str,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> str:
    """Layer multiple audio tracks with mixing.

    Args:
        tracks: List of track configs with:
            - file: path to WAV file
            - volume: volume multiplier (0-1)
            - start: start time in seconds
            - loop: whether to loop the track
        duration: Total duration of output
        output: Output WAV file path
        sample_rate: Sample rate

    Returns:
        Path to generated WAV file
    """
    total_samples = int(duration * sample_rate)
    mix_buffer = [0.0] * total_samples

    for track in tracks:
        file_path = track.get("file")
        volume = track.get("volume", 1.0)
        start_time = track.get("start", 0)
        loop = track.get("loop", False)

        if not file_path or not isinstance(file_path, str):
            raise MCPVideoError(
                "tracks must contain 'file' key with a non-empty path string",
                error_type="validation_error",
                code="invalid_parameter",
            )
        if not Path(file_path).exists():
            raise MCPVideoError(
                f"Audio track file not found: {file_path}",
                error_type="input_error",
                code="invalid_input",
            )

        # Read WAV file
        with wave.open(file_path, "rb") as wav_file:
            sample_width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            frames = wav_file.readframes(wav_file.getnframes())
            track_samples = _pcm_to_float(frames, sample_width=sample_width, channels=channels)

        start_sample = int(start_time * sample_rate)

        # Add to mix buffer
        if loop:
            for i in range(total_samples - start_sample):
                idx = start_sample + i
                sample_idx = i % len(track_samples)
                if idx < len(mix_buffer):
                    mix_buffer[idx] += track_samples[sample_idx] * volume
        else:
            for i, sample in enumerate(track_samples):
                idx = start_sample + i
                if idx < len(mix_buffer):
                    mix_buffer[idx] += sample * volume

    # Normalize
    max_val = max(abs(s) for s in mix_buffer) if mix_buffer else 1
    if max_val > 1:
        mix_buffer = [s / max_val * 0.95 for s in mix_buffer]  # Leave headroom

    pcm_data = _float_to_pcm(mix_buffer)
    return write_wav(pcm_data, output, sample_rate)


def audio_effects(
    input_path: str,
    output: str,
    effects: list[dict[str, Any]],
) -> str:
    """Apply audio effects chain.

    Args:
        input_path: Input WAV file path
        output: Output WAV file path
        effects: List of effect configs with:
            - type: "lowpass", "highpass", "reverb", "normalize"
            - Additional parameters per effect type

    Returns:
        Path to processed WAV file
    """
    # Read input
    with wave.open(input_path, "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()
        frames = wav_file.readframes(wav_file.getnframes())
        samples = _pcm_to_float(frames, sample_width=sample_width, channels=channels)

    # Apply effects chain
    for effect in effects:
        effect_type = effect.get("type")

        if effect_type == "lowpass":
            cutoff = effect.get("frequency", 2000)
            samples = apply_lowpass(samples, cutoff, sample_rate)

        elif effect_type == "reverb":
            room_size = effect.get("room_size", 0.5)
            damping = effect.get("damping", 0.5)
            wet_level = effect.get("wet_level", 0.2)
            samples = apply_reverb(samples, room_size, damping, wet_level)

        elif effect_type == "normalize":
            max_val = max(abs(s) for s in samples) if samples else 1
            if max_val > 0:
                effect.get("target_lufs", -16)
                # Simple linear normalization (LUFS would require more complex analysis)
                gain = 0.5 / max_val  # Approximate -6dB as baseline
                samples = [s * gain for s in samples]

        elif effect_type == "highpass":
            cutoff = effect.get("frequency", 200)
            samples = apply_highpass(samples, cutoff, sample_rate)

        elif effect_type == "fade":
            fade_in = effect.get("fade_in", 0)
            fade_out = effect.get("fade_out", 0)
            duration = len(samples) / sample_rate
            samples = apply_fade(samples, fade_in, fade_out, duration, sample_rate)

    # Write output
    pcm_data = _float_to_pcm(samples)
    return write_wav(pcm_data, output, sample_rate)


# ---------------------------------------------------------------------------
# Video Integration
# ---------------------------------------------------------------------------
