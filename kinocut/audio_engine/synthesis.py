"""Audio synthesis and sound design engine.

NumPy-based professional DSP with band-limited waveforms and high-quality effects.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from ..errors import MCPVideoError
from ..validation_errors import rejected_value

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
MAX_SYNTHESIS_SAMPLES = 44100 * 600 * 2  # 10 min @ 44.1 kHz stereo; caps in-memory buffers (H6)

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
            f"effects keys must be one of {sorted(VALID_AUDIO_SYNTH_EFFECT_KEYS)}; "
            f"{len(unknown)} submitted key(s) were not accepted",
            error_type="validation_error",
            code="invalid_parameter",
        )


def validate_effect_items(effects: list[dict[str, Any]], sample_rate: int) -> None:
    """Validate the ``audio_effects`` chain form: a list of ``{"type": ..., **params}`` items."""
    for item in effects:
        if isinstance(item, dict) and item.get("type"):
            validate_effect_values(
                {item["type"]: {key: value for key, value in item.items() if key != "type"}}, sample_rate
            )


#: Accepted numeric ranges for every effect parameter, shared by the synthesis
#: and effects tools. A value outside its range is an input error raised before
#: a single sample is generated, instead of a raw IndexError / ValueError from
#: numpy or a multi-gigabyte allocation. ``None`` means unbounded on that side.
_EFFECT_PARAM_RANGES: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "envelope": {"attack": (0.0, 60.0), "decay": (0.0, 60.0), "sustain": (0.0, 1.0), "release": (0.0, 60.0)},
    "reverb": {"room_size": (0.0, 1.0), "damping": (0.0, 1.0), "wet_level": (0.0, 1.0)},
    "delay": {"delay_time": (0.001, 10.0), "feedback": (0.0, 0.99), "mix": (0.0, 1.0)},
    "chorus": {"rate": (0.01, 100.0), "depth": (0.0, 0.05), "voices": (1, 8), "mix": (0.0, 1.0)},
    "flanger": {"rate": (0.01, 100.0), "depth": (0.0, 0.05), "feedback": (0.0, 0.99), "mix": (0.0, 1.0)},
    "distortion": {"drive": (0.0, 1.0), "tone": (0.0, 1.0)},
    "compressor": {
        "threshold": (0.0, 1.0),
        "ratio": (1.0, 100.0),
        "attack": (0.0, 1.0),
        "release": (0.0, 2.0),
        "makeup": (0.0, 64.0),
    },
    "eq": {
        "low_gain": (-60.0, 60.0),
        "mid_gain": (-60.0, 60.0),
        "high_gain": (-60.0, 60.0),
        "low_freq": (20.0, None),
        "high_freq": (20.0, None),
    },
    "tremolo": {"rate": (0.01, 100.0), "depth": (0.0, 1.0)},
    "vibrato": {"rate": (0.01, 100.0), "depth": (0.0, 0.05)},
    "fade": {"fade_in": (0.0, 600.0), "fade_out": (0.0, 600.0)},
    "normalize": {},
}
_EFFECT_PARAM_CHOICES: dict[str, dict[str, frozenset[str]]] = {
    "lowpass": {"type": frozenset({"static", "sweep_up", "sweep_down"})},
    "distortion": {"type": frozenset({"soft", "tube", "bit"})},
}
#: Parameters that must stay below Nyquist for the render rate.
_FREQUENCY_PARAMS: dict[str, frozenset[str]] = {
    "lowpass": frozenset({"frequency", "to"}),
    "highpass": frozenset({"frequency"}),
    "eq": frozenset({"low_freq", "high_freq"}),
}
#: Top-level numeric effects, in seconds.
_TOP_LEVEL_RANGES: dict[str, tuple[float, float]] = {"fade_in": (0.0, 600.0), "fade_out": (0.0, 600.0)}


def _invalid_effect(effect: str, param: str, expected: str) -> MCPVideoError:
    where = f"effects.{effect}.{param}" if param else f"effects.{effect}"
    return MCPVideoError(f"{where} must be {expected}", error_type="validation_error", code="invalid_parameter")


def _require_number(
    effect: str, param: str, value: Any, bounds: tuple[float | None, float | None], nyquist: float | None = None
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _invalid_effect(effect, param, "a finite number")
    low, high = bounds
    if (low is not None and value < low) or (high is not None and value > high):
        raise _invalid_effect(effect, param, f"between {low} and {high}")
    if nyquist is not None and not (0.0 < value < nyquist):
        raise _invalid_effect(effect, param, f"greater than 0 and below the Nyquist frequency ({nyquist:g} Hz)")


def validate_effect_values(effects: dict[str, Any] | None, sample_rate: int) -> None:
    """Reject effect parameters numpy would crash on, allocate wildly for, or silently ignore.

    Covers every effect shared by ``audio_synthesize``/``audio_preset`` and
    ``audio_effects``: unknown keys, non-numeric or non-finite values, values
    outside their range, misspelled enum members and cutoffs at or above
    Nyquist all raise ``validation_error`` before any DSP runs.
    """
    if not effects:
        return
    nyquist = sample_rate / 2.0
    for effect, spec in effects.items():
        if effect in _TOP_LEVEL_RANGES:
            _require_number(effect, "", spec, _TOP_LEVEL_RANGES[effect])
            continue
        if effect in ("lowpass", "highpass") and not isinstance(spec, dict):
            _require_number(effect, "frequency", spec, (None, None), nyquist)
            continue
        if not isinstance(spec, dict):
            raise _invalid_effect(effect, "", "a number or a dict of parameters")
        ranges = _EFFECT_PARAM_RANGES.get(effect, {})
        frequencies = _FREQUENCY_PARAMS.get(effect, frozenset())
        choices = _EFFECT_PARAM_CHOICES.get(effect, {})
        unknown = sorted(set(spec) - set(ranges) - frequencies - set(choices))
        if unknown:
            raise MCPVideoError(
                f"effects.{effect} does not accept parameter(s) {unknown}; "
                f"accepted: {sorted((*ranges, *frequencies, *choices))}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        for param, value in spec.items():
            if param in frequencies:
                _require_number(effect, param, value, (None, None), nyquist)
            elif param in ranges:
                _require_number(effect, param, value, ranges[param])
            elif value not in choices[param]:
                raise _invalid_effect(effect, param, f"one of {sorted(choices[param])}")


# Where a lowpass sweep ends when the caller gives no "to" (issue #843).
_SWEEP_DEFAULT_TO = {"sweep_down": 200.0, "sweep_up": 8000.0}


def _apply_lowpass_sweep(samples: Any, start: float, end: float, sample_rate: int) -> Any:
    """Lowpass whose cutoff glides exponentially from ``start`` to ``end`` Hz over the sound.

    Numpy-only: Hann-windowed STFT frames at 75% overlap, each multiplied by a
    2-pole Butterworth magnitude at that frame's cutoff, then overlap-added.
    """
    import numpy as np

    x = np.asarray(samples, dtype=np.float64)
    if x.size == 0:
        return samples
    nyq = sample_rate / 2.0
    start = float(min(max(start, 20.0), nyq * 0.95))
    end = float(min(max(end, 20.0), nyq * 0.95))
    n_fft, hop = 1024, 256
    win = np.hanning(n_fft + 1)[:-1]
    pad = np.concatenate([np.zeros(n_fft), x, np.zeros(n_fft)])
    out = np.zeros_like(pad)
    norm = np.zeros_like(pad)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    n_frames = 1 + (len(pad) - n_fft) // hop
    for k in range(n_frames):
        i = k * hop
        centre = min(max(i + n_fft // 2 - n_fft, 0), len(x) - 1)
        cutoff = start * (end / start) ** (centre / max(len(x) - 1, 1))
        mag = 1.0 / np.sqrt(1.0 + (freqs / cutoff) ** 4)
        frame = np.fft.irfft(np.fft.rfft(pad[i : i + n_fft] * win) * mag, n_fft)
        out[i : i + n_fft] += frame * win
        norm[i : i + n_fft] += win**2
    out = out / np.maximum(norm, 1e-12)
    return out[n_fft : n_fft + len(x)]


def _apply_filter_effects(
    samples: Any,
    effects: dict[str, Any],
    sample_rate: int,
) -> Any:
    """Apply lowpass, highpass, delay, chorus, flanger, distortion, tremolo, vibrato."""
    # Lowpass
    if "lowpass" in effects:
        lp = effects["lowpass"]
        cutoff = lp.get("frequency", 2000) if isinstance(lp, dict) else lp
        sweep = lp.get("type") if isinstance(lp, dict) else None
        if sweep in (None, "static"):
            samples = apply_lowpass(samples, cutoff, sample_rate)
        elif sweep in _SWEEP_DEFAULT_TO:
            samples = _apply_lowpass_sweep(samples, cutoff, lp.get("to", _SWEEP_DEFAULT_TO[sweep]), sample_rate)
        else:
            raise MCPVideoError(
                f"lowpass type must be one of {['static', *sorted(_SWEEP_DEFAULT_TO)]}",
                error_type="validation_error",
                code="invalid_parameter",
            )

    # Highpass
    if "highpass" in effects:
        hp = effects["highpass"]
        cutoff = hp.get("frequency", 200) if isinstance(hp, dict) else hp
        samples = apply_highpass(samples, cutoff, sample_rate)

    return samples


def _apply_modulation_effects(
    samples: Any,
    effects: dict[str, Any],
    sample_rate: int,
) -> Any:
    """Apply delay, chorus, flanger, distortion, tremolo, vibrato."""
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

    samples = _apply_filter_effects(samples, effects, sample_rate)
    samples = _apply_modulation_effects(samples, effects, sample_rate)

    return samples


def _validate_synth_params(
    frequency: float,
    duration: float,
    volume: float,
    sample_rate: int,
    effects: dict[str, Any] | None,
    stereo: bool = False,
) -> None:
    """Validate synthesis parameters and effect keys."""
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
    validate_effect_values(effects, sample_rate)

    # Reject synthesis that would allocate oversized in-memory buffers (H6).
    channels = 2 if stereo else 1
    total_samples = int(sample_rate * duration) * channels
    if total_samples > MAX_SYNTHESIS_SAMPLES:
        raise MCPVideoError(
            f"Synthesis would allocate {total_samples:,} samples (rate={sample_rate}, "
            f"duration={duration}s, channels={channels}), exceeding the "
            f"{MAX_SYNTHESIS_SAMPLES:,}-sample ceiling. Reduce duration or sample rate.",
            error_type="validation_error",
            code="synthesis_too_large",
        )


#: The waveforms this engine generates. The caller picks one; the
#: rejected name is never echoed back.
_WAVEFORMS = frozenset({"sine", "square", "sawtooth", "triangle", "noise", "pulse", "supersaw", "pluck", "fm"})


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
    _validate_synth_params(frequency, duration, volume, sample_rate, effects, stereo)

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
        raise MCPVideoError(
            f"Unknown waveform ({rejected_value(waveform)}). Available: {sorted(_WAVEFORMS)}",
            error_type="validation_error",
            code="invalid_parameter",
        )

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


def _apply_preset_controls(config: dict[str, Any], mult: float, intensity: float) -> None:
    """Apply ``pitch`` and ``intensity`` to a preset config, in place.

    ``intensity`` drives every preset the same way: loudness and effect wetness
    scale together around the authored values (0.5 = as authored, 0 = half,
    1 = 1.5x), so 0 is never silent. ``pitch`` shifts the frequency; a noise
    generator ignores frequency, so for noise the filter edges move instead
    and the parameter is not silently dropped.
    """
    config["frequency"] = config["frequency"] * mult
    scale = 0.5 + intensity
    config["volume"] = min(1.0, config["volume"] * scale)
    effects = config.get("effects") or {}
    for name in ("reverb", "delay", "chorus", "flanger"):
        wet = effects.get(name)
        if isinstance(wet, dict):
            for key in ("wet_level", "mix"):
                if key in wet:
                    wet[key] = min(1.0, wet[key] * scale)
    if config.get("waveform") != "noise":
        return
    ceiling = DEFAULT_SAMPLE_RATE / 2.0 * 0.95
    for name in ("lowpass", "highpass"):
        spec = effects.get(name)
        if isinstance(spec, dict):
            for key in ("frequency", "to"):
                if key in spec:
                    spec[key] = min(spec[key] * mult, ceiling)
        elif isinstance(spec, (int, float)):
            effects[name] = min(spec * mult, ceiling)


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
        pitch: Pitch variation (low/mid/high). Noise presets have no pitch to
            shift, so their filter edges move instead.
        duration: Override default duration
        intensity: Effect intensity 0-1. Scales loudness and effect wetness:
            0.5 is the preset as authored, 0 is half, 1 is 1.5x.
        stereo: Output stereo WAV
        pan: Stereo panning (-1 left to 1 right)

    Returns:
        Path to generated WAV file
    """
    from .presets import _PITCH_MULT, get_preset_config

    if pitch not in _PITCH_MULT:
        raise MCPVideoError(
            f"pitch must be one of {sorted(_PITCH_MULT)}, got {rejected_value(pitch)}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not isinstance(intensity, (int, float)) or not (0.0 <= intensity <= 1.0):
        raise MCPVideoError(
            f"intensity must be between 0 and 1, got {rejected_value(intensity)}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    config = get_preset_config(preset)
    if duration is not None:
        config["duration"] = duration
    _apply_preset_controls(config, _PITCH_MULT[pitch], float(intensity))

    return audio_synthesize(output=output, stereo=stereo, pan=pan, **config)
