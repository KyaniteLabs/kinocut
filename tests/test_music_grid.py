import struct
import wave
import json
import subprocess
import sys

import pytest

from kinocut.engine_edit import _time_to_seconds, trim
from kinocut.errors import MCPVideoError
from kinocut.music_grid import (
    FINE_GRID_384,
    MicrotimingConfig,
    MusicalGrid,
    TimingCurve,
    estimate_bpm_from_audio,
    lint_composition_keyframes,
    place_rhythm_cell,
    quantize_real_timestamps,
    snap_duration_to_grid,
    validate_edit_points,
)
import itertools


def test_coordinate_system_and_frame_residual():
    grid = MusicalGrid(126, offset_s=0.512)
    assert grid.parse_time("1:1:0") == 0.512
    assert grid.parse_time("3:3:0") == pytest.approx(0.512 + 10 * 60 / 126)
    assert grid.parse_time("tc:1:2:3") == grid.parse_time("tc:01:02:03") == 3723
    assert grid.parse_time("3:12.5") == 192.5
    cut = grid.cut("1:2:0")
    assert cut["frame"] == 30
    assert cut["final_time"] == grid.frame_to_seconds(30) == 1
    assert cut["residual_ms"] == pytest.approx((1 - 0.512 - 60 / 126) * 1000)
    assert MusicalGrid(120, fps=10).time_to_frame(-0.05) == -1
    assert MusicalGrid(120, fps=10).time_to_frame(0.05) == 1


def test_resolution_validation():
    with pytest.warns(UserWarning, match="floor"):
        grid = MusicalGrid(126, steps_per_bar=FINE_GRID_384)
    grid.validate_note_values([16, 64, 96, 128])
    assert grid.step_ms == pytest.approx(60000 / 126 * 4 / 384)
    with pytest.raises(MCPVideoError, match=r"16.*remainder 8") as caught:
        MusicalGrid(126, steps_per_bar=264).validate_note_values([16])
    assert caught.value.code == "invalid_grid_resolution"


def test_drift_threshold_and_signed_offsets():
    result = validate_edit_points([0.502, 0.497], MusicalGrid(120), tolerance_ms=2)
    assert [row["passed"] for row in result["points"]] == [True, False]
    assert [row["residual_ms"] for row in result["points"]] == [2, -3]
    assert not result["passed"]


def test_bounded_audio_estimation(tmp_path):
    path = tmp_path / "click.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes((struct.pack("<h", 18000) * 80 + bytes(3920 * 2)) * 12)
    assert estimate_bpm_from_audio(path) == pytest.approx(120, abs=1)


def test_real_musical_trim(sample_video, tmp_path):
    output = tmp_path / "bars.mp4"
    result = trim(sample_video, start="1:1:4", end="2:1:4", bpm=120, offset_s=0.1, output_path=str(output))
    assert result.duration == pytest.approx(2, abs=0.1)
    assert any("start: frame=7" in text and "residual_ms=" in text for text in result.warnings)
    assert any("end: frame=67" in text for text in result.warnings)
    assert _time_to_seconds("1:1:0") == 3660
    assert _time_to_seconds("1:1:0", bpm=120) == 0


def test_microtiming_and_gain():
    grid = MusicalGrid(120)
    timing = MicrotimingConfig(swing_pct=56, offset_ms=-2, accent_pattern=(3, 0))
    assert timing.apply(0, grid, gain_db=-6)["gain_db"] == -3
    assert timing.apply(2, grid)["accent_db"] == 3
    assert timing.apply(grid.slot_time(1), grid)["accent_db"] == 0
    off = timing.apply(0.125, grid)
    assert off["nominal_time"] == 0.125
    assert off["swing_ms"] == pytest.approx(15)
    assert off["final_time"] == pytest.approx(0.138)
    nominal = 0.121232334
    assert MicrotimingConfig().apply(nominal, grid)["final_time"].hex() == nominal.hex()


@pytest.mark.parametrize(("shape", "expected"), [("stepped", [15, 10, 5, 0, 0]), ("linear", [15, 11.25, 7.5, 3.75, 0])])
def test_offset_curve_section_origin(shape, expected):
    config = MicrotimingConfig(curve=TimingCurve(15, 0, 8, shape))
    assert [
        config.apply(6 + 4 * index, MusicalGrid(120), section_start_bar=4)["offset_ms"] for index in range(5)
    ] == expected


@pytest.mark.parametrize(("strength", "expected"), [(0, 0.02), (50, 0.025625), (100, 0.03125)])
def test_partial_quantization(strength, expected):
    row = quantize_real_timestamps([0, "20ms"], MusicalGrid(120), quantize_strength=strength)["events"][1]
    assert row == pytest.approx(
        dict(
            source_time=0.02,
            mapped_time=0.02,
            final_time=expected,
            strength=strength,
            residual_ms=(expected - 0.03125) * 1000,
        )
    )


def test_log_privacy_scaling_and_strength_curve():
    class Record(dict):
        def __getitem__(self, key):
            assert key != "message"
            return super().__getitem__(key)

    records = [Record(timestamp="1970-01-01T00:00:01Z", message="private"), Record(timestamp_ms=5000), Record(time_s=9)]
    result = quantize_real_timestamps(
        records, MusicalGrid(120), strength_curve=TimingCurve(20, 100, 2), target_duration_s=4, start_time_s=3
    )
    assert result["time_scale"] == 0.5
    assert [row["strength"] for row in result["events"]] == [20, 60, 100]
    assert [row["mapped_time"] for row in result["events"]] == [3, 5, 7]
    assert "private" not in repr(result)


def test_collisions_and_order():
    result = quantize_real_timestamps([0, 0.001, 0.002], MusicalGrid(120))
    assert result["collisions"] == [(0, 1), (1, 2)]
    assert [row["final_time"] for row in result["events"]] == [0, 0, 0]
    with pytest.raises(ValueError, match="non-decreasing"):
        quantize_real_timestamps([2, 1], MusicalGrid(120))


def test_duration_ignores_offset():
    slot, snapped, residual = snap_duration_to_grid(1.8, MusicalGrid(126, offset_s=0.512))
    assert slot == 60
    assert snapped == pytest.approx(1.785714, abs=1e-6)
    assert residual == pytest.approx(14.285714, abs=1e-6)


def test_changing_strength_holds_crossing_events_in_input_order():
    result = quantize_real_timestamps(
        [0, 0.0001], MusicalGrid(120), start_time_s=0.014, strength_curve=TimingCurve(0, 100, 0.00005)
    )
    assert [row["source_time"] for row in result["events"]] == [0, 0.0001]
    assert [row["final_time"] for row in result["events"]] == [0.014, 0.014]
    assert result["collisions"] == [(0, 1)]


def test_empty_or_dynamic_composition_does_not_pass():
    assert not lint_composition_keyframes("<body></body>", MusicalGrid(120))["passed"]
    report = lint_composition_keyframes("gsap.to(node, {duration: compute})", MusicalGrid(120))
    assert not report["passed"] and report["errors"]


def test_keyframe_sources():
    html = """<div id="logo" data-start="0.5" data-duration="0.125"></div>
    <script>gsap.to("dolly", {duration: 0.4, delay: 0.5});</script>
    <style>@keyframes fade {from {opacity:0} 25% {opacity:.1} to {opacity:1}}
    .logo {animation-name: fade; animation-duration: 500ms; animation-delay: 1s}</style>"""
    rows = lint_composition_keyframes(html, MusicalGrid(120))
    assert not rows["passed"]
    indexed = {row["name"]: row for row in rows["keyframes"]}
    assert indexed["dolly.end"]["residual_ms"] == pytest.approx(-6.25)
    assert indexed["fade.25%"]["time"] == 1.125
    assert indexed["logo.end"]["time"] == 0.625
    events = [
        dict(name="camera", start=0.125, ease=0.25, end=0.5),
        dict(name="logo", fade_in=1, fade_out=2, fade_end=3),
    ]
    lint = lint_composition_keyframes(events, MusicalGrid(120))
    assert lint["passed"]
    assert {row["name"] for row in lint["keyframes"]} >= {
        "camera.ease",
        "logo.fade_in",
        "logo.fade_out",
        "logo.fade_end",
    }


@pytest.mark.parametrize(
    ("cell", "slots"),
    [
        ("straight", list(range(0, 128, 16))),
        ("tresillo", [0, 24, 48, 64, 88, 112]),
        ("son_clave", [0, 24, 48, 80, 96]),
        ("push", [24, 56, 88, 120]),
        ("off_beat", list(range(8, 128, 16))),
        ([0, 7, 10], [0, 7, 10]),
    ],
)
def test_paired_phrase(cell, slots):
    names = [f"flip_{index}" for index in range(len(slots))]
    receipt = place_rhythm_cell(
        cell, MusicalGrid(120), start_bar=2, events=names, sfx="click", microtiming=MicrotimingConfig(offset_ms=4)
    )
    picture, sound = receipt["picture_events"], receipt["sfx_events"]
    assert [hit["event"] for hit in picture] == names
    assert [hit["event"] for hit in sound] == ["click"] * len(slots)
    assert [hit["slot"] for hit in picture] == [64 + slot for slot in slots]
    assert (
        [hit["final_time"] for hit in picture]
        == [hit["final_time"] for hit in sound]
        == [2 + slot / 32 + 0.004 for slot in slots]
    )


@pytest.mark.parametrize("value", ["0:1:0", "1:0:0", "1:1:-1", "1:1:0.5", "1:x:0", "1:5:0", "1:1:16", "01:02:03"])
def test_invalid_musical_triples_never_become_clock_times(value):
    with pytest.raises(ValueError):
        MusicalGrid(120).parse_time(value)


def test_negative_authored_start(sample_video):
    with pytest.raises(MCPVideoError, match="Invalid musical"):
        trim(sample_video, start=-0.01, bpm=120)


@pytest.mark.parametrize(
    "unsupported",
    [
        "<script>gsap.timeline().to(node,{duration: dynamic})</script>",
        "<script>node.animate(frames, 50)</script>",
        "<style>.box {animation: fade 1s}</style>",
        "<script>gsap.to(box,{duration:1,repeat:2})</script>",
        '<svg><animateMotion dur="13ms"/></svg>',
        "<style>.box {animation-name: missing; animation-duration: 1s}</style>",
    ],
)
def test_unsupported_timing_cannot_hide_behind_valid_timing(unsupported):
    report = lint_composition_keyframes('<div data-start="0"></div>' + unsupported, MusicalGrid(120))
    assert not report["passed"] and report["errors"]


def test_cross_style_block_keyframes_are_resolved():
    html = (
        "<style>@keyframes pulse { 13% { opacity: 1; } }</style>"
        "<style>.box { animation-name: pulse; animation-duration: 1s; }</style>"
    )
    report = lint_composition_keyframes(html, MusicalGrid(120), tolerance_ms=0)
    assert not report["passed"]
    assert any(row["name"] == "pulse.13%" and not row["passed"] for row in report["keyframes"])
    comment_split = (
        '<div data-start="0"></div>'
        "<style>/* unclosed</style>"
        "<style>@keyframes pulse { 13% { opacity: 1; } } .box { animation-name: pulse; animation-duration: 1s; }</style>"
    )
    bad_report = lint_composition_keyframes(comment_split, MusicalGrid(120), tolerance_ms=0)
    assert not bad_report["passed"] and bad_report["errors"]


@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), float("-inf"), "Infinity", "-Infinity", "NaN"])
def test_timeline_grid_rejects_non_finite_times(bad_time):
    from kinocut.models import Timeline
    from pydantic import ValidationError

    for payload in (
        {
            "grid": {"bpm": 120},
            "tracks": [{"type": "video", "clips": [{"source": "clip.mp4", "trim_start": bad_time}]}],
        },
        {"grid": {"bpm": 120}, "tracks": [{"type": "video", "clips": [{"source": "clip.mp4", "volume": bad_time}]}]},
        {"grid": {"bpm": 120}, "tracks": [{"type": "image", "images": [{"source": "logo.png", "opacity": bad_time}]}]},
    ):
        with pytest.raises((ValueError, ValidationError)):
            Timeline.model_validate(payload)


def test_decimal_endpoint_and_linter_exit_status(tmp_path):
    path = tmp_path / "events.json"
    command = [sys.executable, "-m", "kinocut.music_grid", str(path), "--bpm", "150", "--tolerance-ms", "0"]
    path.write_text('[{"start":0.1,"duration":0.2}]')
    report = json.loads(subprocess.check_output(command))
    assert report["keyframes"][-1]["time"] == 0.3
    assert report["keyframes"][-1]["residual_ms"] == 0
    path.write_text('[{"time":0.001}]')
    assert subprocess.run(command).returncode == 1


def test_swing_warp_is_increasing_and_section_relative():
    grid = MusicalGrid(120, steps_per_bar=384, floor_ms=0)
    config = MicrotimingConfig(swing_curve=TimingCurve(56, 70, 1))
    times = [config.apply(grid.slot_time(slot), grid, section_start_bar=2) for slot in range(810)]
    assert all(left["final_time"] < right["final_time"] for left, right in itertools.pairwise(times))
    assert times[408]["swing_ms"] == pytest.approx(15)
    assert times[792]["swing_ms"] == pytest.approx(50)


def test_timeline_json_musical_context():
    from kinocut.models import Timeline
    from pydantic import ValidationError

    tracks = [{"type": "video", "clips": [{"source": "clip.mp4", "start": "1:2:0", "duration": "1:2:0"}]}]
    with pytest.raises(ValidationError):
        Timeline.model_validate_json(json.dumps({"tracks": tracks}))
    clip = (
        Timeline.model_validate_json(json.dumps({"grid": {"bpm": 120, "offset_s": 0.25}, "tracks": tracks}))
        .tracks[0]
        .clips[0]
    )
    assert (clip.start, clip.duration) == (0.75, 0.5)


def test_trim_cli_grid_flags():
    from kinocut.cli.parser import build_parser

    args = build_parser().parse_args(["trim", "a.mp4", "--bpm", "120", "--offset", "0.25", "--fps", "24"])
    assert (args.bpm, args.offset, args.fps) == (120, 0.25, 24)


def test_space_separated_iso_and_millisecond_bool():
    grid = MusicalGrid(120)
    for convert in (grid.slot_time, grid.frame_to_seconds, grid.time_to_frame):
        with pytest.raises(ValueError):
            convert(True)
    assert quantize_real_timestamps(["1970-01-01 00:00:01"], grid)["events"][0]["source_time"] == 1
    with pytest.raises(ValueError):
        quantize_real_timestamps([{"time_ms": True}], grid)
    for key in ("quantize_strength", "target_duration_s", "start_time_s"):
        with pytest.raises(ValueError):
            quantize_real_timestamps([], grid, **{key: True})


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_invalid_microtiming_numbers(value):
    for key in ("gain_db", "section_start_bar"):
        with pytest.raises(ValueError):
            MicrotimingConfig().apply(0, MusicalGrid(120), **{key: value})
    with pytest.raises(ValueError):
        TimingCurve(value, 50, 1)
    with pytest.raises(ValueError):
        MicrotimingConfig(swing_pct=value)
