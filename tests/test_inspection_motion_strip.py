"""Deterministic full-duration motion-strip contracts (Task 7)."""

from __future__ import annotations

import hashlib

import pytest

from kinocut.aivideo.inspection import motion_strip
from kinocut.aivideo.inspection.motion_strip import build_motion_strip
from kinocut.aivideo.inspection.samplers import (
    extract_sampled_frames,
    sample_decoded_timestamps,
)
from kinocut.ffmpeg_helpers import _run_ffprobe_json
from kinocut.errors import MCPVideoError
from kinocut.projectstore import open_project


def test_motion_strip_uses_all_truthful_samples_and_persists_one_tiled_image(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    samples = sample_decoded_timestamps(sample_video)
    frames = extract_sampled_frames(project, sample_video, samples)

    strip = build_motion_strip(project, frames)

    assert strip.sample_timestamps == tuple(frame.timestamp for frame in frames)
    assert strip.sample_timestamps[-1] == samples[-1].timestamp
    assert strip.artifact.kind == "motion_strip"
    output = project.root / strip.artifact.location
    assert output.is_file()
    assert output.stat().st_size > 0
    assert strip.artifact.artifact_id == "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
    video = next(stream for stream in _run_ffprobe_json(str(output))["streams"] if stream["codec_type"] == "video")
    assert int(video["width"]) > int(video["height"])


def test_motion_strip_is_idempotent_for_the_same_referenced_frames(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    frames = extract_sampled_frames(project, sample_video, sample_decoded_timestamps(sample_video))

    first = build_motion_strip(project, frames)
    second = build_motion_strip(project, frames)

    assert first == second
    assert (project.root / first.artifact.location).read_bytes() == (
        project.root / second.artifact.location
    ).read_bytes()


def test_motion_strip_supports_a_single_decodable_sample(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    samples = sample_decoded_timestamps(sample_video)[:1]
    frames = extract_sampled_frames(project, sample_video, samples)

    strip = build_motion_strip(project, frames)

    assert strip.sample_timestamps == (samples[0].timestamp,)
    assert (project.root / strip.artifact.location).is_file()


def test_motion_strip_rejects_unordered_samples_before_rendering(tmp_path, sample_video):
    project = open_project(tmp_path / "project")
    frames = extract_sampled_frames(project, sample_video, sample_decoded_timestamps(sample_video))
    before = set((project.root / ".kinocut" / "artifacts").rglob("motion_strip.jpg"))

    with pytest.raises(MCPVideoError) as exc:
        build_motion_strip(project, tuple(reversed(frames)))

    after = set((project.root / ".kinocut" / "artifacts").rglob("motion_strip.jpg"))
    assert exc.value.code == "motion_strip_order"
    assert after == before


def test_motion_strip_cannot_overwrite_a_symlinked_staging_target(tmp_path, sample_video, monkeypatch):
    project = open_project(tmp_path / "project")
    frames = extract_sampled_frames(project, sample_video, sample_decoded_timestamps(sample_video)[:1])
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"DO NOT REPLACE")
    trap = project.root / ".kinocut" / "artifacts" / "sha256" / ".render.trap.jpg"
    trap.symlink_to(outside)
    monkeypatch.setattr(
        motion_strip,
        "staging_path",
        lambda *_args, **_kwargs: trap,
        raising=False,
    )

    build_motion_strip(project, frames)

    assert outside.read_bytes() == b"DO NOT REPLACE"
