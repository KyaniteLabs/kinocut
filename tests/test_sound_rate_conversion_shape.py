"""Rational frame bounds, not backend floating-point tie behavior."""

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_conversion_shape import conversion_shape


@pytest.mark.parametrize(
    "source,rate,target,expected",
    [
        (240, 48000, 44100, 220),
        (5, 48000, 24000, 2),
        (3, 48000, 24000, 2),
        (101, 44100, 48000, 110),
        (1, 8000, 96000, 12),
        (4800, 48000, 48000, 4800),
    ],
)
def test_exact_rational_target_and_guard_envelope(source, rate, target, expected):
    shape = conversion_shape(source, rate, target, 2)
    assert shape.target_frames == expected
    assert shape.raw_min >= expected and shape.raw_max - shape.raw_min <= 1
    assert shape.guard_frames == ((rate + target - 1) // target if rate != target else 0)
    assert shape.derived_bytes(123) == (123 if rate == target else 44 + 4 * expected)


@pytest.mark.parametrize(
    "args",
    [
        (1, 48000, 24000, 1),
        (0, 48000, 24000, 1),
        (True, 48000, 24000, 1),
        (5, 48000.0, 24000, 1),
        (5, 48000, 24000, True),
        (5, 48000, 24000, 6),
        (5, 7999, 24000, 1),
        (5, 48000, 96001, 1),
    ],
)
def test_invalid_or_subframe_conversion_rejected(args):
    with pytest.raises(MixError):
        conversion_shape(*args)
