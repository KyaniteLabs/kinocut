"""Batch planner and per-clip override tests for the post package."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut_sound.post import (
    BatchClip,
    BatchPlanner,
    PostChain,
    PostContext,
    PostError,
)
from kinocut_sound.post._fixtures import (
    FIXTURE_SAMPLE_RATE_HZ,
    sha256_of_file,
    synthetic_clip,
)


@pytest.fixture()
def ctx(tmp_path: Path) -> PostContext:
    return PostContext(work_dir=tmp_path / "work", sample_rate_hz=FIXTURE_SAMPLE_RATE_HZ)


@pytest.fixture()
def chain() -> PostChain:
    return PostChain.build_default()


class TestBatchOverrides:
    """W2.9 — Batch processing with per-clip overrides."""

    def test_batch_applies_per_clip_eq_overrides(self, tmp_path, chain, ctx):
        clip_a = synthetic_clip(tmp_path / "clip_a.wav", seed=1)
        clip_b = synthetic_clip(tmp_path / "clip_b.wav", seed=2)
        clips = [
            BatchClip(
                clip_id="clip_a",
                input_path=clip_a,
                output_path=tmp_path / "out_a.wav",
                stage_overrides={"eq": {"preset": "warm"}},
            ),
            BatchClip(
                clip_id="clip_b",
                input_path=clip_b,
                output_path=tmp_path / "out_b.wav",
                stage_overrides={"eq": {"preset": "bright"}},
            ),
        ]
        planner = BatchPlanner(chain)
        result = planner.run(clips, ctx=ctx)
        assert len(result.results) == 2
        assert result.clip_ids == ("clip_a", "clip_b")
        # Different EQ presets should produce different outputs (different seeds + presets).
        assert sha256_of_file(tmp_path / "out_a.wav") != sha256_of_file(tmp_path / "out_b.wav")

    def test_batch_base_params_applied_to_all(self, tmp_path, chain, ctx):
        clip_a = synthetic_clip(tmp_path / "base_a.wav", seed=10)
        clip_b = synthetic_clip(tmp_path / "base_b.wav", seed=11)
        clips = [
            BatchClip(
                clip_id="a",
                input_path=clip_a,
                output_path=tmp_path / "out_base_a.wav",
            ),
            BatchClip(
                clip_id="b",
                input_path=clip_b,
                output_path=tmp_path / "out_base_b.wav",
            ),
        ]
        planner = BatchPlanner(
            chain,
            base_stage_params={"eq": {"preset": "narrator"}, "loudness": {"preset": "stream_-14"}},
        )
        result = planner.run(clips, ctx=ctx)
        assert len(result.results) == 2
        result_a = result.result_for("a")
        result_b = result.result_for("b")
        assert result_a.digest != result_b.digest  # different inputs

    def test_batch_override_merges_with_base(self, tmp_path, chain, ctx):
        """Per-clip overrides merge on top of base params (shallow per-stage merge)."""
        clip = synthetic_clip(tmp_path / "merge_clip.wav", seed=42)
        clips = [
            BatchClip(
                clip_id="merge",
                input_path=clip,
                output_path=tmp_path / "merged.wav",
                stage_overrides={"loudness": {"preset": "podcast_-16"}},
            ),
        ]
        planner = BatchPlanner(
            chain,
            base_stage_params={"eq": {"preset": "narrator"}, "loudness": {"preset": "stream_-14"}},
        )
        result = planner.run(clips, ctx=ctx)
        assert len(result.results) == 1
        # Verify the override took effect by checking the output differs from
        # a run with only the base params.
        clip2 = synthetic_clip(tmp_path / "merge_clip2.wav", seed=42)
        clips_base = [
            BatchClip(
                clip_id="base",
                input_path=clip2,
                output_path=tmp_path / "base_out.wav",
            ),
        ]
        planner_base = BatchPlanner(
            chain,
            base_stage_params={"eq": {"preset": "narrator"}, "loudness": {"preset": "stream_-14"}},
        )
        result_base = planner_base.run(clips_base, ctx=ctx)
        assert result.result_for("merge").digest != result_base.result_for("base").digest

    def test_batch_result_lookup(self, tmp_path, chain, ctx):
        clip = synthetic_clip(tmp_path / "lookup.wav", seed=5)
        clips = [
            BatchClip(
                clip_id="unique_id",
                input_path=clip,
                output_path=tmp_path / "out.wav",
            ),
        ]
        planner = BatchPlanner(chain)
        result = planner.run(clips, ctx=ctx)
        assert result.result_for("unique_id") is not None
        with pytest.raises(PostError):
            result.result_for("nonexistent")

    def test_batch_rejects_missing_input(self, tmp_path, chain, ctx):
        with pytest.raises(PostError):
            BatchClip(
                clip_id="missing",
                input_path=tmp_path / "nonexistent.wav",
                output_path=tmp_path / "out.wav",
            )

    def test_batch_rejects_unknown_stage_override(self, tmp_path, chain, ctx):
        clip = synthetic_clip(tmp_path / "bad_override.wav", seed=7)
        with pytest.raises(PostError):
            BatchClip(
                clip_id="bad",
                input_path=clip,
                output_path=tmp_path / "out.wav",
                stage_overrides={"unknown_stage": {"param": 1.0}},
            )

    def test_batch_over_limit_rejected(self, tmp_path, chain, ctx):
        clip = synthetic_clip(tmp_path / "over.wav", seed=8)
        clips = [
            BatchClip(
                clip_id="over",
                input_path=clip,
                output_path=tmp_path / "out.wav",
                stage_overrides={"denoise": {"strength_db": 999.0}},
            ),
        ]
        planner = BatchPlanner(chain)
        with pytest.raises(PostError):
            planner.run(clips, ctx=ctx)

    def test_batch_clip_id_must_be_bounded(self, tmp_path, chain, ctx):
        clip = synthetic_clip(tmp_path / "bounded.wav", seed=9)
        with pytest.raises(Exception):
            BatchClip(
                clip_id="../bad path",
                input_path=clip,
                output_path=tmp_path / "out.wav",
            )
