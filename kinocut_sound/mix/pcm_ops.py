"""Shared PCM16 saturation and gain arithmetic for mixing."""


def _overlay(canvas, clip, start):
    for i, value in enumerate(clip):
        index = start + i
        if 0 <= index < len(canvas):
            canvas[index] = max(-32768, min(32767, canvas[index] + value))


def _scale_sample(sample, factor):
    return max(-32768, min(32767, round(sample * factor)))


def _scale_in_place(samples, factors):
    if all(factor == 1 for factor in factors):
        return
    channels = len(factors)
    for i, sample in enumerate(samples):
        samples[i] = _scale_sample(sample, factors[i % channels])
