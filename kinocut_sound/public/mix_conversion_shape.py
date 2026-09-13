"""Integer frame geometry and conservative sequential conversion admission."""

from dataclasses import dataclass

from kinocut_sound.limits import (
    MIN_MIX_SAMPLE_RATE_HZ,
    MAX_MIX_SAMPLE_RATE_HZ,
    MAX_MIX_MEMORY_BYTES,
    MAX_MIX_INPUT_BYTES,
    MAX_MIX_CONVERTED_BYTES,
    MAX_MIX_CONVERSION_WORK_UNITS,
    MIX_CONVERSION_STARTUP_WORK_UNITS,
    MIX_CONVERSION_NATIVE_MEMORY_BYTES,
    MIX_CONVERSION_METADATA_BYTES,
    MIX_CONVERSION_IO_BYTES,
)
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix._wav import wav_from_pcm
from kinocut_sound.public.mix_request import check_mix_resources


@dataclass(frozen=True)
class ConversionShape:
    source_frames: int
    source_rate: int
    target_rate: int
    channels: int
    target_frames: int
    guard_frames: int
    raw_min: int
    raw_max: int

    @property
    def changed(self):
        return self.source_rate != self.target_rate

    @property
    def raw_byte_limit(self):
        return 2 * self.channels * self.raw_max

    @property
    def work_units(self):
        if not self.changed:
            return self.channels * self.source_frames
        return (
            self.channels * (self.source_frames + self.guard_frames + self.raw_max) + MIX_CONVERSION_STARTUP_WORK_UNITS
        )

    def derived_bytes(self, original_bytes):
        if not self.changed:
            return original_bytes
        header = len(wav_from_pcm(b"", sample_rate_hz=self.target_rate, channel_count=self.channels))
        return header + 2 * self.channels * self.target_frames


def conversion_shape(source_frames, source_rate, target_rate, channels):
    if any(type(value) is not int for value in (source_frames, source_rate, target_rate, channels)):
        raise mix_error("conversion shape requires integer values", MIX_INPUT_INVALID)
    if source_frames < 1 or channels not in (1, 2):
        raise mix_error("conversion requires nonempty mono/stereo PCM16", MIX_INPUT_INVALID)
    if not all(MIN_MIX_SAMPLE_RATE_HZ <= rate <= MAX_MIX_SAMPLE_RATE_HZ for rate in (source_rate, target_rate)):
        raise mix_error("conversion sample rate exceeds limits", MIX_OVER_LIMIT)
    quotient, remainder = divmod(source_frames * target_rate, source_rate)
    target = quotient + int(2 * remainder > source_rate or (2 * remainder == source_rate and quotient % 2))
    if target < 1:
        raise mix_error("source is too short at the target rate", MIX_INPUT_INVALID)
    guard = (source_rate + target_rate - 1) // target_rate if source_rate != target_rate else 0
    lower, remainder = divmod((source_frames + guard) * target_rate, source_rate)
    return ConversionShape(
        source_frames, source_rate, target_rate, channels, target, guard, lower, lower + bool(remainder)
    )


class ConversionAdmission:
    def __init__(self, request):
        self.request = request
        self.original_total = self.derived_total = self.work = 0

    def add(self, original_bytes, shape):
        if type(original_bytes) is not int or original_bytes < 1:
            raise mix_error("conversion source byte count must be a positive integer", MIX_INPUT_INVALID)
        derived = shape.derived_bytes(original_bytes)
        self.original_total += original_bytes
        self.derived_total += derived
        self.work += shape.work_units
        parent = (
            original_bytes
            + 4 * shape.channels * shape.source_frames
            + 4 * shape.raw_byte_limit
            + 4 * derived
            + MIX_CONVERSION_NATIVE_MEMORY_BYTES
            + MIX_CONVERSION_METADATA_BYTES
            + MIX_CONVERSION_IO_BYTES
        )
        if parent > MAX_MIX_MEMORY_BYTES:
            raise mix_error("conversion exceeds parent memory estimate", MIX_OVER_LIMIT)
        if (
            self.original_total > MAX_MIX_INPUT_BYTES
            or self.derived_total > MAX_MIX_CONVERTED_BYTES
            or self.work > MAX_MIX_CONVERSION_WORK_UNITS
        ):
            raise mix_error("conversion exceeds input, derived or work limits", MIX_OVER_LIMIT)
        check_mix_resources(self.request, self.derived_total)


def check_conversion_resources(request, sources):
    admission = ConversionAdmission(request)
    for original_bytes, shape in sources:
        admission.add(original_bytes, shape)
