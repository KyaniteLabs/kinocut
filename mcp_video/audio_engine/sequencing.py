"""Audio sequencing, composition, and effects engine.

NumPy-aware mixing with stereo support.
"""

from __future__ import annotations

import tempfile
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_ffmpeg
from ..validation import VALID_AUDIO_EFFECT_TYPES, VALID_AUDIO_SEQUENCE_TYPES, VALID_WAVEFORMS
from .core import (
    _float_to_pcm,
    _pcm_to_float,
    apply_chorus,
    apply_compressor,
    apply_delay,
    apply_distortion,
    apply_eq,
    apply_fade,
    apply_flanger,
    apply_highpass,
    apply_lowpass,
    apply_reverb,
    apply_tremolo,
    apply_vibrato,
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
)
from .synthesis import audio_preset

# ---------------------------------------------------------------------------
# Audio Constants
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit


def _wav_format_tag(path: str) -> int | None:
    """Read the RIFF fmt tag without asking Python's version-specific WAV decoder."""
    with Path(path).open("rb") as source:
        header = source.read(12)
        if len(header) != 12 or header[:4] not in {b"RIFF", b"RF64"} or header[8:] != b"WAVE":
            return None
        while chunk := source.read(8):
            if len(chunk) != 8:
                return None
            chunk_id = chunk[:4]
            chunk_size = int.from_bytes(chunk[4:], "little")
            if chunk_id == b"fmt ":
                format_tag = source.read(2)
                return int.from_bytes(format_tag, "little") if len(format_tag) == 2 else None
            source.seek(chunk_size + (chunk_size % 2), 1)
    return None


@contextmanager
def _canonical_wav_input(path: str, sample_rate: int) -> Iterator[str]:
    """Decode WAV variants unsupported by older stdlib readers to mono PCM16."""
    if _wav_format_tag(path) == 0x0001:
        yield path
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        canonical_path = tmp.name
    try:
        _run_ffmpeg(
            [
                "-i",
                path,
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                canonical_path,
            ]
        )
        yield canonical_path
    finally:
        Path(canonical_path).unlink(missing_ok=True)


def _normalize_mix(mix_buffer: Any) -> Any:
    """Normalize mixed audio to prevent clipping."""
    try:
        import numpy as np

        if isinstance(mix_buffer, np.ndarray):
            max_val = np.max(np.abs(mix_buffer))
            if max_val > 1.0:
                return mix_buffer / max_val * 0.95
            return mix_buffer
    except ImportError:
        pass

    # Pure-python fallback
    max_val = max(abs(s) for s in mix_buffer) if mix_buffer else 1
    if max_val > 1:
        return [s / max_val * 0.95 for s in mix_buffer]
    return mix_buffer


def _make_mix_buffer(total_samples: int, channels: int = 1) -> Any:
    """Create a silent mix buffer (numpy array if available)."""
    try:
        import numpy as np

        if channels > 1:
            return np.zeros((total_samples, channels), dtype=np.float64)
        return np.zeros(total_samples, dtype=np.float64)
    except ImportError:
        if channels > 1:
            return [[0.0] * channels for _ in range(total_samples)]
        return [0.0] * total_samples


def _mix_into_buffer(mix_buffer: Any, samples: Any, start_sample: int, volume: float = 1.0) -> Any:
    """Add samples into mix buffer at start_sample with volume scaling."""
    try:
        import numpy as np

        if isinstance(mix_buffer, np.ndarray):
            # Convert list samples to numpy array if needed
            if isinstance(samples, list):
                samples = np.array(samples, dtype=np.float64)
            end = min(start_sample + len(samples), len(mix_buffer))
            slice_len = end - start_sample
            if slice_len <= 0:
                return mix_buffer
            if (mix_buffer.ndim == 2 and samples.ndim == 2) or (mix_buffer.ndim == 1 and samples.ndim == 1):
                mix_buffer[start_sample:end] += samples[:slice_len] * volume
            elif mix_buffer.ndim == 2 and samples.ndim == 1:
                # Broadcast mono into stereo
                mix_buffer[start_sample:end, 0] += samples[:slice_len] * volume
                mix_buffer[start_sample:end, 1] += samples[:slice_len] * volume
            return mix_buffer
    except ImportError:
        pass

    # Pure-python fallback
    for i in range(len(samples)):
        idx = start_sample + i
        if idx < len(mix_buffer):
            if isinstance(mix_buffer[idx], list):
                mix_buffer[idx][0] += samples[i] * volume
                mix_buffer[idx][1] += samples[i] * volume
            else:
                mix_buffer[idx] += samples[i] * volume
    return mix_buffer


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


def _generate_waveform(
    waveform: str,
    frequency: float,
    duration: float,
    sample_rate: int,
    volume: float,
) -> bytes:
    """Generate raw PCM bytes for a waveform."""
    if waveform == "sine":
        return generate_sine(frequency, duration, sample_rate, volume)
    elif waveform == "square":
        return generate_square(frequency, duration, sample_rate, volume)
    elif waveform == "sawtooth":
        return generate_sawtooth(frequency, duration, sample_rate, volume)
    elif waveform == "triangle":
        return generate_triangle(frequency, duration, sample_rate, volume)
    elif waveform == "noise":
        return generate_noise(duration, sample_rate, volume)
    elif waveform == "pulse":
        return generate_pulse(frequency, duration, sample_rate, volume)
    elif waveform == "supersaw":
        return generate_supersaw(frequency, duration, sample_rate, volume)
    elif waveform == "pluck":
        return generate_pluck(frequency, duration, sample_rate, volume)
    elif waveform == "fm":
        return generate_fm(frequency, duration, sample_rate, volume)
    else:
        raise MCPVideoError(f"Unknown waveform: {waveform}", error_type="validation_error", code="invalid_parameter")


def audio_sequence(
    sequence: list[dict[str, Any]],
    output: str,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    stereo: bool = False,
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
        stereo: Output stereo WAV

    Returns:
        Path to generated WAV file
    """
    _validate_audio_sequence(sequence)

    # Calculate total duration
    max_end = max(event.get("at", 0) + event.get("duration", 1.0) for event in sequence)
    total_samples = int(max_end * sample_rate)
    channels = 2 if stereo else 1

    mix_buffer = _make_mix_buffer(total_samples, channels)

    for event in sequence:
        start_time = event.get("at", 0)
        duration = event.get("duration", 1.0)
        event_type = event.get("type", "tone")

        start_sample = int(start_time * sample_rate)

        # Generate based on type
        if event_type == "tone":
            freq = event.get("freq") or event.get("frequency", 440)
            volume = event.get("volume", 0.3)
            waveform = event.get("waveform", "sine")
            pcm = _generate_waveform(waveform, freq, duration, sample_rate, volume)
            samples = _pcm_to_float(pcm)

        elif event_type == "preset":
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
            volume = event.get("volume", 0.3)
            pcm = generate_noise(duration, sample_rate, volume)
            samples = _pcm_to_float(pcm)
            samples = apply_lowpass(samples, 2000, sample_rate)

        # Mix into buffer
        _mix_into_buffer(mix_buffer, samples, start_sample)

    # Normalize
    mix_buffer = _normalize_mix(mix_buffer)

    pcm_data = _float_to_pcm(mix_buffer)
    return write_wav(pcm_data, output, sample_rate, channels=channels)


def _validate_audio_compose_tracks(tracks: list[dict[str, Any]], duration: float) -> None:
    """Validate compose tracks before allocating or writing output."""
    if duration <= 0:
        raise MCPVideoError("duration must be > 0", error_type="validation_error", code="invalid_parameter")
    if not isinstance(tracks, list) or not tracks:
        raise MCPVideoError("tracks cannot be empty", error_type="validation_error", code="invalid_parameter")

    for i, track in enumerate(tracks):
        if not isinstance(track, dict):
            raise MCPVideoError(
                f"tracks[{i}] must be a dict",
                error_type="validation_error",
                code="invalid_parameter",
            )
        volume = track.get("volume", 1.0)
        if not isinstance(volume, (int, float)) or volume < 0 or volume > 1:
            raise MCPVideoError(
                f"tracks[{i}].volume must be between 0 and 1, got {volume}",
                error_type="validation_error",
                code="invalid_parameter",
            )


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
    _validate_audio_compose_tracks(tracks, duration)

    total_samples = int(duration * sample_rate)
    mix_buffer = _make_mix_buffer(total_samples, channels=1)

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

        # WAVE_FORMAT_EXTENSIBLE is valid PCM but unsupported by Python 3.11's
        # stdlib reader. Decode non-legacy headers to one canonical mix format.
        with (
            _canonical_wav_input(file_path, sample_rate) as readable_path,
            wave.open(readable_path, "rb") as wav_file,
        ):
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
                if idx < total_samples:
                    _mix_into_buffer(mix_buffer, [track_samples[sample_idx] * volume], idx)
        else:
            for i, sample in enumerate(track_samples):
                idx = start_sample + i
                if idx < total_samples:
                    _mix_into_buffer(mix_buffer, [sample * volume], idx)

    # Normalize
    mix_buffer = _normalize_mix(mix_buffer)

    pcm_data = _float_to_pcm(mix_buffer)
    return write_wav(pcm_data, output, sample_rate)


def _validate_audio_effects(effects: list[dict[str, Any]]) -> None:
    """Validate effects before reading or writing media."""
    if not isinstance(effects, list):
        raise MCPVideoError("effects must be a list", error_type="validation_error", code="invalid_parameter")

    for i, effect in enumerate(effects):
        if not isinstance(effect, dict):
            raise MCPVideoError(
                f"effects[{i}] must be a dict",
                error_type="validation_error",
                code="invalid_parameter",
            )

        effect_type = effect.get("type")
        if effect_type not in VALID_AUDIO_EFFECT_TYPES:
            raise MCPVideoError(
                f"effects[{i}].type must be one of {sorted(VALID_AUDIO_EFFECT_TYPES)}, got {effect_type!r}",
                error_type="validation_error",
                code="invalid_parameter",
            )


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
            - type: effect name
            - Additional parameters per effect type

    Returns:
        Path to processed WAV file
    """
    _validate_audio_effects(effects)

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

        elif effect_type == "highpass":
            cutoff = effect.get("frequency", 200)
            samples = apply_highpass(samples, cutoff, sample_rate)

        elif effect_type == "reverb":
            room_size = effect.get("room_size", 0.5)
            damping = effect.get("damping", 0.5)
            wet_level = effect.get("wet_level", 0.2)
            samples = apply_reverb(samples, room_size, damping, wet_level, sample_rate)

        elif effect_type == "delay":
            samples = apply_delay(
                samples,
                delay_time=effect.get("delay_time", 0.3),
                feedback=effect.get("feedback", 0.4),
                mix=effect.get("mix", 0.3),
                sample_rate=sample_rate,
            )

        elif effect_type == "chorus":
            samples = apply_chorus(
                samples,
                rate=effect.get("rate", 1.5),
                depth=effect.get("depth", 0.002),
                voices=effect.get("voices", 3),
                mix=effect.get("mix", 0.5),
                sample_rate=sample_rate,
            )

        elif effect_type == "flanger":
            samples = apply_flanger(
                samples,
                rate=effect.get("rate", 0.5),
                depth=effect.get("depth", 0.003),
                feedback=effect.get("feedback", 0.5),
                mix=effect.get("mix", 0.5),
                sample_rate=sample_rate,
            )

        elif effect_type == "distortion":
            samples = apply_distortion(
                samples,
                drive=effect.get("drive", 0.5),
                tone=effect.get("tone", 0.5),
                type_=effect.get("type", "soft"),
                sample_rate=sample_rate,
            )

        elif effect_type == "compressor":
            samples = apply_compressor(
                samples,
                threshold=effect.get("threshold", 0.5),
                ratio=effect.get("ratio", 4.0),
                attack=effect.get("attack", 0.01),
                release=effect.get("release", 0.1),
                makeup=effect.get("makeup", 1.0),
                sample_rate=sample_rate,
            )

        elif effect_type == "eq":
            samples = apply_eq(
                samples,
                low_gain=effect.get("low_gain", 0.0),
                mid_gain=effect.get("mid_gain", 0.0),
                high_gain=effect.get("high_gain", 0.0),
                low_freq=effect.get("low_freq", 200.0),
                high_freq=effect.get("high_freq", 4000.0),
                sample_rate=sample_rate,
            )

        elif effect_type == "tremolo":
            samples = apply_tremolo(
                samples,
                rate=effect.get("rate", 5.0),
                depth=effect.get("depth", 0.5),
                sample_rate=sample_rate,
            )

        elif effect_type == "vibrato":
            samples = apply_vibrato(
                samples,
                rate=effect.get("rate", 5.0),
                depth=effect.get("depth", 0.003),
                sample_rate=sample_rate,
            )

        elif effect_type == "normalize":
            try:
                import numpy as np

                if isinstance(samples, np.ndarray):
                    max_val = np.max(np.abs(samples))
                    if max_val > 0:
                        samples = samples / max_val * 0.95
                else:
                    max_val = max(abs(s) for s in samples) if samples else 1
                    if max_val > 0:
                        samples = [s / max_val * 0.95 for s in samples]
            except ImportError:
                max_val = max(abs(s) for s in samples) if samples else 1
                if max_val > 0:
                    samples = [s / max_val * 0.95 for s in samples]

        elif effect_type == "fade":
            fade_in = effect.get("fade_in", 0)
            fade_out = effect.get("fade_out", 0)
            duration = len(samples) / sample_rate
            samples = apply_fade(samples, fade_in, fade_out, duration, sample_rate)

    # Write output
    pcm_data = _float_to_pcm(samples)
    return write_wav(pcm_data, output, sample_rate)
