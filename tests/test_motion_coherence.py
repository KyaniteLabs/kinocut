"""Chronological image-change controls do not grant semantic or viewing approval."""

import hashlib
import subprocess

import pytest

from kinocut.aivideo.inspection.temporal_checks import (
    TemporalFrameObservation,
    analyze_temporal_observations,
    inspect_temporal_media,
)


ASSET_ID = "sha256:" + "a" * 64


def _frames(rates, step=0.1):
    frames = [TemporalFrameObservation(timestamp=0, mean_luma=100, difference_from_previous=0, signature=ASSET_ID)]
    for index in range(1, round(len(rates) / step) + 1):
        timestamp = round(index * step, 6)
        rate = rates[min(int(timestamp - step / 2), len(rates) - 1)]
        frames.append(
            TemporalFrameObservation(
                timestamp=timestamp, mean_luma=100, difference_from_previous=rate * step, signature=ASSET_ID
            )
        )
    return tuple(frames)


def _report(frames, expected_end=None):
    return analyze_temporal_observations(
        frames,
        target_id=ASSET_ID,
        project_id="project-1",
        expected_end=expected_end or max(item.timestamp for item in frames) + 0.1,
    ).motion_coherence


@pytest.mark.parametrize("rates", [[0, 0, 0, 0], [20, 20, 20, 20]])
def test_calm_and_steady_controls_are_advisory_without_rate_findings(rates):
    report = _report(_frames(rates))
    assert not report["findings"]
    assert report["intentional_calm_is_valid"]
    assert report["complete_human_viewing_required"]
    assert report["acceptance"] == "not_granted"
    assert "semantic_and_artistic_coherence_not_assessed" in report["scope"]


def test_repeated_lurches_retain_chronology_and_time_bounds():
    report = _report(_frames([5, 200, 5, 200]))
    lurches = [item for item in report["findings"] if item["code"] == "image_change_rate_lurch"]
    assert len(lurches) == 3
    assert [(item["start"], item["end"]) for item in lurches] == [(0, 2), (1, 3), (2, 4)]
    assert [window["rate"] for window in report["windows"]] == pytest.approx([5, 200, 5, 200])


def test_sustained_high_and_calm_to_high_have_distinct_intervals():
    report = _report(_frames([0, 0, 200, 200, 200]))
    findings = {item["code"]: item for item in report["findings"]}
    assert findings["calm_to_high_image_change"]["start"] == 0
    assert findings["sustained_high_image_change"]["start"] == 2
    assert findings["sustained_high_image_change"]["end"] == 5


def test_isolated_cut_candidate_is_separate_from_sustained_rate_without_claiming_intent():
    frames = list(_frames([10, 10, 10, 10]))
    frames[15] = frames[15].model_copy(update={"difference_from_previous": 90.0})
    report = _report(tuple(frames))
    assert not report["findings"]
    assert len(report["isolated_transitions"]) == 1
    assert report["isolated_transitions"][0]["intent_assessed"] is False


def test_observation_rate_and_input_order_do_not_change_window_rates():
    first = _report(_frames([10, 20, 10, 20], step=0.1))
    second = _report(tuple(reversed(_frames([10, 20, 10, 20], step=0.05))))
    assert [item["rate"] for item in first["windows"]] == pytest.approx([item["rate"] for item in second["windows"]])


def test_missing_span_is_excluded_and_coverage_is_not_full_watch():
    frames = _frames([10, 10, 10, 10])
    incomplete = frames[:10] + frames[30:]
    report = _report(incomplete)
    assert report["difference_coverage_seconds"] < 4
    assert report["source_binding_status"] == "unbound_observations"
    assert report["coverage_scope"] == "provided_observations_only; timestamp_gaps_excluded"
    assert report["human_viewing_status"] == "not_recorded"


def test_real_media_report_binds_source_hash_and_bounded_decode(tmp_path):
    source = tmp_path / "calm.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=32x32:r=10:d=1",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    report = inspect_temporal_media(str(source), target_id=ASSET_ID, project_id="project-1").motion_coherence
    assert report["source_sha256"] == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["decoded_frame_count"] == 10
    assert report["coverage_scope"] == "complete_bounded_decode"
    assert report["decoded_coverage_seconds"] == pytest.approx(1.0)
    assert report["budget_policy"] == "excess_frames_reject; never_silently_truncated"
