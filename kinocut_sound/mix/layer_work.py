"""Shared structural layer fill/duck work arithmetic, independent of PCM buffers."""

from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix.layers import fill_plan
from kinocut_sound.world.layers import LayerStack


def layer_work_units(layers, source_frames, target_frames, channels, *, ducking=False):
    if len(layers) != len(source_frames):
        raise mix_error("layer work requires every source frame count", MIX_INPUT_INVALID)
    states = LayerStack(tuple(item.layer for item in layers)).mix()
    work = 0
    for item, state, frames in zip(layers, states, source_frames, strict=True):
        fill = fill_plan(frames, target_frames, item.fill_mode, item.crossfade_frames)
        work += frames * channels
        if state.audible:
            work += channels * (fill["copies"] * min(frames, target_frames) + (4 if ducking else 2) * target_frames)
    if ducking and not any(state.audible for state in states):
        work += target_frames * channels
    return work
