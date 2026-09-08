"""Ordered PCM16 ambient layers with explicit, frame-based fill."""

from array import array
from dataclasses import dataclass

from kinocut_sound.limits import MAX_AMBIENT_EXTRA_REPEATS
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.mix.pcm_ops import _scale_in_place, _overlay
from kinocut_sound.validation import PCM_MIX_CHANNEL_COUNTS
from kinocut_sound.world.layers import AmbientLayer, LayerStack


@dataclass(frozen=True)
class MixLayer:
    layer: AmbientLayer
    wav_bytes: bytes
    fill_mode: str
    crossfade_frames: int | None


def fill_plan(source_frames, target_frames, mode, crossfade_frames):
    if any(type(n) is not int or n < 1 for n in (source_frames, target_frames)):
        raise mix_error("layer source and target require positive frame counts", MIX_INPUT_INVALID)
    extra, step = 0, None
    if mode == "pad":
        if crossfade_frames is not None:
            raise mix_error("padded layers cannot declare loop crossfades", MIX_INPUT_INVALID)
    elif mode == "loop":
        if type(crossfade_frames) is not int or not 1 <= crossfade_frames < source_frames:
            raise mix_error("loop crossfade must be positive and shorter than source", MIX_INPUT_INVALID)
        step = source_frames - crossfade_frames
        extra = max(0, (target_frames - source_frames + step - 1) // step)
        if extra > MAX_AMBIENT_EXTRA_REPEATS:
            raise mix_error("layer repeat count exceeds limit", MIX_OVER_LIMIT)
    else:
        raise mix_error("unknown layer fill mode", MIX_INPUT_INVALID)
    return {
        "source_frames": source_frames,
        "target_frames": target_frames,
        "crossfade_frames": crossfade_frames,
        "step_frames": step,
        "copies": extra + 1,
        "last_seam_start_frame": extra * step if extra else None,
        "last_seam_end_frame": extra * step + crossfade_frames if extra else None,
    }


def fill_layer(samples, channels, target_frames, mode, crossfade_frames):
    if type(channels) is not int or channels not in PCM_MIX_CHANNEL_COUNTS or len(samples) % channels:
        raise mix_error("layer PCM requires complete mono/stereo frames", MIX_INPUT_INVALID)
    source_frames = len(samples) // channels
    plan = fill_plan(source_frames, target_frames, mode, crossfade_frames)
    canvas = array("h", [0]) * (target_frames * channels)
    count = min(len(samples), len(canvas))
    canvas[:count] = samples[:count]
    for repeat in range(1, plan["copies"]):
        start = repeat * plan["step_frames"]
        for frame in range(min(source_frames, target_frames - start)):
            alpha = (frame + 1) / crossfade_frames if frame < crossfade_frames else 1
            for channel in range(channels):
                index = (start + frame) * channels + channel
                value = samples[frame * channels + channel]
                if alpha != 1:
                    value = round(canvas[index] * (1 - alpha) + value * alpha)
                canvas[index] = max(-32768, min(32767, value))
    return canvas


def _decode_layer(item, sample_rate_hz, channels, target_frames):
    samples, rate, actual_channels = decode_pcm_wav(item.wav_bytes)
    if rate != sample_rate_hz or actual_channels != channels:
        raise mix_error("layer source format mismatch", MIX_INPUT_INVALID)
    fill_plan(len(samples) // channels, target_frames, item.fill_mode, item.crossfade_frames)
    return samples


def apply_layers(canvases, layers, sample_rate_hz, channels):
    """Validate every source, add one layer scratch at a time, return shapes."""
    if not layers:
        return ()
    if "ambience" not in canvases:
        raise mix_error("layers require an ambience stem", MIX_INPUT_INVALID)
    stack = LayerStack(tuple(item.layer for item in layers))
    target_frames = len(canvases["ambience"]) // channels
    source_frames = []
    for item, state in zip(layers, stack.mix(), strict=True):
        samples = _decode_layer(item, sample_rate_hz, channels, target_frames)
        frames = len(samples) // channels
        source_frames.append(frames)
        if state.audible:
            _scale_in_place(samples, (10 ** (state.effective_gain_db / 20),) * channels)
            filled = fill_layer(samples, channels, target_frames, item.fill_mode, item.crossfade_frames)
            _overlay(canvases["ambience"], filled, 0)
            del filled
    return tuple(source_frames)
