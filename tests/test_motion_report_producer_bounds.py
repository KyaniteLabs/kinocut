"""Bounded longform CLI journeys using controlled producer observations."""

import hashlib
import json
import subprocess
import sys

import pytest

from kinocut.aivideo.inspection.motion_coherence import chronological_motion_report
from kinocut.aivideo.inspection.temporal_checks import TemporalFrameObservation
from kinocut.cli.handlers_motion_acceptance import handle_motion_acceptance_commands
from kinocut.errors import MCPVideoError
from kinocut.limits import (
    MAX_CLI_JSON_ARTIFACT_BYTES,
    MAX_MOTION_DISPOSITIONS_JSON_BYTES,
    MAX_MOTION_REPORT_JSON_BYTES,
    MAX_MOTION_WATCHED_INTERVALS_JSON_BYTES,
    MAX_TEMPORAL_INSPECTION_FRAMES,
    MAX_VIDEO_DURATION,
)
from kinocut.semantic.models import canonical_digest
from tests.test_motion_acceptance_surfaces import _arguments, _parser


def _longform_arguments(tmp_path, pattern):
    # Source binding and decoded observations are controlled fixtures, not a
    # real four-hour decode, perceptual acceptance, or proof of human watching.
    source = tmp_path / "film.mp4"
    source.write_bytes(b"controlled producer observation source binding")
    frames = tuple(
        TemporalFrameObservation(
            timestamp=index * MAX_VIDEO_DURATION / MAX_TEMPORAL_INSPECTION_FRAMES,
            mean_luma=100.0,
            difference_from_previous=pattern[index % len(pattern)] if index else 0.0,
            signature="sha256:" + "a" * 64,
        )
        for index in range(MAX_TEMPORAL_INSPECTION_FRAMES)
    )
    report = chronological_motion_report(frames, float(MAX_VIDEO_DURATION))
    report.update(
        source_sha256="sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        source_binding_status="hashed_media_unchanged_during_inspection",
        coverage_scope="complete_bounded_decode",
        decoded_media_end=float(MAX_VIDEO_DURATION),
        decoded_coverage_seconds=float(MAX_VIDEO_DURATION),
    )
    return {
        "input_path": str(source),
        "report": report,
        "source_sha256": report["source_sha256"],
        "report_sha256": canonical_digest(report),
        "reviewer_id": "human:fixture",
        "watched_intervals": [{"start": 0.0, "end": float(MAX_VIDEO_DURATION)}],
        "dispositions": {
            item["review_id"]: "intended_cut" if item["kind"] == "transition" else "purposeful_motion"
            for item in report["review_items"]
        },
        "verdict": "reject",
    }


def _all_file_argv(arguments, tmp_path):
    argv = ["record-motion-acceptance", arguments["input_path"]]
    for field in ("report", "watched_intervals", "dispositions"):
        path = tmp_path / (field + ".json")
        path.write_text(json.dumps(arguments[field], indent=2), encoding="utf-8")
        argv.extend(["--" + field.replace("_", "-") + "-file", str(path)])
    for field in ("source_sha256", "report_sha256", "reviewer_id", "verdict"):
        argv.extend(["--" + field.replace("_", "-"), arguments[field]])
    return argv


@pytest.mark.parametrize("pattern", [(0.0, 200.0), (0.0, 100.0, 100.0, 0.0)])
def test_max_duration_and_frame_budget_producer_reports_launch_via_files(tmp_path, pattern):
    arguments = _longform_arguments(tmp_path, pattern)
    if len(pattern) == 4:
        arguments["watched_intervals"] *= MAX_TEMPORAL_INSPECTION_FRAMES
    argv = _all_file_argv(arguments, tmp_path)
    report_bytes = (tmp_path / "report.json").stat().st_size
    assert MAX_CLI_JSON_ARTIFACT_BYTES < report_bytes <= MAX_MOTION_REPORT_JSON_BYTES
    assert (tmp_path / "dispositions.json").stat().st_size > 128 * 1024
    assert (tmp_path / "dispositions.json").stat().st_size <= MAX_MOTION_DISPOSITIONS_JSON_BYTES
    assert (tmp_path / "watched_intervals.json").stat().st_size <= MAX_MOTION_WATCHED_INTERVALS_JSON_BYTES
    result = subprocess.run(
        [sys.executable, "-m", "kinocut", "--format", "json", *argv],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)["receipt"]
    assert receipt["acceptance"] == "human_rejected"
    assert receipt["attestation_verified_by_system"] is False
    assert receipt["report_sha256"] == arguments["report_sha256"]
    assert receipt["film_duration_seconds"] == MAX_VIDEO_DURATION
    assert receipt["dispositions"] == arguments["dispositions"]
    assert len(receipt["watched_intervals"]) == len(arguments["watched_intervals"])
    assert receipt["receipt_sha256"] == canonical_digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )


@pytest.mark.parametrize(
    ("field", "cap"),
    [
        ("dispositions", MAX_MOTION_DISPOSITIONS_JSON_BYTES),
        ("watched_intervals", MAX_MOTION_WATCHED_INTERVALS_JSON_BYTES),
    ],
)
@pytest.mark.parametrize("damage", ["oversize", "invalid", "utf8", "deep", "missing"])
def test_review_file_admission_precedes_human_review(tmp_path, monkeypatch, field, cap, damage):
    argv = _all_file_argv(_arguments(tmp_path), tmp_path)
    path = tmp_path / (field + ".json")
    if damage == "oversize":
        with path.open("wb") as handle:
            handle.truncate(cap + 1)
    elif damage == "invalid":
        path.write_text('{"private-secret":', encoding="utf-8")
    elif damage == "utf8":
        path.write_bytes(b"\xffprivate-secret")
    elif damage == "deep":
        path.write_text("[" * 129 + "]" * 129, encoding="utf-8")
    else:
        path.unlink()

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid file reached human review")

    monkeypatch.setattr("kinocut.aivideo.inspection.motion_acceptance.record_motion_acceptance", forbidden)
    with pytest.raises(MCPVideoError) as error:
        handle_motion_acceptance_commands(_parser().parse_args(argv), use_json=True)
    assert error.value.error_type == "validation_error"
    assert error.value.code == "invalid_json"
    assert "private" not in str(error.value) and str(tmp_path) not in str(error.value)


@pytest.mark.parametrize("field", ["watched_intervals", "dispositions"])
def test_each_review_input_requires_exactly_one_inline_or_file_lane(tmp_path, field):
    argv = _all_file_argv(_arguments(tmp_path), tmp_path)
    flag = "--" + field.replace("_", "-")
    index = argv.index(flag + "-file")
    for invalid in (argv[:index] + argv[index + 2 :], [*argv, flag + "-json", "{}"]):
        with pytest.raises(SystemExit) as error:
            _parser().parse_args(invalid)
        assert error.value.code == 2
