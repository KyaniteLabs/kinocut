"""Independent verification of rescue package artifacts."""

from __future__ import annotations

import shutil
import math

import pytest

import mcp_video.engine_runtime_utils as runtime
from mcp_video.engine_edit import trim
from mcp_video.rescue.verifier import CHECK_IDS, verify_package
from kinocut.rescue.verifier import _av_end_delta, _within_time_tolerance


@pytest.mark.parametrize("base", [0.0, 3.0, 14400.0])
def test_time_tolerance_includes_decimal_boundary_without_allowing_overrun(base):
    assert _within_time_tolerance(base + 0.1, base, 0.1)
    assert _within_time_tolerance(base + 0.099, base, 0.1)
    assert not _within_time_tolerance(base + 0.100000001, base, 0.1)
    assert not _within_time_tolerance(base + 0.101, base, 0.1)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_time_tolerance_cannot_accept_nonfinite_measurements(bad):
    assert not _within_time_tolerance(bad, 3, 0.1)
    assert not _within_time_tolerance(3, bad, 0.1)
    assert not _within_time_tolerance(3, 3, bad)


def test_shared_av_delta_contract_keeps_difference_and_missing_stream_semantics():
    raw = {"streams": [{"index": 0, "codec_type": "video"}, {"index": 1, "codec_type": "audio"}]}
    packets = [
        {"stream_index": 0, "pts_time": "3.0", "duration_time": "0.1"},
        {"stream_index": 1, "pts_time": "2.9", "duration_time": "0.1"},
    ]
    assert _av_end_delta(raw, packets) == pytest.approx(0.1)
    assert _av_end_delta(raw, packets[:1]) is None


def test_verifier_rejects_duration_regression(tmp_path, sample_video):
    shortened = tmp_path / "short.mp4"
    trim(sample_video, start=0, duration=1, output_path=str(shortened))

    checks = verify_package(sample_video, str(shortened), str(shortened))

    assert tuple(check.id for check in checks) == CHECK_IDS
    duration = next(check for check in checks if check.id == "timeline_duration")
    assert duration.passed is False
    assert duration.metric is not None
    assert duration.metric.unit == "seconds"


def test_universal_copy_contract_is_explicit(sample_video):
    checks = verify_package(sample_video, sample_video, sample_video)

    universal = next(check for check in checks if check.id == "universal_mp4_contract")
    assert universal.metric is not None
    assert universal.metric.definition
    assert universal.details["required"] == {
        "container": "mp4",
        "video_codec": "h264",
        "pixel_format": "yuv420p",
        "audio_codec": "aac_or_absent",
    }


def test_every_numeric_verification_metric_has_units_and_definition(sample_video):
    checks = verify_package(sample_video, sample_video, sample_video)

    assert all(check.metric is None or (check.metric.unit and check.metric.definition) for check in checks)


def test_verifier_uses_resolved_ffmpeg_binaries_when_path_is_empty(sample_video, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None
    assert ffprobe is not None
    monkeypatch.setattr(runtime, "_ffmpeg", lambda: ffmpeg)
    monkeypatch.setattr(runtime, "_ffprobe", lambda: ffprobe)
    monkeypatch.setenv("PATH", "")

    checks = verify_package(sample_video, sample_video, sample_video)
    by_id = {check.id: check for check in checks}

    assert by_id["master_full_decode"].passed is True
    assert by_id["sharing_full_decode"].passed is True
    assert by_id["monotonic_timestamps"].passed is True
