"""Deterministic interval-based temporal inspection checks."""

from __future__ import annotations

import math
import subprocess

import pytest
from pydantic import ValidationError

from kinocut.aivideo.inspection.temporal_checks import (
    _pixel_frame_difference,
    CorruptInterval,
    RegionDifferenceObservation,
    TemporalFrameObservation,
    analyze_temporal_observations,
    inspect_temporal_media,
)
from kinocut.contracts.defect import DefectCode, DefectStatus
from kinocut.errors import MCPVideoError


ASSET_ID = "sha256:" + "a" * 64


def frame(timestamp: float, luma: float, difference: float, signature: str) -> TemporalFrameObservation:
    return TemporalFrameObservation(
        timestamp=timestamp,
        mean_luma=luma,
        difference_from_previous=difference,
        signature="sha256:" + signature * 64,
    )


def analyze(frames, **kwargs):
    return analyze_temporal_observations(
        tuple(frames),
        target_id=ASSET_ID,
        project_id="project-1",
        expected_end=kwargs.pop("expected_end", 4.0),
        **kwargs,
    )


def findings(result, code: DefectCode):
    return [item for item in result.findings if item.defect_code is code]


def render(output, *args):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *args, str(output)],
        check=True,
        timeout=15,
    )


def test_loop_metric_and_broken_loop_finding_are_deterministic():
    frames = [
        frame(0.0, 80, 0, "0"),
        frame(1.0, 90, 10, "1"),
        frame(2.0, 100, 10, "2"),
        frame(3.0, 140, 40, "f"),
    ]

    first = analyze(frames)
    second = analyze(reversed(frames))

    assert first == second
    assert first.opening_closing_difference == 60.0
    broken = findings(first, DefectCode.BROKEN_LOOP)
    assert len(broken) == 1
    assert broken[0].time_range == (0.0, 4.0)
    assert broken[0].status is DefectStatus.SUSPECTED
    assert broken[0].measurements[0].name == "opening_closing_difference"


def test_loop_metric_compares_pixels_not_only_average_luma():
    assert _pixel_frame_difference(bytes((0, 255)), bytes((255, 0))) == 255.0


def test_black_frames_are_coalesced_into_exact_decoded_interval():
    result = analyze(
        [
            frame(0.0, 60, 0, "0"),
            frame(0.4, 2, 58, "1"),
            frame(1.1, 3, 1, "2"),
            frame(2.0, 70, 67, "3"),
        ],
        expected_end=2.6,
    )

    black = findings(result, DefectCode.BLACK_FRAMES)
    assert [item.time_range for item in black] == [(0.4, 2.0)]
    assert black[0].detector == "temporal.black_interval.v1"


def test_exact_duplicates_and_near_frozen_frames_have_bounded_intervals():
    repeated = "b"
    result = analyze(
        [
            frame(0.0, 80, 0, repeated),
            frame(0.5, 80, 0, repeated),
            frame(1.0, 80, 0.2, "c"),
            frame(1.5, 100, 20, "d"),
        ],
        expected_end=2.0,
    )

    frozen = findings(result, DefectCode.FROZEN_FRAMES)
    assert [item.time_range for item in frozen] == [(0.0, 1.5)]
    names = {measurement.name for measurement in frozen[0].measurements}
    assert names == {"maximum_frame_difference", "exact_duplicate_transitions"}
    assert frozen[0].status is DefectStatus.SUSPECTED


def test_corrupt_intervals_are_sorted_coalesced_and_privacy_safe():
    result = analyze(
        [frame(0, 40, 0, "1"), frame(1, 60, 20, "2"), frame(3, 40, 20, "1")],
        corrupt_intervals=(
            CorruptInterval(start=2.5, end=3.0, reason_code="decode_error"),
            CorruptInterval(start=2.0, end=2.5, reason_code="missing_frame"),
        ),
    )

    corrupt = findings(result, DefectCode.CORRUPT_FRAMES)
    assert [item.time_range for item in corrupt] == [(2.0, 3.0)]
    dumped = corrupt[0].model_dump_json()
    assert "/Users/" not in dumped
    assert "decode_error" not in dumped


def test_late_decode_truncation_is_reported_from_last_decoded_timestamp():
    result = analyze(
        [frame(0.0, 50, 0, "1"), frame(0.5, 60, 10, "2"), frame(1.0, 70, 10, "3")],
        expected_end=3.0,
    )

    late = findings(result, DefectCode.LATE_FRAME_DEGRADATION)
    assert [item.time_range for item in late] == [(1.0, 3.0)]
    assert late[0].detector == "temporal.late_decode.v1"


def test_late_region_difference_emits_text_drift_evidence():
    observations = (
        RegionDifferenceObservation(timestamp=1.0, region_name="price_label", difference=2.0),
        RegionDifferenceObservation(timestamp=2.0, region_name="price_label", difference=16.0),
        RegionDifferenceObservation(timestamp=3.0, region_name="price_label", difference=22.0),
    )
    result = analyze(
        [frame(0, 40, 0, "1"), frame(1, 50, 10, "2"), frame(2, 60, 10, "3"), frame(3, 40, 20, "1")],
        region_differences=observations,
    )

    drift = findings(result, DefectCode.TEXT_DRIFT)
    assert [item.time_range for item in drift] == [(2.0, 4.0)]
    assert drift[0].detector == "temporal.text_region_difference.v1"
    assert {m.name for m in drift[0].measurements} == {"maximum_region_difference"}


def test_short_and_vfr_observations_use_real_timestamps_without_invented_frames():
    result = analyze(
        [frame(0.0, 10, 0, "a"), frame(0.017, 10, 0, "a"), frame(0.119, 40, 30, "b")],
        expected_end=0.2,
    )

    assert result.decoded_timestamps == (0.0, 0.017, 0.119)
    assert all(end <= 0.2 for item in result.findings for _, end in (item.time_range,))


@pytest.mark.parametrize(
    "frames",
    [
        (),
        (frame(0, 20, 0, "1"), frame(0, 30, 10, "2")),
    ],
)
def test_empty_or_duplicate_timestamps_fail_closed(frames):
    with pytest.raises(MCPVideoError, match="decoded frame observations") as exc_info:
        analyze(frames)
    assert exc_info.value.code == "invalid_temporal_observations"


@pytest.mark.parametrize("value", [math.nan, math.inf, -1.0, 256.0])
def test_observation_rejects_hostile_luma(value):
    with pytest.raises(ValidationError):
        TemporalFrameObservation(
            timestamp=0,
            mean_luma=value,
            difference_from_previous=0,
            signature="sha256:" + "a" * 64,
        )


def test_unbounded_or_unknown_corrupt_reason_is_rejected():
    with pytest.raises(ValidationError):
        CorruptInterval(start=0, end=1, reason_code="/Users/private/source.mov")


def test_evidence_intervals_cannot_escape_media_duration():
    frames = (frame(0, 20, 0, "1"), frame(1, 30, 10, "2"))
    with pytest.raises(MCPVideoError) as corrupt_error:
        analyze(
            frames,
            expected_end=2,
            corrupt_intervals=(CorruptInterval(start=1.5, end=2.5, reason_code="decode_error"),),
        )
    assert corrupt_error.value.code == "invalid_temporal_observations"

    with pytest.raises(MCPVideoError) as region_error:
        analyze(
            frames,
            expected_end=2,
            region_differences=(RegionDifferenceObservation(timestamp=2.1, region_name="label", difference=20),),
        )
    assert region_error.value.code == "invalid_temporal_observations"


def test_real_ffmpeg_short_media_uses_decoded_timestamp_truth(tmp_path):
    source = tmp_path / "short-vfr.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=32x32:r=10:d=0.4",
            "-vf",
            "select=eq(n\\,0)+eq(n\\,1)+eq(n\\,3)",
            "-fps_mode",
            "vfr",
            "-c:v",
            "ffv1",
            str(source),
        ],
        check=True,
        timeout=10,
    )

    result = inspect_temporal_media(str(source), target_id=ASSET_ID, project_id="project-1")

    assert result.decoded_timestamps == (0.0, 0.1, 0.3)
    assert result.decoded_timestamps[-1] < 0.4


def test_real_media_probe_fails_closed_without_leaking_path(tmp_path):
    source = tmp_path / "private-client-name.mov"
    source.write_bytes(b"not media")

    with pytest.raises(MCPVideoError) as exc_info:
        inspect_temporal_media(str(source), target_id=ASSET_ID, project_id="project-1")

    assert exc_info.value.code == "temporal_probe_failed"
    assert str(source) not in str(exc_info.value)


def test_real_media_uses_video_end_when_audio_is_longer(tmp_path):
    source = tmp_path / "long-audio.mkv"
    render(
        source,
        "-f",
        "lavfi",
        "-i",
        "color=red:s=32x32:r=10:d=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=3",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "ffv1",
        "-c:a",
        "pcm_s16le",
    )

    result = inspect_temporal_media(str(source), target_id=ASSET_ID, project_id="project-1")

    assert not findings(result, DefectCode.LATE_FRAME_DEGRADATION)
    assert result.playable_end == pytest.approx(1.0, abs=0.11)
    assert max(item.time_range[1] for item in result.findings) <= 1.0


def test_real_media_detects_black_frozen_duplicate_and_broken_loop(tmp_path):
    source = tmp_path / "deterministic-defects.mkv"
    render(
        source,
        "-f",
        "lavfi",
        "-i",
        "color=black:s=32x32:r=10:d=0.5",
        "-f",
        "lavfi",
        "-i",
        "color=red:s=32x32:r=10:d=0.5",
        "-f",
        "lavfi",
        "-i",
        "color=blue:s=32x32:r=10:d=0.5",
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0[out]",
        "-map",
        "[out]",
        "-c:v",
        "ffv1",
    )

    result = inspect_temporal_media(str(source), target_id=ASSET_ID, project_id="project-1")

    assert findings(result, DefectCode.BLACK_FRAMES)
    frozen = findings(result, DefectCode.FROZEN_FRAMES)
    assert frozen
    assert any(
        next(m.value for m in item.measurements if m.name == "exact_duplicate_transitions") > 0 for item in frozen
    )
    assert findings(result, DefectCode.BROKEN_LOOP)


def test_real_corrupt_media_yields_bounded_privacy_safe_finding(tmp_path):
    source = tmp_path / "damaged-client-source.ts"
    render(
        source,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=64x64:r=10:d=2",
        "-c:v",
        "mpeg2video",
        "-f",
        "mpegts",
    )
    damaged = bytearray(source.read_bytes())
    damaged[7000:7008] = b"\xff" * 8
    source.write_bytes(damaged)

    result = inspect_temporal_media(str(source), target_id=ASSET_ID, project_id="project-1")

    corrupt = findings(result, DefectCode.CORRUPT_FRAMES)
    assert corrupt
    assert result.decoded_timestamps[0] == 0.0
    assert all(0 <= item.time_range[0] < item.time_range[1] <= 2.1 for item in corrupt)
    assert str(source) not in result.model_dump_json()


def test_real_media_consumes_typed_late_region_evidence(tmp_path):
    source = tmp_path / "region-evidence.mkv"
    render(
        source,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=32x32:r=10:d=1",
        "-c:v",
        "ffv1",
    )
    evidence = (
        RegionDifferenceObservation(timestamp=0.5, region_name="price_label", difference=2),
        RegionDifferenceObservation(timestamp=0.9, region_name="price_label", difference=25),
    )

    result = inspect_temporal_media(
        str(source),
        target_id=ASSET_ID,
        project_id="project-1",
        region_differences=evidence,
    )

    drift = findings(result, DefectCode.TEXT_DRIFT)
    assert len(drift) == 1
    assert drift[0].time_range == (0.9, 1.0)


def test_real_media_path_with_filter_metacharacters_needs_no_filter_escaping(tmp_path):
    source = tmp_path / "client,[draft]'cut.mkv"
    render(
        source,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=32x32:r=5:d=0.4",
        "-c:v",
        "ffv1",
    )

    result = inspect_temporal_media(str(source), target_id=ASSET_ID, project_id="project-1")
    assert result.decoded_timestamps == (0.0, 0.2)


@pytest.mark.parametrize("retained", [0.7, 0.8, 0.9])
def test_real_truncated_tail_uses_independent_trusted_video_end(tmp_path, retained):
    source = tmp_path / f"tail-{retained}.ts"
    render(
        source,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=64x64:r=10:d=3",
        "-c:v",
        "mpeg2video",
        "-f",
        "mpegts",
    )
    content = source.read_bytes()
    source.write_bytes(content[: int(len(content) * retained)])

    result = inspect_temporal_media(
        str(source),
        target_id=ASSET_ID,
        project_id="project-1",
        trusted_expected_video_end=3.0,
    )

    tail = findings(result, DefectCode.LATE_FRAME_DEGRADATION)
    corrupt = findings(result, DefectCode.CORRUPT_FRAMES)
    assert tail or corrupt
    assert all(0 <= item.time_range[0] < item.time_range[1] <= 3.0 for item in (*tail, *corrupt))
