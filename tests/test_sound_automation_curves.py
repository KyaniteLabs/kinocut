"""Independent frame and work-unit oracles for global parameter automation."""

import pytest

from kinocut_sound.mix.automation import CompiledAutomation
from kinocut_sound.mix._errors import MixError
from kinocut_sound.routing import AutomationEnvelope


def envelope(points, parameter="gain_db"):
    return AutomationEnvelope(
        target_track_id="voice",
        parameter=parameter,
        points=[{"time_seconds": frame / 1000, "value": value} for frame, value in points],
    )


def test_linear_values_and_both_endpoint_holds():
    compiled = CompiledAutomation((envelope([(2, -6), (4, 0), (6, 6)]),), 1000, 10, 1)
    cursor = compiled.by_track["voice"]["gain_db"].cursor(0)
    assert [cursor.value(frame) for frame in range(8)] == [-6, -6, -6, -3, 0, 3, 6, 6]
    other_clip = compiled.by_track["voice"]["gain_db"].cursor(5)
    assert [other_clip.value(frame) for frame in (5, 6, 7)] == [3, 6, 6]


def test_single_point_holds_value_before_and_after_its_time():
    compiled = CompiledAutomation((envelope([(5, -3)]),), 1000, 10, 1)
    cursor = compiled.by_track["voice"]["gain_db"].cursor(0)
    assert [cursor.value(frame) for frame in (0, 5, 10, 20)] == [-3] * 4


def test_end_boundary_is_not_last_emitted_frame():
    end = CompiledAutomation((envelope([(0, -6), (4, 0)]),), 1000, 4, 1)
    last = CompiledAutomation((envelope([(0, -6), (3, 0)]),), 1000, 4, 1)
    assert end.by_track["voice"]["gain_db"].cursor(0).value(3) == -1.5
    assert last.by_track["voice"]["gain_db"].cursor(0).value(3) == 0


def test_quantized_point_collisions_rejected():
    item = AutomationEnvelope(
        target_track_id="voice",
        parameter="gain_db",
        points=[
            {"time_seconds": 0.0001, "value": 0},
            {"time_seconds": 0.0002, "value": 1},
        ],
    )
    with pytest.raises(MixError):
        CompiledAutomation((item,), 1000, 10, 1)


@pytest.mark.parametrize(
    "points,parameter",
    [
        ([(11, 0)], "gain_db"),
        ([(0, 13)], "gain_db"),
        ([(0, 2)], "pan_position"),
        ([(0, 0)], "cutoff_hz"),
        ([(0, 1)], "pan_position"),
    ],
)
def test_unsupported_time_parameter_and_mono_intent(points, parameter):
    with pytest.raises(MixError):
        CompiledAutomation((envelope(points, parameter),), 1000, 10, 1)


def test_work_includes_compilation_cursor_points_and_repeated_clips():
    compiled = CompiledAutomation((envelope([(0, -6), (2, 0), (4, 6)]),), 1000, 10, 1)
    assert compiled.work_units({"a": 2}, {"a": "voice"}, 1) == 14
    assert compiled.work_units({"a": 2, "b": 1}, {"a": "voice", "b": "voice"}, 1) == 22
    two = CompiledAutomation(
        (envelope([(0, -6), (2, 0), (4, 6)]), envelope([(0, -1), (4, 1)], "pan_position")), 1000, 10, 2
    )
    assert two.work_units({"a": 2}, {"a": "voice"}, 2) == 30


def test_tiny_clip_with_max_points_still_has_cursor_work():
    compiled = CompiledAutomation((envelope([(frame, 0) for frame in range(4096)]),), 1000, 4095, 1)
    assert compiled.work_units({"a": 1}, {"a": "voice"}, 1) == 8209


@pytest.mark.parametrize("invalid", [True, 0, -1, 1.0])
def test_source_work_requires_positive_integer_frames(invalid):
    compiled = CompiledAutomation((envelope([(0, 0)]),), 1000, 10, 1)
    with pytest.raises(MixError):
        compiled.work_units({"a": invalid}, {"a": "voice"}, 1)
