"""Adversarial whole-film review controls, including intentional exceptions."""

import hashlib

import pytest

from kinocut import Client
from kinocut.aivideo.inspection.motion_acceptance import motion_review_items
from kinocut.aivideo.inspection.temporal_checks import TemporalFrameObservation, analyze_temporal_observations
from kinocut.errors import MCPVideoError
from kinocut.semantic.models import canonical_digest


def _measured(tmp_path, rates):
    source = tmp_path / "film.mp4"
    source.write_bytes(b"fixture binding; measured observations are injected")
    frames = [
        TemporalFrameObservation(timestamp=0, mean_luma=100, difference_from_previous=0, signature="sha256:" + "a" * 64)
    ]
    for index in range(1, len(rates) * 10 + 1):
        frames.append(
            TemporalFrameObservation(
                timestamp=index / 10,
                mean_luma=100,
                difference_from_previous=rates[(index - 1) // 10] / 10,
                signature="sha256:" + "a" * 64,
            )
        )
    report = analyze_temporal_observations(
        tuple(frames), target_id="sha256:" + "a" * 64, project_id="acceptance", expected_end=len(rates) + 0.1
    ).motion_coherence
    report.update(
        source_sha256="sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        source_binding_status="hashed_media_unchanged_during_inspection",
        coverage_scope="complete_bounded_decode",
        decoded_media_end=report["expected_media_end"],
        decoded_coverage_seconds=report["expected_media_end"],
    )
    return source, report


def _review(source, report, **overrides):
    kwargs = dict(
        input_path=str(source),
        reviewer_id="human:reviewer",
        source_sha256=report["source_sha256"],
        report_sha256=overrides.get("report_sha256") or canonical_digest(report),
        watched_intervals=[{"start": 0.0, "end": report["expected_media_end"]}],
        dispositions={
            item["review_id"]: "intended_cut" if item["kind"] == "transition" else "purposeful_motion"
            for item in motion_review_items(report)
        },
        verdict="accept",
    )
    kwargs.update(overrides)
    return Client().record_motion_acceptance(report, **kwargs)


@pytest.mark.parametrize("rates", [[0, 0, 0, 0], [20, 20, 20, 20], [5, 200, 5, 200], [200, 200, 200], [0, 0, 200, 200]])
def test_motion_controls_need_explicit_full_watch_acceptance(tmp_path, rates):
    source, report = _measured(tmp_path, rates)
    assert report["acceptance"] == "not_granted"
    receipt = _review(source, report)
    assert receipt["acceptance"] == "human_granted"
    assert receipt["attestation_verified_by_system"] is False
    assert report["acceptance"] == "not_granted"  # Original evidence is immutable to this operation.
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert receipt["receipt_sha256"] == canonical_digest(body)


def test_isolated_cut_has_distinct_intention_disposition(tmp_path):
    source, report = _measured(tmp_path, [20, 20])
    report["isolated_transitions"] = [
        {
            "start": 1.0,
            "end": 1.1,
            "difference": 90.0,
            "intent_assessed": False,
            "classification": "isolated_transition_candidate",
        }
    ]
    item = motion_review_items(report)[0]
    assert _review(source, report)["acceptance"] == "human_granted"
    with pytest.raises(MCPVideoError):
        _review(source, report, dispositions={item["review_id"]: "purposeful_motion"})


@pytest.mark.parametrize(
    "intervals",
    [
        [{"start": 0.1, "end": 2.1}],
        [{"start": 0.0, "end": 1.0}, {"start": 1.1, "end": 2.1}],
        [{"start": 0.0, "end": 2.0}],
        [{"start": 0.0, "end": 2.2}],
        [{"start": False, "end": 2.1}],
        [{"start": 0.0, "end": float("nan")}],
        [],
    ],
)
def test_incomplete_invalid_or_excess_viewing_cannot_approve(tmp_path, intervals):
    source, report = _measured(tmp_path, [0, 0])
    with pytest.raises(MCPVideoError):
        _review(source, report, watched_intervals=intervals)


def test_overlapping_and_reordered_watch_segments_cover_full_film(tmp_path):
    source, report = _measured(tmp_path, [0, 0])
    assert (
        _review(source, report, watched_intervals=[{"start": 1.0, "end": 2.1}, {"start": 0.0, "end": 1.1}])[
            "acceptance"
        ]
        == "human_granted"
    )


def test_unresolved_or_missing_flags_and_stale_evidence_cannot_approve(tmp_path):
    source, report = _measured(tmp_path, [5, 200, 5, 200])
    for kwargs in (
        {"dispositions": {}},
        {"report_sha256": "sha256:" + "b" * 64},
        {"source_sha256": "sha256:" + "b" * 64},
        {"dispositions": {item["review_id"]: "needs_fix" for item in motion_review_items(report)}},
    ):
        with pytest.raises(MCPVideoError):
            _review(source, report, **kwargs)
    source.write_bytes(b"changed after inspection")
    with pytest.raises(MCPVideoError):
        _review(source, report)


@pytest.mark.parametrize(
    "update",
    [
        {"coverage_scope": "provided_observations_only"},
        {"budget_truncation": True},
        {"source_binding_status": "unbound_observations"},
        {"observed_start": 1.0},
    ],
)
def test_partial_or_unbound_measurements_never_receive_acceptance(tmp_path, update):
    source, report = _measured(tmp_path, [0, 0])
    report.update(update)
    with pytest.raises(MCPVideoError):
        _review(source, report)


def test_rejected_film_retains_needs_fix_dispositions(tmp_path):
    source, report = _measured(tmp_path, [5, 200])
    receipt = _review(
        source,
        report,
        dispositions={item["review_id"]: "needs_fix" for item in motion_review_items(report)},
        verdict="reject",
    )
    assert receipt["acceptance"] == "human_rejected"


@pytest.mark.parametrize("cut", [False, True])
def test_actual_decoded_calm_or_cut_film_requires_separate_review(tmp_path, cut):
    import subprocess
    from kinocut.aivideo.inspection.temporal_checks import inspect_temporal_media

    source = tmp_path / "assembled.mp4"
    pixels = b"".join(bytes([100 if not cut or index < 20 else 200]) * (32 * 32) for index in range(40))
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-s",
            "32x32",
            "-r",
            "10",
            "-i",
            "pipe:0",
            "-c:v",
            "libx264",
            str(source),
        ],
        input=pixels,
        check=True,
        capture_output=True,
        timeout=30,
    )
    report = inspect_temporal_media(
        str(source), target_id="sha256:" + "a" * 64, project_id="acceptance"
    ).motion_coherence
    assert report["coverage_scope"] == "complete_bounded_decode"
    assert report["expected_media_end"] == 4.0
    assert not report["findings"]
    assert len(report["isolated_transitions"]) == int(cut)
    assert _review(source, report)["acceptance"] == "human_granted"


@pytest.mark.parametrize(
    "update",
    [
        {"decoded_media_end": 0.5},
        {"decoded_coverage_seconds": 0.5},
        {"decoded_media_end": 0.5, "decoded_coverage_seconds": 0.5},
        {"difference_coverage_seconds": 0.0},
        {"difference_coverage_seconds": 0.5},
        {"gaps": [{"start": 0.5, "end": 1.5}]},
        {"unmeasured_intervals": [{"start": 0.5, "end": 1.5}]},
        {"decoded_frame_count": True},
        {"decoded_frame_count": 1},
        {"decoded_media_end": 10**1000},
        {"decoded_coverage_seconds": float("inf")},
        {"observed_last_timestamp": float("nan")},
    ],
)
def test_complete_tag_cannot_override_incomplete_or_invalid_measured_coverage(tmp_path, monkeypatch, update):
    source, report = _measured(tmp_path, [0, 0, 0, 0])
    report.update(update)
    from kinocut.aivideo.inspection import motion_acceptance

    monkeypatch.setattr(
        motion_acceptance,
        "canonical_digest",
        lambda body: pytest.fail("incomplete evidence reached digest serialization"),
    )
    with pytest.raises(MCPVideoError) as failure:
        _review(source, report, report_sha256="sha256:" + "a" * 64)
    assert failure.value.code == "invalid_motion_review"


@pytest.mark.parametrize(
    "finding",
    [
        {"start": -999, "end": "private nonnumeric data"},
        {"start": 0.0, "end": 100.0, "code": "image_change_rate_lurch", "rate_delta": 10, "rate_ratio": 3},
        {"start": 1.0, "end": 0.5, "code": "image_change_rate_lurch", "rate_delta": 10, "rate_ratio": 3},
        {"start": 0.0, "end": 1.0, "code": "unknown", "rate": 200},
        {"start": 0.0, "end": 1.0, "code": "sustained_high_image_change", "rate": float("nan")},
        {"start": 0.0, "end": 1.0, "code": "sustained_high_image_change", "rate": 10**1000},
    ],
)
def test_malformed_motion_evidence_cannot_get_a_review_identifier(tmp_path, finding):
    _, report = _measured(tmp_path, [0, 0])
    report["findings"] = [finding]
    with pytest.raises(MCPVideoError) as failure:
        motion_review_items(report)
    assert failure.value.code == "invalid_motion_review"
