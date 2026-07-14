"""Subtitle temporal and safe-area QA tests (Plan 02 Task 8 / PR 5.1).

Covers cue overlap, meaningful gaps, reading-speed violations, missing lines,
EOF overflow, and deterministic platform safe-area profiles with full-display-
resolution collision evidence across vertical/horizontal/square fixtures.

Every pure-QA test (no FFmpeg) is prefixed ``test_qa_`` and the FFmpeg-required
end-to-end tests reuse the shared subtitle-render fixture support.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut.contracts.defect import DefectCode, DefectFinding, Severity
from kinocut.errors import MCPVideoError
from kinocut.subtitles_eof import ClampWarning

_PROJECT = "proj-subtitle-qa"
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
requires_ffmpeg = pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe not installed")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _target_id(cues):
    payload = json.dumps([[c.start, c.end, c.text] for c in cues]).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _srt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = round((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(path, cues):
    """Write ``cues`` as ``(start, end, text)`` tuples to an SRT file."""
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(text)
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _write_vtt(path, cues):
    blocks = ["WEBVTT", ""]
    for start, end, text in cues:
        blocks.append(f"{_srt_time(start).replace(',', '.')} --> {_srt_time(end).replace(',', '.')}")
        blocks.append(text)
        blocks.append("")
    Path(path).write_text("\n".join(blocks), encoding="utf-8")
    return str(path)


def _measurements_dict(finding):
    return {m.name: m.value for m in finding.measurements}


# --------------------------------------------------------------------------- #
# Cue parsing
# --------------------------------------------------------------------------- #


def test_qa_parse_srt_cues(tmp_path):
    from kinocut.aivideo.subtitle_qa import parse_subtitle_cues

    path = _write_srt(tmp_path / "cues.srt", [(0.0, 2.0, "HELLO"), (2.0, 4.0, "WORLD")])
    cues = parse_subtitle_cues(path)
    assert len(cues) == 2
    assert (cues[0].start, cues[0].end, cues[0].text, cues[0].index) == (0.0, 2.0, "HELLO", 0)
    assert (cues[1].start, cues[1].end, cues[1].text, cues[1].index) == (2.0, 4.0, "WORLD", 1)


def test_qa_parse_vtt_cues(tmp_path):
    from kinocut.aivideo.subtitle_qa import parse_subtitle_cues

    path = _write_vtt(tmp_path / "cues.vtt", [(0.0, 2.0, "HELLO"), (2.0, 4.0, "WORLD")])
    cues = parse_subtitle_cues(path)
    assert len(cues) == 2
    assert cues[0].text == "HELLO"
    assert cues[1].text == "WORLD"


def test_qa_parse_empty_subtitle_file(tmp_path):
    from kinocut.aivideo.subtitle_qa import parse_subtitle_cues

    path = tmp_path / "empty.srt"
    path.write_text("", encoding="utf-8")
    assert parse_subtitle_cues(str(path)) == ()


def test_qa_parse_bad_subtitle_format_rejected(tmp_path):
    from kinocut.aivideo.subtitle_qa import parse_subtitle_cues

    path = tmp_path / "cues.ssa"
    path.write_text("junk", encoding="utf-8")
    with pytest.raises(MCPVideoError) as exc:
        parse_subtitle_cues(str(path))
    assert exc.value.code == "unsupported_subtitle_format"


def test_qa_parse_missing_file_rejected(tmp_path):
    from kinocut.aivideo.subtitle_qa import parse_subtitle_cues

    with pytest.raises(MCPVideoError):
        parse_subtitle_cues(str(tmp_path / "nonexistent.srt"))


# --------------------------------------------------------------------------- #
# Temporal QA — overlap
# --------------------------------------------------------------------------- #


def test_qa_detects_cue_overlap():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=3.0, text="first cue"),
        SubtitleCue(index=1, start=2.0, end=4.0, text="second cue"),
    )
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    overlaps = [f for f in findings if f.detector.endswith(":overlap")]
    assert len(overlaps) == 1
    assert overlaps[0].defect_code == DefectCode.SUBTITLE_TIMING
    assert overlaps[0].time_range[0] == pytest.approx(2.0)
    assert overlaps[0].time_range[1] == pytest.approx(3.0)
    measurements = _measurements_dict(overlaps[0])
    assert measurements["overlap_seconds"] == pytest.approx(1.0)


def test_qa_clean_cues_no_overlap_finding():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=2.0, text="first"),
        SubtitleCue(index=1, start=2.0, end=4.0, text="second"),
    )
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert not [f for f in findings if f.detector.endswith(":overlap")]


# --------------------------------------------------------------------------- #
# Temporal QA — meaningful gap
# --------------------------------------------------------------------------- #


def test_qa_detects_meaningful_gap():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=2.0, text="first"),
        SubtitleCue(index=1, start=10.0, end=12.0, text="second"),
    )
    findings = qa_subtitle_temporal(cues, eof_seconds=15.0, project_id=_PROJECT, target_id=_target_id(cues))
    gaps = [f for f in findings if f.detector.endswith(":gap")]
    assert len(gaps) == 1
    assert gaps[0].defect_code == DefectCode.SUBTITLE_TIMING
    measurements = _measurements_dict(gaps[0])
    assert measurements["gap_seconds"] == pytest.approx(8.0)


def test_qa_short_gap_not_flagged():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=2.0, text="first"),
        SubtitleCue(index=1, start=2.5, end=4.0, text="second"),
    )
    findings = qa_subtitle_temporal(
        cues,
        eof_seconds=10.0,
        project_id=_PROJECT,
        target_id=_target_id(cues),
        gap_seconds_threshold=3.0,
    )
    assert not [f for f in findings if f.detector.endswith(":gap")]


# --------------------------------------------------------------------------- #
# Temporal QA — reading speed
# --------------------------------------------------------------------------- #


def test_qa_detects_reading_speed_violation():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    # 30 chars in 0.5 seconds = 60 cps — well above any standard threshold.
    text = "x" * 30
    cues = (SubtitleCue(index=0, start=0.0, end=0.5, text=text),)
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    speed_findings = [f for f in findings if f.detector.endswith(":reading_speed")]
    assert len(speed_findings) == 1
    assert speed_findings[0].defect_code == DefectCode.SUBTITLE_TIMING
    measurements = _measurements_dict(speed_findings[0])
    assert measurements["reading_speed_cps"] == pytest.approx(60.0, abs=0.5)
    assert measurements["text_length_chars"] == 30


def test_qa_normal_reading_speed_not_flagged():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    # 20 chars in 2 seconds = 10 cps — well within standard thresholds.
    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="x" * 20),)
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert not [f for f in findings if f.detector.endswith(":reading_speed")]


# --------------------------------------------------------------------------- #
# Temporal QA — missing lines
# --------------------------------------------------------------------------- #


def test_qa_detects_missing_lines_empty_text():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=2.0, text=""),
        SubtitleCue(index=1, start=2.0, end=4.0, text="   "),
    )
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    missing = [f for f in findings if f.detector.endswith(":missing_text")]
    assert len(missing) == 2


def test_qa_nonempty_text_no_missing_finding():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="real content"),)
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert not [f for f in findings if f.detector.endswith(":missing_text")]


# --------------------------------------------------------------------------- #
# Temporal QA — EOF overflow
# --------------------------------------------------------------------------- #


def test_qa_detects_eof_overflow_clamped():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (SubtitleCue(index=0, start=7.0, end=12.0, text="past end"),)
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    eof_findings = [f for f in findings if f.detector.endswith(":eof_overflow")]
    assert len(eof_findings) == 1
    assert eof_findings[0].defect_code == DefectCode.SUBTITLE_OVERFLOW
    clamp_measure = next(m for m in eof_findings[0].measurements if m.name == "clamp_warning")
    assert ClampWarning.CLAMPED.value in clamp_measure.unit
    assert clamp_measure.value == 0.0


def test_qa_detects_eof_overflow_dropped():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=2.0, text="ok"),
        SubtitleCue(index=1, start=10.5, end=12.0, text="after eof"),
    )
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    eof_findings = [f for f in findings if f.detector.endswith(":eof_overflow")]
    assert len(eof_findings) == 1
    clamp_measure = next(m for m in eof_findings[0].measurements if m.name == "clamp_warning")
    assert ClampWarning.DROPPED.value in clamp_measure.unit
    assert clamp_measure.value == 1.0


def test_qa_exact_eof_not_flagged():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (SubtitleCue(index=0, start=0.0, end=10.0, text="exact"),)
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert not [f for f in findings if f.detector.endswith(":eof_overflow")]


# --------------------------------------------------------------------------- #
# Temporal QA — clean cues produce no findings
# --------------------------------------------------------------------------- #


def test_qa_clean_cues_produce_no_findings():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=2.0, text="Hello world."),
        SubtitleCue(index=1, start=2.5, end=4.5, text="Goodbye world."),
    )
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert findings == ()


# --------------------------------------------------------------------------- #
# Safe-area QA — platform profiles
# --------------------------------------------------------------------------- #


def test_qa_platform_profiles_cover_vertical_horizontal_square():
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES

    assert set(PLATFORM_PROFILES) >= {"vertical", "horizontal", "square"}
    v = PLATFORM_PROFILES["vertical"]
    h = PLATFORM_PROFILES["horizontal"]
    s = PLATFORM_PROFILES["square"]
    # Vertical is portrait (height > width), horizontal is landscape, square is equal.
    assert v.display_height > v.display_width
    assert h.display_width > h.display_height
    assert s.display_width == s.display_height
    # All define a deterministic title-safe margin.
    for profile in (v, h, s):
        assert 0.0 < profile.title_safe_margin_pct < 0.5
        assert profile.subtitle_font_size_px > 0
        assert profile.max_chars_per_line > 0
        assert profile.max_lines > 0


def test_qa_safe_area_vertical_overflow():
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES, SubtitleCue, qa_subtitle_safe_area

    profile = PLATFORM_PROFILES["vertical"]
    # Very long single-line text that exceeds the safe width at full resolution.
    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="X" * 200),)
    findings = qa_subtitle_safe_area(cues, profile=profile, project_id=_PROJECT, target_id=_target_id(cues))
    assert len(findings) >= 1
    finding = findings[0]
    assert finding.defect_code == DefectCode.SUBTITLE_OVERFLOW
    measurements = _measurements_dict(finding)
    # Evidence is at the platform's full display resolution (pixels), not normalized.
    assert measurements["display_width_px"] == profile.display_width
    assert measurements["display_height_px"] == profile.display_height
    assert measurements["subtitle_box_width_px"] > 0
    assert measurements["subtitle_box_height_px"] > 0


def test_qa_safe_area_horizontal_normal_text_ok():
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES, SubtitleCue, qa_subtitle_safe_area

    profile = PLATFORM_PROFILES["horizontal"]
    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="Short caption"),)
    findings = qa_subtitle_safe_area(cues, profile=profile, project_id=_PROJECT, target_id=_target_id(cues))
    assert findings == ()


def test_qa_safe_area_square_overflow():
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES, SubtitleCue, qa_subtitle_safe_area

    profile = PLATFORM_PROFILES["square"]
    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="Y" * 150),)
    findings = qa_subtitle_safe_area(cues, profile=profile, project_id=_PROJECT, target_id=_target_id(cues))
    assert len(findings) >= 1
    assert findings[0].defect_code == DefectCode.SUBTITLE_OVERFLOW


def test_qa_safe_area_collision_evidence_full_resolution():
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES, SubtitleCue, qa_subtitle_safe_area

    profile = PLATFORM_PROFILES["vertical"]
    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="Z" * 100),)
    findings = qa_subtitle_safe_area(cues, profile=profile, project_id=_PROJECT, target_id=_target_id(cues))
    assert len(findings) == 1
    finding = findings[0]
    measurements = _measurements_dict(finding)
    # Pixel-accurate bounding box at the platform's full display resolution.
    assert measurements["subtitle_box_x_px"] >= 0
    assert measurements["subtitle_box_y_px"] >= 0
    assert measurements["subtitle_box_width_px"] > 0
    assert measurements["subtitle_box_height_px"] > 0
    # The box must exceed at least one safe-area boundary.
    assert (
        measurements["overflow_left_px"] > 0
        or measurements["overflow_right_px"] > 0
        or measurements["overflow_top_px"] > 0
        or measurements["overflow_bottom_px"] > 0
    )


def test_qa_safe_area_overlay_collision():
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES, SubtitleCue, qa_subtitle_safe_area

    profile = PLATFORM_PROFILES["horizontal"]
    # Overlay region (logo) at bottom-right where subtitles also sit.
    overlay = {"x": 0.80, "y": 0.80, "width": 0.15, "height": 0.10}
    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="A" * 80),)
    findings = qa_subtitle_safe_area(
        cues,
        profile=profile,
        project_id=_PROJECT,
        target_id=_target_id(cues),
        overlay_regions=(overlay,),
    )
    collisions = [f for f in findings if f.detector.endswith(":overlay_collision")]
    assert len(collisions) >= 1
    measurements = _measurements_dict(collisions[0])
    assert measurements["display_width_px"] == profile.display_width


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_qa_deterministic_same_input_same_findings():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=3.0, text="overlapping"),
        SubtitleCue(index=1, start=2.0, end=4.0, text="cue"),
    )
    args = dict(eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    first = qa_subtitle_temporal(cues, **args)
    second = qa_subtitle_temporal(cues, **args)
    assert len(first) == len(second)
    for a, b in zip(first, second, strict=True):
        assert a.record_id == b.record_id
        assert a.defect_code == b.defect_code
        assert a.time_range == b.time_range


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #


def test_qa_invalid_eof_raises():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (SubtitleCue(index=0, start=0.0, end=2.0, text="ok"),)
    with pytest.raises(MCPVideoError) as exc:
        qa_subtitle_temporal(cues, eof_seconds=-1.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert exc.value.code == "invalid_subtitle_qa_input"


def test_qa_bad_cue_timing_raises():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    # end before start — invalid cue
    cues = (SubtitleCue(index=0, start=5.0, end=2.0, text="bad"),)
    with pytest.raises(MCPVideoError) as exc:
        qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert exc.value.code == "invalid_subtitle_qa_input"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (float("nan"), 1.0),
        (0.0, float("nan")),
        (float("inf"), 1.0),
        (False, 1.0),
    ],
)
def test_qa_rejects_non_finite_or_boolean_cue_times(start, end):
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (SubtitleCue(index=0, start=start, end=end, text="bad"),)
    with pytest.raises(MCPVideoError) as exc:
        qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    assert exc.value.code == "invalid_subtitle_qa_input"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reading_speed_cps_threshold": float("nan")},
        {"reading_speed_cps_threshold": 0.0},
        {"gap_seconds_threshold": float("inf")},
        {"gap_seconds_threshold": -1.0},
    ],
)
def test_qa_rejects_invalid_temporal_thresholds(kwargs):
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (SubtitleCue(index=0, start=0.0, end=1.0, text="ok"),)
    with pytest.raises(MCPVideoError) as exc:
        qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, **kwargs)
    assert exc.value.code == "invalid_subtitle_qa_input"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_id": "sha256:x"},
        {"created_by": "bad user"},
    ],
)
def test_qa_rejects_invalid_record_metadata(kwargs):
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=2.0, text="first"),
        SubtitleCue(index=1, start=1.0, end=3.0, text="second"),
    )
    with pytest.raises(MCPVideoError) as exc:
        qa_subtitle_temporal(cues, eof_seconds=5.0, project_id=_PROJECT, **kwargs)
    assert exc.value.code == "invalid_subtitle_qa_input"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_width", 0),
        ("display_height", -1),
        ("title_safe_margin_pct", float("nan")),
        ("subtitle_anchor_x_pct", 1.1),
        ("subtitle_anchor_y_pct", -0.1),
        ("subtitle_font_size_px", 0),
        ("max_chars_per_line", 0),
        ("max_lines", 0),
    ],
)
def test_qa_rejects_invalid_safe_area_profile(field, value):
    from dataclasses import replace

    from kinocut.aivideo.subtitle_qa import (
        PLATFORM_PROFILES,
        SubtitleCue,
        qa_subtitle_safe_area,
    )

    profile = replace(PLATFORM_PROFILES["horizontal"], **{field: value})
    cues = (SubtitleCue(index=0, start=0.0, end=1.0, text="ok"),)
    with pytest.raises(MCPVideoError) as exc:
        qa_subtitle_safe_area(cues, profile=profile, project_id=_PROJECT)
    assert exc.value.code == "invalid_subtitle_qa_input"


@pytest.mark.parametrize(
    "overlay",
    [
        {"x": "bad", "y": 0.0, "width": 0.1, "height": 0.1},
        {"x": float("nan"), "y": 0.0, "width": 0.1, "height": 0.1},
        {"x": 0.95, "y": 0.0, "width": 0.1, "height": 0.1},
        {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.1},
    ],
)
def test_qa_rejects_malformed_overlay_geometry(overlay):
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES, SubtitleCue, qa_subtitle_safe_area

    cues = (SubtitleCue(index=0, start=0.0, end=1.0, text="ok"),)
    with pytest.raises(MCPVideoError) as exc:
        qa_subtitle_safe_area(
            cues,
            profile=PLATFORM_PROFILES["horizontal"],
            project_id=_PROJECT,
            overlay_regions=(overlay,),
        )
    assert exc.value.code == "invalid_subtitle_qa_input"


# --------------------------------------------------------------------------- #
# End-to-end with real media (FFmpeg required)
# --------------------------------------------------------------------------- #


def _make_video(path, width, height, seconds=3):
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:duration={seconds}:rate=15",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        timeout=60,
    )
    if not Path(path).is_file():
        pytest.skip("could not generate fixture video")
    return str(path)


@requires_ffmpeg
@pytest.mark.parametrize(
    ("platform", "dims"),
    [("vertical", (216, 384)), ("horizontal", (384, 216)), ("square", (256, 256))],
)
def test_qa_end_to_end_subtitle_qa_with_real_media(tmp_path, platform, dims):
    from kinocut.aivideo.subtitle_qa import subtitle_qa

    width, height = dims
    media = _make_video(tmp_path / f"{platform}.mp4", width, height)
    srt = _write_srt(
        tmp_path / "cues.srt",
        [
            (0.0, 2.0, "First cue here."),
            (1.5, 3.0, "Overlapping second cue with a very long text " + "X" * 80),
        ],
    )
    report = subtitle_qa(
        media,
        srt,
        project_id=_PROJECT,
        profile=platform,
    )
    assert report.cue_count == 2
    assert report.eof_seconds > 0
    codes = {f.defect_code for f in report.findings}
    # The overlapping cues guarantee at least a timing finding.
    assert DefectCode.SUBTITLE_TIMING in codes


@requires_ffmpeg
def test_qa_end_to_end_clean_subtitles_no_findings(tmp_path):
    from kinocut.aivideo.subtitle_qa import subtitle_qa

    media = _make_video(tmp_path / "clean.mp4", 384, 216, seconds=5)
    srt = _write_srt(
        tmp_path / "clean.srt",
        [(0.0, 2.0, "Short cue."), (2.5, 4.0, "Second cue.")],
    )
    report = subtitle_qa(media, srt, project_id=_PROJECT, profile="horizontal")
    assert report.findings == ()


@requires_ffmpeg
def test_qa_end_to_end_eof_overflow(tmp_path):
    from kinocut.aivideo.subtitle_qa import subtitle_qa

    media = _make_video(tmp_path / "short.mp4", 216, 384, seconds=2)
    srt = _write_srt(tmp_path / "overflow.srt", [(0.0, 1.0, "ok"), (1.5, 5.0, "past end")])
    report = subtitle_qa(media, srt, project_id=_PROJECT, profile="vertical")
    eof_findings = [f for f in report.findings if f.detector.endswith(":eof_overflow")]
    assert len(eof_findings) >= 1


# --------------------------------------------------------------------------- #
# All findings are valid DefectFinding records
# --------------------------------------------------------------------------- #


def test_qa_all_findings_are_valid_defect_records():
    from kinocut.aivideo.subtitle_qa import SubtitleCue, qa_subtitle_temporal

    cues = (
        SubtitleCue(index=0, start=0.0, end=3.0, text="overlap"),
        SubtitleCue(index=1, start=2.0, end=4.0, text="speed test " * 10),
    )
    findings = qa_subtitle_temporal(cues, eof_seconds=10.0, project_id=_PROJECT, target_id=_target_id(cues))
    for finding in findings:
        assert isinstance(finding, DefectFinding)
        assert finding.project_id == _PROJECT
        assert finding.defect_code in (DefectCode.SUBTITLE_TIMING, DefectCode.SUBTITLE_OVERFLOW)
        assert finding.severity in Severity
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.detector.startswith("deterministic:subtitle_qa")
        assert finding.status.value == "suspected"


# --------------------------------------------------------------------------- #
# Shared-defaults divergence (AGENTS.md Rule 12)
# --------------------------------------------------------------------------- #


def test_qa_defaults_sourced_from_shared_defaults_module():
    """Subtitle QA defaults must come from ``defaults.py``, not be redefined.

    Identity checks (not equality) catch silent divergence: if anyone
    reintroduces a module-level literal or rebinds the public function default
    to a hardcoded number, ``is`` fails because Python does not intern floats.
    """
    import inspect

    from kinocut.aivideo import subtitle_qa
    from kinocut.defaults import (
        DEFAULT_SUBTITLE_QA_CHAR_WIDTH_FACTOR,
        DEFAULT_SUBTITLE_QA_DETECTOR_CONFIDENCE,
        DEFAULT_SUBTITLE_QA_GAP_SECONDS_THRESHOLD,
        DEFAULT_SUBTITLE_QA_LINE_HEIGHT_FACTOR,
        DEFAULT_SUBTITLE_QA_READING_SPEED_CPS,
    )

    # Module-level aliases must reference the shared defaults exactly.
    assert subtitle_qa.DEFAULT_READING_SPEED_CPS is DEFAULT_SUBTITLE_QA_READING_SPEED_CPS
    assert subtitle_qa.DEFAULT_GAP_SECONDS_THRESHOLD is DEFAULT_SUBTITLE_QA_GAP_SECONDS_THRESHOLD
    assert subtitle_qa._CHAR_WIDTH_FACTOR is DEFAULT_SUBTITLE_QA_CHAR_WIDTH_FACTOR
    assert subtitle_qa._LINE_HEIGHT_FACTOR is DEFAULT_SUBTITLE_QA_LINE_HEIGHT_FACTOR
    assert subtitle_qa._DETECTOR_CONFIDENCE is DEFAULT_SUBTITLE_QA_DETECTOR_CONFIDENCE

    # Public function default args must bind to the same shared objects.
    sig_temporal = inspect.signature(subtitle_qa.qa_subtitle_temporal)
    assert sig_temporal.parameters["reading_speed_cps_threshold"].default is DEFAULT_SUBTITLE_QA_READING_SPEED_CPS
    assert sig_temporal.parameters["gap_seconds_threshold"].default is DEFAULT_SUBTITLE_QA_GAP_SECONDS_THRESHOLD

    sig_full = inspect.signature(subtitle_qa.subtitle_qa)
    assert sig_full.parameters["reading_speed_cps_threshold"].default is DEFAULT_SUBTITLE_QA_READING_SPEED_CPS
    assert sig_full.parameters["gap_seconds_threshold"].default is DEFAULT_SUBTITLE_QA_GAP_SECONDS_THRESHOLD

    # Private helper confidence default must also bind to the shared object.
    sig_finding = inspect.signature(subtitle_qa._make_finding)
    assert sig_finding.parameters["confidence"].default is DEFAULT_SUBTITLE_QA_DETECTOR_CONFIDENCE


def test_qa_defaults_module_does_not_redefine_shared_numeric_values():
    """The subtitle_qa module must not contain a local numeric redefinition.

    AST-scans the source so a future edit that adds e.g.
    ``DEFAULT_READING_SPEED_CPS = 25.0`` (with the same value) is still caught,
    even though the value would happen to compare equal.
    """
    import ast
    import pathlib

    from kinocut.aivideo import subtitle_qa

    shared_names = {
        "DEFAULT_SUBTITLE_QA_READING_SPEED_CPS",
        "DEFAULT_SUBTITLE_QA_GAP_SECONDS_THRESHOLD",
        "DEFAULT_SUBTITLE_QA_CHAR_WIDTH_FACTOR",
        "DEFAULT_SUBTITLE_QA_LINE_HEIGHT_FACTOR",
        "DEFAULT_SUBTITLE_QA_DETECTOR_CONFIDENCE",
    }
    rebound = {
        "DEFAULT_READING_SPEED_CPS",
        "DEFAULT_GAP_SECONDS_THRESHOLD",
        "_CHAR_WIDTH_FACTOR",
        "_LINE_HEIGHT_FACTOR",
        "_DETECTOR_CONFIDENCE",
    }

    source = pathlib.Path(subtitle_qa.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # No module-level Assign/AnnAssign may re-bind the alias names — they must
    # come through `from kinocut.defaults import ... as ...` only.
    offenders: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in rebound:
                    offenders.append(target.id)
    assert offenders == [], f"subtitle_qa redefines shared-default aliases locally: {offenders}"

    # The shared names must be imported from defaults, not defined inline.
    imported_from_defaults: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("defaults"):
            for alias in node.names:
                imported_from_defaults.add(alias.name)
    assert shared_names <= imported_from_defaults, (
        f"subtitle_qa missing required shared-default imports: {shared_names - imported_from_defaults}"
    )


# --------------------------------------------------------------------------- #
# Platform profiles — divergence from shared validation data (Rule 13)
# --------------------------------------------------------------------------- #


def test_qa_platform_profiles_built_from_validation_data():
    """PLATFORM_PROFILES must match the immutable validation source exactly.

    Every field of every profile is compared against
    ``SUBTITLE_SAFE_AREA_PROFILES`` from ``validation.py`` so a silent edit
    to either surface is caught.
    """
    from kinocut.aivideo.subtitle_qa import PLATFORM_PROFILES, SafeAreaProfile
    from kinocut.validation import SUBTITLE_SAFE_AREA_PROFILES

    assert len(PLATFORM_PROFILES) == len(SUBTITLE_SAFE_AREA_PROFILES)
    for data in SUBTITLE_SAFE_AREA_PROFILES:
        assert data.platform in PLATFORM_PROFILES
        profile = PLATFORM_PROFILES[data.platform]
        assert isinstance(profile, SafeAreaProfile)
        assert profile.platform == data.platform
        assert profile.display_width == data.display_width
        assert profile.display_height == data.display_height
        assert profile.title_safe_margin_pct == data.title_safe_margin_pct
        assert profile.subtitle_font_size_px == data.subtitle_font_size_px
        assert profile.subtitle_anchor_x_pct == data.subtitle_anchor_x_pct
        assert profile.subtitle_anchor_y_pct == data.subtitle_anchor_y_pct
        assert profile.max_chars_per_line == data.max_chars_per_line
        assert profile.max_lines == data.max_lines


def test_qa_platform_profiles_not_hardcoded_in_subtitle_qa():
    """subtitle_qa must build PLATFORM_PROFILES from imported data, not literals.

    AST-scans the source so a future edit that re-introduces literal
    ``SafeAreaProfile(...)`` calls with hardcoded numbers inside a module-level
    dict is caught.
    """
    import ast
    import pathlib

    from kinocut.aivideo import subtitle_qa

    source = pathlib.Path(subtitle_qa.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # SUBTITLE_SAFE_AREA_PROFILES must be imported from validation.
    imported_from_validation: set[str] = set()
    profile_value: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("validation"):
            for alias in node.names:
                imported_from_validation.add(alias.name)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PLATFORM_PROFILES":
                    profile_value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PLATFORM_PROFILES"
        ):
            profile_value = node.value
    assert "SUBTITLE_SAFE_AREA_PROFILES" in imported_from_validation, (
        "subtitle_qa must import SUBTITLE_SAFE_AREA_PROFILES from validation"
    )
    assert profile_value is not None, "PLATFORM_PROFILES must be defined"
    # The dict must be built via comprehension over the imported data, not a
    # literal dict with SafeAreaProfile calls using hardcoded numbers.
    assert isinstance(profile_value, ast.DictComp), (
        "PLATFORM_PROFILES must be a dict comprehension built from SUBTITLE_SAFE_AREA_PROFILES, not hardcoded literals"
    )


def test_subtitle_qa_module_under_800_lines():
    from kinocut.aivideo import subtitle_qa

    assert len(Path(subtitle_qa.__file__).read_text().splitlines()) <= 800
