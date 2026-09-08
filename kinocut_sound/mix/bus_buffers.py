"""Owned PCM16 bus buffers and read-only internal snapshots."""

from array import array

from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error


def validate_bus_canvases(canvases, bus_ids, frame_count, channels):
    if not isinstance(canvases, dict) or set(canvases) != set(bus_ids):
        raise mix_error("bus canvases must match declared buses", MIX_INPUT_INVALID)
    expected = frame_count * channels
    if any(
        type(samples) is not array or samples.typecode != "h" or len(samples) != expected
        for samples in canvases.values()
    ):
        raise mix_error("bus canvases require matching PCM16 frames", MIX_INPUT_INVALID)
    if len({id(samples) for samples in canvases.values()}) != len(canvases):
        raise mix_error("bus canvases must not alias one another", MIX_INPUT_INVALID)


def readonly_pcm_snapshot(samples):
    return memoryview(samples.tobytes()).cast("h")
