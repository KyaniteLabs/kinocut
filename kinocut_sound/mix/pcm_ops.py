"""Shared PCM16 saturation and wide-accumulator gain arithmetic for mixing."""

from array import array


def _clamp_pcm16(value: float | int) -> int:
    return max(-32768, min(32767, round(value)))


def _quantize_pcm16(samples) -> array:
    if isinstance(samples, array) and samples.typecode == "h":
        return samples
    return array("h", (_clamp_pcm16(sample) for sample in samples))


def _is_pcm16_array(samples) -> bool:
    return isinstance(samples, array) and samples.typecode == "h"


def _add_sample(base, value):
    return max(-32768, min(32767, base + value))


def _overlay(canvas, clip, start):
    clamped = _is_pcm16_array(canvas)
    limit = len(canvas)
    for i, value in enumerate(clip):
        index = start + i
        if 0 <= index < limit:
            canvas[index] = _add_sample(canvas[index], value) if clamped else canvas[index] + value


def _scale_sample(sample, factor):
    return max(-32768, min(32767, round(sample * factor)))


def _scale_in_place(samples, factors):
    if all(factor == 1 for factor in factors):
        return
    channels = len(factors)
    if _is_pcm16_array(samples):
        for i, sample in enumerate(samples):
            samples[i] = _scale_sample(sample, factors[i % channels])
    else:
        for i, sample in enumerate(samples):
            samples[i] = sample * factors[i % channels]


def _overlay_scaled(canvas, source, factor):
    if _is_pcm16_array(canvas):
        for index, sample in enumerate(source):
            canvas[index] = _add_sample(canvas[index], _scale_sample(sample, factor))
    else:
        for index, sample in enumerate(source):
            canvas[index] = canvas[index] + round(sample * factor)
