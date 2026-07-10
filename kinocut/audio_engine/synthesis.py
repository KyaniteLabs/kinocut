"""Audio synthesis and sound design engine.

NumPy-based professional DSP with band-limited waveforms and high-quality effects.
"""

from __future__ import annotations

from typing import Any, Literal

from ..errors import MCPVideoError

from .core import (
    _float_to_pcm,
    _pcm_to_float,
    apply_chorus,
    apply_delay,
    apply_distortion,
    apply_envelope,
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

# ---------------------------------------------------------------------------
# Audio Constants
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit

VALID_AUDIO_SYNTH_EFFECT_KEYS = {
    "envelope",
    "fade_in",
    "fade_out",
    "reverb",
    "lowpass",
    "highpass",
    "delay",
    "chorus",
    "flanger",
    "distortion",
    "tremolo",
    "vibrato",
}


def _validate_synth_effects(effects: dict[str, Any] | None) -> None:
    """Validate synthesis effect keys before generating output."""
    if effects is None:
        return
    if not isinstance(effects, dict):
        raise MCPVideoError("effects must be a dict", error_type="validation_error", code="invalid_parameter")

    unknown = sorted(set(effects) - VALID_AUDIO_SYNTH_EFFECT_KEYS)
    if unknown:
        raise MCPVideoError(
            f"effects keys must be one of {sorted(VALID_AUDIO_SYNTH_EFFECT_KEYS)}, got unsupported keys {unknown}",
            error_type="validation_error",
            code="invalid_parameter",
        )


def _apply_synth_effects(
    samples: Any,
    effects: dict[str, Any],
    duration: float,
    sample_rate: int,
) -> Any:
    """Apply a chain of synthesis effects."""
    if not effects:
        return samples

    # Envelope
    if "envelope" in effects:
        env = effects["envelope"]
        samples = apply_envelope(
            samples,
            attack=env.get("attack", 0.01),
            decay=env.get("decay", 0.1),
            sustain=env.get("sustain", 0.7),
            release=env.get("release", 0.2),
            duration=duration,
            sample_rate=sample_rate,
        )

    # Fade in/out
    fade_in = effects.get("fade_in", 0)
    fade_out = effects.get("fade_out", 0)
    if fade_in > 0 or fade_out > 0:
        samples = apply_fade(samples, fade_in, fade_out, duration, sample_rate)

    # Reverb
    if "reverb" in effects:
        rev = effects["reverb"]
        samples = apply_reverb(
            samples,
            room_size=rev.get("room_size", 0.5),
            damping=rev.get("damping", 0.5),
            wet_level=rev.get("wet_level", 0.2),
            sample_rate=sample_rate,
        )

    # Lowpass
    if "lowpass" in effects:
        lp = effects["lowpass"]
        cutoff = lp.get("frequency", 2000) if isinstance(lp, dict) else lp
        samples = apply_lowpass(samples, cutoff, sample_rate)

    # Highpass
    if "highpass" in effects:
        hp = effects["highpass"]
        cutoff = hp.get("frequency", 200) if isinstance(hp, dict) else hp
        samples = apply_highpass(samples, cutoff, sample_rate)

    # Delay
    if "delay" in effects:
        d = effects["delay"]
        samples = apply_delay(
            samples,
            delay_time=d.get("delay_time", 0.3),
            feedback=d.get("feedback", 0.4),
            mix=d.get("mix", 0.3),
            sample_rate=sample_rate,
        )

    # Chorus
    if "chorus" in effects:
        c = effects["chorus"]
        samples = apply_chorus(
            samples,
            rate=c.get("rate", 1.5),
            depth=c.get("depth", 0.002),
            voices=c.get("voices", 3),
            mix=c.get("mix", 0.5),
            sample_rate=sample_rate,
        )

    # Flanger
    if "flanger" in effects:
        f = effects["flanger"]
        samples = apply_flanger(
            samples,
            rate=f.get("rate", 0.5),
            depth=f.get("depth", 0.003),
            feedback=f.get("feedback", 0.5),
            mix=f.get("mix", 0.5),
            sample_rate=sample_rate,
        )

    # Distortion
    if "distortion" in effects:
        d = effects["distortion"]
        samples = apply_distortion(
            samples,
            drive=d.get("drive", 0.5),
            tone=d.get("tone", 0.5),
            type_=d.get("type", "soft"),
            sample_rate=sample_rate,
        )

    # Tremolo
    if "tremolo" in effects:
        t = effects["tremolo"]
        samples = apply_tremolo(
            samples,
            rate=t.get("rate", 5.0),
            depth=t.get("depth", 0.5),
            sample_rate=sample_rate,
        )

    # Vibrato
    if "vibrato" in effects:
        v = effects["vibrato"]
        samples = apply_vibrato(
            samples,
            rate=v.get("rate", 5.0),
            depth=v.get("depth", 0.003),
            sample_rate=sample_rate,
        )

    return samples


def audio_synthesize(
    output: str,
    waveform: Literal["sine", "square", "sawtooth", "triangle", "noise", "pulse", "supersaw", "pluck", "fm"] = "sine",
    frequency: float = 440.0,
    duration: float = 1.0,
    volume: float = 0.5,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    effects: dict[str, Any] | None = None,
    stereo: bool = False,
    pan: float = 0.0,
) -> str:
    """Generate audio procedurally using synthesis.

    Args:
        output: Output WAV file path
        waveform: Type of waveform to generate
        frequency: Base frequency in Hz
        duration: Duration in seconds
        volume: Amplitude (0-1)
        sample_rate: Sample rate in Hz
        effects: Optional effects dictionary
        stereo: Output stereo WAV
        pan: Stereo panning (-1 left to 1 right, 0 center)

    Returns:
        Path to generated WAV file
    """
    from ..limits import MAX_AUDIO_DURATION, MIN_FREQUENCY, MAX_FREQUENCY, MIN_SAMPLE_RATE, MAX_SAMPLE_RATE

    _validate_synth_effects(effects)

    if not (MIN_FREQUENCY <= frequency <= MAX_FREQUENCY):
        raise MCPVideoError(
            f"Frequency must be between {MIN_FREQUENCY} and {MAX_FREQUENCY} Hz, got {frequency}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.01 <= duration <= MAX_AUDIO_DURATION):
        raise MCPVideoError(
            f"Duration must be between 0.01 and {MAX_AUDIO_DURATION} seconds, got {duration}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= volume <= 1.0):
        raise MCPVideoError(
            f"Volume must be between 0.0 and 1.0, got {volume}", error_type="validation_error", code="invalid_parameter"
        )
    if not (MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE):
        raise MCPVideoError(
            f"Sample rate must be between {MIN_SAMPLE_RATE} and {MAX_SAMPLE_RATE}, got {sample_rate}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    # Generate base waveform
    if waveform == "sine":
        pcm_data = generate_sine(frequency, duration, sample_rate, volume)
    elif waveform == "square":
        pcm_data = generate_square(frequency, duration, sample_rate, volume)
    elif waveform == "sawtooth":
        pcm_data = generate_sawtooth(frequency, duration, sample_rate, volume)
    elif waveform == "triangle":
        pcm_data = generate_triangle(frequency, duration, sample_rate, volume)
    elif waveform == "noise":
        pcm_data = generate_noise(duration, sample_rate, volume)
    elif waveform == "pulse":
        pcm_data = generate_pulse(frequency, duration, sample_rate, volume)
    elif waveform == "supersaw":
        pcm_data = generate_supersaw(frequency, duration, sample_rate, volume)
    elif waveform == "pluck":
        pcm_data = generate_pluck(frequency, duration, sample_rate, volume)
    elif waveform == "fm":
        pcm_data = generate_fm(frequency, duration, sample_rate, volume)
    else:
        raise MCPVideoError(f"Unknown waveform: {waveform}", error_type="validation_error", code="invalid_parameter")

    # Convert to float for processing
    samples = _pcm_to_float(pcm_data)

    # Apply effects chain
    samples = _apply_synth_effects(samples, effects or {}, duration, sample_rate)

    # Stereo panning
    if stereo:
        from .core import apply_pan

        samples = apply_pan(samples, pan)
        pcm_data = _float_to_pcm(samples)
        return write_wav(pcm_data, output, sample_rate, channels=2)

    # Convert back to PCM and write
    pcm_data = _float_to_pcm(samples)
    return write_wav(pcm_data, output, sample_rate)


def audio_preset(
    preset: str,
    output: str,
    pitch: Literal["low", "mid", "high"] = "mid",
    duration: float | None = None,
    intensity: float = 0.5,
    stereo: bool = False,
    pan: float = 0.0,
) -> str:
    """Generate preset sound design elements.

    Presets:
        UI: ui-blip, ui-click, ui-tap, ui-whoosh-up, ui-whoosh-down
        Ambient: drone-low, drone-mid, drone-tech, drone-ominous
        Notifications: chime-success, chime-error, chime-notification
        Percussion: bass-kick, snare, hi-hat
        FX: alarm, notify, confirm, cancel
        Data: typing, scan, processing, data-flow, upload, download

    Args:
        preset: Preset name
        output: Output WAV file path
        pitch: Pitch variation (low/mid/high)
        duration: Override default duration
        intensity: Effect intensity (0-1)
        stereo: Output stereo WAV
        pan: Stereo panning (-1 left to 1 right)

    Returns:
        Path to generated WAV file
    """
    from .presets import _PITCH_MULT, get_preset_config

    if pitch not in _PITCH_MULT:
        raise MCPVideoError(
            f"pitch must be one of {sorted(_PITCH_MULT)}, got {pitch!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not isinstance(intensity, (int, float)) or intensity < 0 or intensity > 1:
        raise MCPVideoError(
            f"intensity must be between 0 and 1, got {intensity}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    try:
        config = get_preset_config(preset)
    except KeyError as exc:
        raise MCPVideoError(
            str(exc),
            error_type="validation_error",
            code="invalid_parameter",
        ) from None

    mult = _PITCH_MULT[pitch]
    config["frequency"] = config["frequency"] * mult

    if duration is not None:
        config["duration"] = duration

    if preset in {"typing", "scan", "hi-hat", "ui-tap"}:
        config["volume"] = config["volume"] * intensity

    return audio_synthesize(output=output, stereo=stereo, pan=pan, **config)
