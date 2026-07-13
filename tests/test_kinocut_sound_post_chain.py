"""Chain builder, determinism, and validation tests for the post package."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut_sound.post import (
    CANONICAL_STAGE_ORDER,
    DynamicsAdapter,
    EqAdapter,
    FFTDenoiseAdapter,
    LoudnessAdapter,
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
    return PostContext(work_dir=tmp_path, sample_rate_hz=FIXTURE_SAMPLE_RATE_HZ, channel_count=1)


@pytest.fixture()
def base_clip(tmp_path: Path) -> Path:
    return synthetic_clip(tmp_path / "base_clip.wav")


class TestChainOrder:
    """The chain enforces the canonical fixed signal order."""

    def test_canonical_order_is_fixed(self):
        assert CANONICAL_STAGE_ORDER == (
            "denoise",
            "deess",
            "eq",
            "dynamics",
            "spatial",
            "distance",
            "humanize",
            "loudness",
        )

    def test_unknown_stage_rejected(self):
        with pytest.raises(ValueError, match="unknown stage"):
            PostChain({"nonexistent": FFTDenoiseAdapter()})

    def test_default_chain_has_all_stages(self):
        chain = PostChain.build_default()
        assert chain.stage_ids == CANONICAL_STAGE_ORDER

    def test_partial_chain_only_runs_present_stages(self):
        chain = PostChain({"denoise": FFTDenoiseAdapter(), "loudness": LoudnessAdapter()})
        assert chain.stage_ids == ("denoise", "loudness")


class TestChainDeterminism:
    """Same input + same params → same output hash."""

    def test_full_chain_is_deterministic(self, ctx, base_clip, tmp_path):
        chain = PostChain.build_default()
        out1 = tmp_path / "chain_out1.wav"
        out2 = tmp_path / "chain_out2.wav"
        params = {
            "denoise": {"strength_db": 10.0},
            "eq": {"preset": "narrator"},
            "dynamics": {"threshold_db": -20.0, "ratio": 4.0},
            "loudness": {"preset": "stream_-14"},
        }
        result1 = chain.run(base_clip, out1, ctx=ctx, stage_params=params)
        # Re-run with fresh work_dir intermediates.
        ctx2 = PostContext(work_dir=tmp_path / "work2", sample_rate_hz=FIXTURE_SAMPLE_RATE_HZ)
        result2 = chain.run(base_clip, out2, ctx=ctx2, stage_params=params)
        assert sha256_of_file(out1) == sha256_of_file(out2)
        assert result1.digest == result2.digest

    def test_chain_produces_stage_trail(self, ctx, base_clip, tmp_path):
        chain = PostChain.build_default()
        out = tmp_path / "chained.wav"
        result = chain.run(base_clip, out, ctx=ctx)
        assert len(result.stages) == len(CANONICAL_STAGE_ORDER)
        stage_ids = tuple(s.adapter_id for s in result.stages)
        assert "denoise_fft" in stage_ids
        assert "loudness_normalize" in stage_ids

    def test_chain_skip_stages(self, ctx, base_clip, tmp_path):
        chain = PostChain.build_default()
        out = tmp_path / "skipped.wav"
        result = chain.run(
            base_clip,
            out,
            ctx=ctx,
            skip_stages=frozenset({"spatial", "distance", "humanize"}),
        )
        stage_ids = tuple(s.adapter_id for s in result.stages)
        assert "spatial_convolution" not in stage_ids
        assert "denoise_fft" in stage_ids


class TestValidationFailClosed:
    """Invalid and over-limit parameters fail closed with PostError."""

    def test_denoise_over_limit_strength(self, ctx, base_clip, tmp_path):
        adapter = FFTDenoiseAdapter()
        with pytest.raises(PostError) as exc:
            adapter.process(base_clip, tmp_path / "x.wav", ctx=ctx, params={"strength_db": 200.0})
        assert exc.value.code == "post_param_over_limit"

    def test_denoise_invalid_strength_type(self, ctx, base_clip, tmp_path):
        adapter = FFTDenoiseAdapter()
        with pytest.raises(PostError) as exc:
            adapter.process(base_clip, tmp_path / "x.wav", ctx=ctx, params={"strength_db": "loud"})
        assert exc.value.code == "invalid_post_param"

    def test_eq_gain_over_limit(self, ctx, base_clip, tmp_path):
        adapter = EqAdapter()
        with pytest.raises(PostError):
            adapter.process(
                base_clip,
                tmp_path / "x.wav",
                ctx=ctx,
                params={"gains": (100.0, 0.0, 0.0, 0.0, 0.0)},
            )

    def test_compressor_ratio_over_limit(self, ctx, base_clip, tmp_path):
        adapter = DynamicsAdapter()
        with pytest.raises(PostError):
            adapter.process(
                base_clip,
                tmp_path / "x.wav",
                ctx=ctx,
                params={"ratio": 100.0},
            )

    def test_distance_over_limit(self, ctx, base_clip, tmp_path):
        from kinocut_sound.post import DistanceAdapter

        adapter = DistanceAdapter()
        with pytest.raises(PostError):
            adapter.process(
                base_clip,
                tmp_path / "x.wav",
                ctx=ctx,
                params={"distance_pct": 150.0},
            )

    def test_humanization_negative_intensity(self, ctx, base_clip, tmp_path):
        from kinocut_sound.post import HumanizationAdapter

        adapter = HumanizationAdapter()
        with pytest.raises(PostError):
            adapter.process(
                base_clip,
                tmp_path / "x.wav",
                ctx=ctx,
                params={"intensity_pct": -5.0},
            )

    def test_error_never_contains_raw_stderr(self, ctx, base_clip, tmp_path):
        """PostError messages must not embed host paths or filter strings."""
        adapter = FFTDenoiseAdapter()
        with pytest.raises(PostError) as exc:
            adapter.process(base_clip, tmp_path / "x.wav", ctx=ctx, params={"strength_db": 999.0})
        message = str(exc.value)
        assert "ffmpeg" not in message.lower() or "processor" in message.lower()
        assert str(tmp_path) not in message
        assert exc.value.suggested_action["auto_fix"] is False
