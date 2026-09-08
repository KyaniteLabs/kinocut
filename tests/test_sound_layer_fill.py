"""Exact frame oracles for actual ambient fill, independent of receipt claims."""

from array import array

import pytest


@pytest.mark.parametrize(
    "source,target,mode,crossfade,expected",
    [
        ([1000, -2000], 4, "pad", None, [1000, -2000, 0, 0]),
        ([1000, -2000, 3000], 2, "pad", None, [1000, -2000]),
        ([1000, 2000, -3000, -4000], 6, "loop", 2, [1000, 2000, -1000, 2000, -3000, -4000]),
        ([1000, 2000, -3000, -4000], 7, "loop", 1, [1000, 2000, -3000, 1000, 2000, -3000, -4000]),
        ([1000, 2000, 3000], 5, "loop", 2, [1000, 1500, 1500, 2000, 3000]),
        ([1000, 2000, -3000, -4000], 5, "loop", 2, [1000, 2000, -1000, 2000, -3000]),
        ([1000, 2000, 3000], 2, "loop", 1, [1000, 2000]),
    ],
)
def test_exact_fill_samples(source, target, mode, crossfade, expected):
    from kinocut_sound.mix.layers import fill_layer

    assert list(fill_layer(array("h", source), 1, target, mode, crossfade)) == expected


def test_stereo_uses_shared_frame_weights():
    from kinocut_sound.mix.layers import fill_layer

    samples = array("h", [1000, -1000, 2000, -2000, -3000, 3000, -4000, 4000])
    assert list(fill_layer(samples, 2, 6, "loop", 2)) == [
        1000,
        -1000,
        2000,
        -2000,
        -1000,
        1000,
        2000,
        -2000,
        -3000,
        3000,
        -4000,
        4000,
    ]


@pytest.mark.parametrize("crossfade", [None, False, True, 0, -1, 3, 4, 1.5, "1"])
def test_invalid_loop_crossfade_rejected(crossfade):
    from kinocut_sound.mix.layers import fill_plan
    from kinocut_sound.mix._errors import MixError

    with pytest.raises(MixError):
        fill_plan(3, 8, "loop", crossfade)


def test_repeat_limit_and_zero_target_rejected_before_allocation():
    from kinocut_sound.mix.layers import fill_plan
    from kinocut_sound.mix._errors import MixError

    assert fill_plan(2, 10002, "loop", 1)["copies"] == 10001
    with pytest.raises(MixError):
        fill_plan(2, 10003, "loop", 1)
    with pytest.raises(MixError):
        fill_plan(2, 0, "pad", None)
