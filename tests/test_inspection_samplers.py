"""Temporal sampler and normalized-region extraction contracts (Task 7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from kinocut.aivideo.inspection.samplers import (
    DEFAULT_SAMPLE_PERCENTAGES,
    DeclaredRegion,
    choose_sample_timestamps,
    extract_region_crops,
    extract_sampled_frames,
    sample_decoded_timestamps,
    TimestampSample,
)
from kinocut.aivideo.inspection import samplers
from kinocut.contracts import NormalizedRegion
from kinocut.ffmpeg_helpers import _run_ffprobe_json
from kinocut.errors import MCPVideoError
from kinocut.projectstore import open_project


def _video_dimensions(path: Path) -> tuple[int, int]:
    streams = _run_ffprobe_json(str(path))["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    return int(video["width"]), int(video["height"])


def test_default_temporal_percentages_are_exactly_the_approved_policy():
    assert DEFAULT_SAMPLE_PERCENTAGES == (0, 25, 50, 75, 95)


def test_vfr_sampling_uses_only_decoded_timestamp_truth_and_includes_last():
    decoded = (0.0, 0.04, 0.11, 0.23, 0.50, 0.91, 1.40)

    samples = choose_sample_timestamps(decoded)

    assert [sample.timestamp for sample in samples] == [0.0, 0.23, 0.50, 0.91, 1.40]
    assert all(sample.timestamp in decoded for sample in samples)
    assert samples[-1].labels[-1] == "last"


def test_short_timeline_deduplicates_samples_without_losing_policy_labels():
    samples = choose_sample_timestamps((0.0, 0.1))

    assert [sample.timestamp for sample in samples] == [0.0, 0.1]
    assert samples[0].labels == ("0", "25", "50")
    assert samples[1].labels == ("75", "95", "last")


def test_single_decodable_frame_collapses_to_one_truthful_sample():
    samples = choose_sample_timestamps((0.125,))

    assert len(samples) == 1
    assert samples[0].timestamp == 0.125
    assert samples[0].labels == ("0", "25", "50", "75", "95", "last")


def test_sampler_models_reject_noncanonical_labels_before_rendering():
    with pytest.raises(ValidationError):
        TimestampSample(timestamp=0.0, labels=("middle",))
    with pytest.raises(ValidationError):
        DeclaredRegion(
            name="Logo",
            region=NormalizedRegion(x=0.0, y=0.0, width=0.5, height=0.5),
        )


def test_real_ffmpeg_sampler_and_frame_extraction_persist_canonical_artifacts(tmp_path, sample_video):
    project = open_project(tmp_path / "project")

    samples = sample_decoded_timestamps(sample_video)
    frames = extract_sampled_frames(project, sample_video, samples)

    assert frames
    assert frames[-1].timestamp == samples[-1].timestamp
    assert frames[-1].labels[-1] == "last"
    for frame in frames:
        assert frame.artifact.artifact_id.startswith("sha256:")
        assert not Path(frame.artifact.location).is_absolute()
        absolute = project.root / frame.artifact.location
        assert absolute.is_file()
        assert absolute.stat().st_size > 0


def test_normalized_region_crop_uses_source_pixels_and_carries_timestamp(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    samples = sample_decoded_timestamps(sample_video)[:1]
    region = DeclaredRegion(
        name="logo",
        region=NormalizedRegion(x=0.25, y=0.25, width=0.5, height=0.5),
    )

    crops = extract_region_crops(project, sample_video, samples, (region,))

    assert len(crops) == 1
    assert crops[0].timestamp == samples[0].timestamp
    assert crops[0].name == "logo"
    crop_path = project.root / crops[0].artifact.location
    source_width, source_height = _video_dimensions(Path(sample_video))
    assert _video_dimensions(crop_path) == (source_width // 2, source_height // 2)


def test_malformed_source_dimensions_raise_a_private_custom_error(tmp_path, sample_video, monkeypatch):
    project = open_project(tmp_path / "project")
    sample = sample_decoded_timestamps(sample_video)[:1]
    region = DeclaredRegion(
        name="logo",
        region=NormalizedRegion(x=0.0, y=0.0, width=0.5, height=0.5),
    )
    monkeypatch.setattr(
        samplers,
        "_run_ffprobe_json",
        lambda _path: {"streams": [{"codec_type": "video", "width": "bad"}]},
    )

    with pytest.raises(MCPVideoError) as exc:
        extract_region_crops(project, sample_video, sample, (region,))

    assert exc.value.code == "source_dimensions_failed"
    assert str(tmp_path) not in str(exc.value)


def test_frame_extraction_cannot_overwrite_a_symlinked_staging_target(tmp_path, sample_video, monkeypatch):
    project = open_project(tmp_path / "project")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"DO NOT REPLACE")
    trap = project.root / ".kinocut" / "artifacts" / "sha256" / ".render.trap.jpg"
    trap.symlink_to(outside)
    monkeypatch.setattr(samplers, "staging_path", lambda *_args, **_kwargs: trap, raising=False)

    extract_sampled_frames(project, sample_video, sample_decoded_timestamps(sample_video)[:1])

    assert outside.read_bytes() == b"DO NOT REPLACE"
