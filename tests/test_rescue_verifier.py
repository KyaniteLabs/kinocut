"""Independent verification of rescue package artifacts."""

from __future__ import annotations

from mcp_video.engine_edit import trim
from mcp_video.rescue.verifier import CHECK_IDS, verify_package


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

    assert all(
        check.metric is None or (check.metric.unit and check.metric.definition)
        for check in checks
    )
