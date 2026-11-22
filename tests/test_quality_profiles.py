"""Content profiles for video-quality-check / release-checkpoint (#679)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from kinocut.errors import MCPVideoError
from kinocut.quality_profiles import QUALITY_PROFILES, resolve_quality_profile

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _render(path, video_filter: str, base: str = "0x1e1e1e") -> str:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={base}:s=640x360:d=2:r=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-vf", video_filter, "-pix_fmt", "yuv420p", "-shortest", str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    return str(path)


# Dark editor UI: dark ground, a lighter sidebar and panel, rows of light "text".
_DARK_UI = ",".join(
    ["drawbox=x=0:y=0:w=140:h=360:color=0x252526:t=fill", "drawbox=x=160:y=20:w=460:h=320:color=0x2d2d30:t=fill"]
    + [f"drawbox=x=180:y={40 + i * 22}:w={200 + (i * 37) % 200}:h=6:color=0xd4d4d4:t=fill" for i in range(13)]
    + [f"drawbox=x=16:y={30 + i * 26}:w=100:h=6:color=0x9a9a9a:t=fill" for i in range(12)]
)


@pytest.fixture(scope="module")
def dark_ui(tmp_path_factory):
    return _render(tmp_path_factory.mktemp("ui") / "dark_ui.mp4", _DARK_UI)


@pytest.fixture(scope="module")
def blank_dark(tmp_path_factory):
    return _render(tmp_path_factory.mktemp("ui") / "blank.mp4", "null")


@pytest.fixture(scope="module")
def black(tmp_path_factory):
    return _render(tmp_path_factory.mktemp("ui") / "black.mp4", "null", base="black")


def test_default_band_scores_match_previous_formulas():
    default = QUALITY_PROFILES["default"]
    for y in (0, 16, 40, 90, 128, 200, 235, 255):
        assert default.brightness.score(y) == float(max(0, 100 - (abs(y - 128) / 128) * 100))
    for v in (0, 5, 20, 50, 80, 100, 130):
        old = float(max(0, 100 - (abs(v - 50) / 50) * 100))
        assert default.contrast.score(v) == old
        assert default.saturation.score(v) == old


def test_unknown_profile_is_a_validation_error():
    with pytest.raises(MCPVideoError) as exc:
        resolve_quality_profile("ui-capture-neon")
    assert exc.value.code == "invalid_parameter"
    assert "ui-capture-dark" in str(exc.value)


def test_mcp_tools_reject_unknown_profile(tmp_path):
    from kinocut.server_tools_ai import video_quality_check, video_release_checkpoint

    for result in (
        video_quality_check(str(tmp_path / "x.mp4"), profile="bogus"),
        video_release_checkpoint(str(tmp_path / "x.mp4"), profile="bogus"),
    ):
        assert result["success"] is False
        assert "profile" in result["error"]["message"]


def test_cli_profile_flag_choices():
    from kinocut.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(["video-quality-check", "in.mp4", "--profile", "ui-capture-dark"])
    assert args.profile == "ui-capture-dark"
    args = parser.parse_args(["release-checkpoint", "in.mp4"])
    assert args.profile == "default"
    with pytest.raises(SystemExit):
        parser.parse_args(["video-quality-check", "in.mp4", "--profile", "bogus"])


@needs_ffmpeg
def test_default_report_records_default_profile(dark_ui):
    from kinocut.quality_guardrails import quality_check

    report = quality_check(dark_ui)
    assert report["profile"]["name"] == "default"
    assert report["profile"]["visual_checks_gate"] is False
    assert report["profile"]["bands"]["brightness"]["optimum"] == 128


@needs_ffmpeg
def test_dark_ui_capture_fails_default_but_passes_dark_profile(dark_ui):
    from kinocut.quality_guardrails import assert_quality, quality_check

    default = {c["name"]: c for c in quality_check(dark_ui)["checks"]}
    assert not default["saturation"]["passed"]  # a neutral UI palette reads as "desaturated"
    with pytest.raises(MCPVideoError):
        assert_quality(dark_ui)

    report = assert_quality(dark_ui, profile="ui-capture-dark", profile_reason="dark editor screen recording")
    checks = {c["name"]: c for c in report["checks"]}
    assert report["gate_passed"] is True, checks
    for name in ("brightness", "contrast", "saturation"):
        assert checks[name]["passed"] is True, checks[name]
    assert report["profile"]["name"] == "ui-capture-dark"
    assert report["profile"]["bands"]["brightness"]["target_min"] == 20


@needs_ffmpeg
def test_profile_switch_reports_the_default_score_beside_it(dark_ui):
    from kinocut.quality_guardrails import assert_quality, quality_check

    default_report = quality_check(dark_ui)
    report = assert_quality(dark_ui, profile="ui-capture-dark", profile_reason="dark editor screen recording")
    baseline = report["profile_baseline"]
    assert baseline["profile"] == "default"
    assert baseline["overall_score"] == default_report["overall_score"]
    assert "saturation" in baseline["failed_checks"]
    assert baseline["overall_score"] < report["overall_score"]
    assert "profile_baseline" not in default_report


@needs_ffmpeg
def test_profile_switch_without_a_reason_keeps_the_gate_failed(dark_ui):
    """#759: a cut that fails on default can't pass by re-running on another profile."""
    from kinocut.quality_guardrails import assert_quality, quality_check

    default_score = quality_check(dark_ui)["overall_score"]
    profile_score = quality_check(dark_ui, profile="ui-capture-dark")["overall_score"]
    with pytest.raises(MCPVideoError) as exc:
        assert_quality(dark_ui, profile="ui-capture-dark")
    message = str(exc.value)
    assert "profile_reason" in message
    assert f"{default_score:.1f}" in message and f"{profile_score:.1f}" in message

    report = assert_quality(dark_ui, profile="ui-capture-dark", profile_reason="  dark editor screen recording  ")
    override = report["profile_override"]
    assert override["reason"] == "dark editor screen recording"
    assert override["profile"] == "ui-capture-dark"
    assert override["default_score"] == default_score
    assert override["profile_score"] == report["overall_score"]
    assert "saturation" in override["default_failed_checks"]


@needs_ffmpeg
def test_blank_reason_does_not_count(dark_ui):
    from kinocut.quality_guardrails import assert_quality

    with pytest.raises(MCPVideoError):
        assert_quality(dark_ui, profile="ui-capture-dark", profile_reason="   ")


@needs_ffmpeg
def test_release_checkpoint_refuses_an_unexplained_profile_switch(dark_ui, tmp_path):
    from kinocut.server_tools_ai import video_release_checkpoint

    result = video_release_checkpoint(dark_ui, output_dir=str(tmp_path / "review"), profile="ui-capture-dark")
    assert result["success"] is False
    assert "profile_reason" in str(result)
    assert not (tmp_path / "review").exists()


@needs_ffmpeg
def test_cli_table_names_the_default_score_under_a_profile(dark_ui):
    from kinocut.cli.quality_formatting import quality_report_renderables
    from kinocut.quality_guardrails import quality_check

    table, _ = quality_report_renderables(quality_check(dark_ui, profile="ui-capture-dark"))
    assert table.caption and "default profile this cut scores" in str(table.caption)


@needs_ffmpeg
@pytest.mark.parametrize("capture", ["blank_dark", "black"])
def test_blank_or_black_capture_fails_dark_profile_gate(capture, request):
    from kinocut.quality_guardrails import assert_quality

    with pytest.raises(MCPVideoError) as exc:
        assert_quality(
            request.getfixturevalue(capture),
            min_score=0,
            profile="ui-capture-dark",
            profile_reason="dark editor screen recording",
        )
    assert "ui-capture-dark profile limits failed" in str(exc.value)


@needs_ffmpeg
def test_release_checkpoint_records_profile(dark_ui, tmp_path):
    from kinocut.server_tools_ai import video_release_checkpoint

    result = video_release_checkpoint(
        dark_ui,
        output_dir=str(tmp_path / "review"),
        profile="ui-capture-dark",
        profile_reason="dark editor screen recording",
    )
    assert result["success"] is True, result
    data = result.get("data", result)
    assert data["quality_profile"] == "ui-capture-dark"
    assert data["quality"]["profile"]["visual_checks_gate"] is True


# Light UI: near-white ground with slightly darker flat panels (ported from #700).
_LIGHT_UI = ",".join(
    [
        "drawbox=x=0:y=0:w=180:h=360:color=0xe8e8e8:t=fill",
        "drawbox=x=200:y=28:w=400:h=36:color=0xdedede:t=fill",
        "drawbox=x=200:y=84:w=400:h=240:color=0xf6f6f6:t=fill",
    ]
)


@needs_ffmpeg
def test_light_ui_capture_fails_default_but_passes_light_profile(tmp_path):
    from kinocut.quality_guardrails import assert_quality, quality_check

    light_ui = _render(tmp_path / "light_ui.mp4", _LIGHT_UI, base="0xf2f2f2")
    default = quality_check(light_ui)
    assert default["overall_score"] < 80
    with pytest.raises(MCPVideoError):
        assert_quality(light_ui)

    profiled = quality_check(light_ui, profile="ui-capture-light")
    report = assert_quality(light_ui, profile="ui-capture-light", profile_reason="light app screen recording")
    checks = {c["name"]: c for c in report["checks"]}
    assert report["gate_passed"] is True, checks
    for name in ("brightness", "contrast", "saturation"):
        assert checks[name]["passed"] is True, checks[name]
    # The profile only rescores the picture bands; the other checks are untouched.
    for name in ("audio_levels", "color_balance", "temporal_motion"):
        assert next(c for c in default["checks"] if c["name"] == name) == next(
            c for c in profiled["checks"] if c["name"] == name
        )


# Dark cinematic grades (#760): night, teal-and-shadow, monochrome noir, low-key gradient.
_DARK_GRADES = {
    "night": "testsrc2=s=640x360:d=2:r=10,eq=brightness=-0.35:contrast=0.9:saturation=0.6",
    "teal": "testsrc2=s=640x360:d=2:r=10,eq=brightness=-0.3:saturation=0.5,colorbalance=bs=0.2:rs=-0.1",
    "noir": "mandelbrot=s=640x360:r=10,eq=brightness=-0.25:saturation=0,trim=duration=2",
    # gradients is randomly seeded by default; a fixed seed keeps the fixture deterministic.
    "lowkey": "gradients=s=640x360:d=2:r=10:c0=0x050505:c1=0x404858:seed=1,eq=saturation=0.7",
}


def _render_source(path, source: str) -> str:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", source,
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-pix_fmt", "yuv420p", "-shortest", str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    return str(path)


@needs_ffmpeg
@pytest.mark.parametrize("grade", sorted(_DARK_GRADES))
def test_dark_grade_profile_passes_intentional_dark_grades(grade, tmp_path):
    from kinocut.quality_guardrails import assert_quality

    clip = _render_source(tmp_path / f"{grade}.mp4", _DARK_GRADES[grade])
    report = assert_quality(clip, profile="dark-grade", profile_reason=f"{grade} grade, dark on purpose")
    checks = {c["name"]: c for c in report["checks"]}
    assert report["gate_passed"] is True, checks
    for name in ("brightness", "contrast", "saturation"):
        assert checks[name]["passed"] is True, checks[name]


@needs_ffmpeg
def test_dark_grade_profile_still_fails_black_and_flat_frames(black, blank_dark):
    from kinocut.quality_guardrails import assert_quality

    for clip in (black, blank_dark):
        with pytest.raises(MCPVideoError) as exc:
            assert_quality(clip, profile="dark-grade", profile_reason="testing a blank frame")
        assert "dark-grade profile limits failed" in str(exc.value)
