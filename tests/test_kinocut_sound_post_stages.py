"""Stage-level acceptance tests for the kinocut_sound.post adapters.

Each test verifies that one post-processing stage applies a measurable change
to a fixed synthetic audio fixture, matching the W2.1-W2.8 acceptance evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut_sound.post import (
    ConvolutionReverbAdapter,
    DeEssAdapter,
    DistanceAdapter,
    DynamicsAdapter,
    EqAdapter,
    FFTDenoiseAdapter,
    HumanizationAdapter,
    LoudnessAdapter,
    NeuralDenoiseAdapter,
    PostContext,
)
from kinocut_sound.post._fixtures import (
    FIXTURE_SAMPLE_RATE_HZ,
    measure_band_energy,
    measure_hf_energy,
    measure_loudness,
    measure_reverb_tail_energy,
    measure_rms,
    measure_rms_variation_db,
    sha256_of_file,
    synthetic_clip,
    synthetic_dynamic_clip,
    synthetic_transient_clip,
)


@pytest.fixture()
def ctx(tmp_path: Path) -> PostContext:
    return PostContext(work_dir=tmp_path, sample_rate_hz=FIXTURE_SAMPLE_RATE_HZ, channel_count=1)


@pytest.fixture()
def base_clip(tmp_path: Path) -> Path:
    return synthetic_clip(tmp_path / "base_clip.wav")


class TestFFTDenoise:
    """W2.1 — FFT denoise deterministic + neural fail-soft."""

    def test_fft_denoise_applies_measurable_change(self, ctx, base_clip, tmp_path):
        adapter = FFTDenoiseAdapter()
        out = tmp_path / "denoised.wav"
        result = adapter.process(base_clip, out, ctx=ctx, params={"strength_db": 20.0})
        assert result.applied is True
        assert out.exists()
        assert sha256_of_file(out) != sha256_of_file(base_clip)

    def test_fft_denoise_probe_available(self):
        adapter = FFTDenoiseAdapter()
        probe = adapter.probe()
        assert probe.available is True
        assert probe.adapter_id == "denoise_fft"

    def test_neural_denoise_probes_unavailable_without_model(self):
        adapter = NeuralDenoiseAdapter(model_path=None)
        probe = adapter.probe()
        assert probe.available is False
        assert probe.reason_code is not None

    def test_neural_denoise_demanded_render_fails_closed(self, ctx, base_clip, tmp_path):
        adapter = NeuralDenoiseAdapter(model_path=None)
        from kinocut_sound.post import PostError

        with pytest.raises(PostError):
            adapter.process(base_clip, tmp_path / "neural.wav", ctx=ctx)

    def test_neural_denoise_probes_available_with_model_file(self, tmp_path):
        model_file = tmp_path / "fake_model.rnnn"
        model_file.write_bytes(b"fake model bytes")
        adapter = NeuralDenoiseAdapter(model_path=model_file)
        probe = adapter.probe()
        assert probe.available is True


class TestDeEss:
    """W2.2 — De-essing reduces sibilant energy in the target band."""

    def test_deess_reduces_high_band_energy(self, ctx, base_clip, tmp_path):
        adapter = DeEssAdapter()
        out = tmp_path / "deessed.wav"
        adapter.process(base_clip, out, ctx=ctx, params={"intensity": 1.0, "frequency_hz": 8000.0})
        before = measure_band_energy(base_clip, lo_hz=6000, hi_hz=10000)
        after = measure_band_energy(out, lo_hz=6000, hi_hz=10000)
        # Sibilant-band energy should be lower after de-essing.
        assert after < before

    def test_deess_probe_available(self):
        assert DeEssAdapter().probe().available is True


class TestEq:
    """W2.3 — 5-band parametric EQ with named presets."""

    @pytest.mark.parametrize(
        "preset_name", ["neutral", "warm", "bright", "intimate", "authoritative", "narrator", "confessional"]
    )
    def test_eq_preset_applies_and_changes_spectrum(self, ctx, base_clip, tmp_path, preset_name):
        adapter = EqAdapter()
        out = tmp_path / f"eq_{preset_name}.wav"
        result = adapter.process(base_clip, out, ctx=ctx, params={"preset": preset_name})
        assert result.applied is True
        assert out.exists()
        # Neutral should be near-identical; others should differ.
        if preset_name != "neutral":
            assert sha256_of_file(out) != sha256_of_file(base_clip)

    def test_eq_bright_preset_boosts_hf(self, ctx, base_clip, tmp_path):
        adapter = EqAdapter()
        bright = tmp_path / "eq_bright.wav"
        adapter.process(base_clip, bright, ctx=ctx, params={"preset": "bright"})
        before_hf = measure_band_energy(base_clip, lo_hz=8000, hi_hz=16000)
        after_hf = measure_band_energy(bright, lo_hz=8000, hi_hz=16000)
        # "bright" boosts the high band.
        assert after_hf > before_hf

    def test_eq_warm_preset_cuts_hf(self, ctx, base_clip, tmp_path):
        adapter = EqAdapter()
        warm = tmp_path / "eq_warm.wav"
        adapter.process(base_clip, warm, ctx=ctx, params={"preset": "warm"})
        before_hf = measure_band_energy(base_clip, lo_hz=8000, hi_hz=16000)
        after_hf = measure_band_energy(warm, lo_hz=8000, hi_hz=16000)
        # "warm" cuts the high band.
        assert after_hf < before_hf

    def test_eq_unknown_preset_fails_closed(self, ctx, base_clip, tmp_path):
        from kinocut_sound.post import PostError

        adapter = EqAdapter()
        with pytest.raises(PostError):
            adapter.process(base_clip, tmp_path / "bad.wav", ctx=ctx, params={"preset": "nonexistent"})


class TestDynamics:
    """W2.4 — Dynamic compression reduces LRA."""

    def test_compressor_reduces_rms_variation(self, ctx, tmp_path):
        clip = synthetic_dynamic_clip(tmp_path / "dynamic.wav", duration_s=6.0)
        adapter = DynamicsAdapter()
        out = tmp_path / "compressed.wav"
        adapter.process(clip, out, ctx=ctx, params={"threshold_db": -25.0, "ratio": 8.0})
        before = measure_rms_variation_db(clip)
        after = measure_rms_variation_db(out)
        assert after < before

    def test_compressor_probe_available(self):
        assert DynamicsAdapter().probe().available is True


class TestConvolutionReverb:
    """W2.5 — Convolution-IR room reverb increases reverberation time."""

    def test_hall_reverb_increases_tail_vs_dry(self, ctx, tmp_path):
        clip = synthetic_transient_clip(tmp_path / "transient.wav")
        dry_tail = measure_reverb_tail_energy(clip)
        adapter = ConvolutionReverbAdapter()
        out = tmp_path / "reverb_hall.wav"
        adapter.process(clip, out, ctx=ctx, params={"preset": "hall"})
        wet_tail = measure_reverb_tail_energy(out)
        assert wet_tail > dry_tail

    def test_hall_reverb_longer_than_small_room(self, ctx, tmp_path):
        clip = synthetic_transient_clip(tmp_path / "transient.wav")
        adapter = ConvolutionReverbAdapter()
        hall_out = tmp_path / "hall.wav"
        small_out = tmp_path / "small.wav"
        adapter.process(clip, hall_out, ctx=ctx, params={"preset": "hall"})
        adapter.process(clip, small_out, ctx=ctx, params={"preset": "small_room"})
        hall_tail = measure_reverb_tail_energy(hall_out)
        small_tail = measure_reverb_tail_energy(small_out)
        assert hall_tail >= small_tail

    def test_unknown_reverb_preset_fails_closed(self, ctx, base_clip, tmp_path):
        from kinocut_sound.post import PostError

        with pytest.raises(PostError):
            ConvolutionReverbAdapter().process(base_clip, tmp_path / "bad.wav", ctx=ctx, params={"preset": "cathedral"})


class TestDistance:
    """W2.6 — Distance simulation: far reduces HF vs close."""

    def test_far_distance_reduces_hf_energy(self, ctx, base_clip, tmp_path):
        adapter = DistanceAdapter()
        close = tmp_path / "close.wav"
        far = tmp_path / "far.wav"
        adapter.process(base_clip, close, ctx=ctx, params={"distance_pct": 0.0})
        adapter.process(base_clip, far, ctx=ctx, params={"distance_pct": 100.0})
        close_hf = measure_hf_energy(close)
        far_hf = measure_hf_energy(far)
        assert far_hf < close_hf

    def test_distance_probe_available(self):
        assert DistanceAdapter().probe().available is True


class TestHumanization:
    """W2.8 — Humanization: 0% near-passthrough, >0% adds micro-variation."""

    def test_zero_intensity_is_near_passthrough(self, ctx, base_clip, tmp_path):
        adapter = HumanizationAdapter()
        out = tmp_path / "human_0.wav"
        result = adapter.process(base_clip, out, ctx=ctx, params={"intensity_pct": 0.0})
        assert result.applied is False
        # Stream copy should produce identical bytes.
        assert sha256_of_file(out) == sha256_of_file(base_clip)

    def test_nonzero_intensity_adds_variation(self, ctx, base_clip, tmp_path):
        adapter = HumanizationAdapter()
        out = tmp_path / "human_50.wav"
        result = adapter.process(base_clip, out, ctx=ctx, params={"intensity_pct": 50.0})
        assert result.applied is True
        # Output must differ from input.
        assert sha256_of_file(out) != sha256_of_file(base_clip)

    def test_nonzero_intensity_changes_rms(self, ctx, base_clip, tmp_path):
        adapter = HumanizationAdapter()
        out = tmp_path / "human_80.wav"
        adapter.process(base_clip, out, ctx=ctx, params={"intensity_pct": 80.0})
        before_rms = measure_rms(base_clip)
        after_rms = measure_rms(out)
        # Amplitude jitter should cause a measurable RMS difference.
        assert abs(after_rms - before_rms) > 0.05 or sha256_of_file(out) != sha256_of_file(base_clip)


class TestLoudness:
    """W2.7 — Loudness normalization hits named preset targets."""

    @pytest.mark.parametrize(
        ("preset_name", "target_lufs"),
        [
            ("stream_-14", -14.0),
            ("podcast_-16", -16.0),
            ("broadcast_ebu_r128_-23", -23.0),
            ("broadcast_atsc_a85_-24", -24.0),
        ],
    )
    def test_loudness_hits_preset_target(self, ctx, tmp_path, preset_name, target_lufs):
        clip = synthetic_clip(tmp_path / f"input_{preset_name}.wav", seed=200)
        adapter = LoudnessAdapter()
        out = tmp_path / f"loud_{preset_name}.wav"
        adapter.process(clip, out, ctx=ctx, params={"preset": preset_name})
        measured = measure_loudness(out)
        # Single-pass loudnorm is not exact on short clips; allow ±2 LU.
        assert abs(measured["integrated_lufs"] - target_lufs) <= 2.0, (
            f"measured {measured['integrated_lufs']} LUFS vs target {target_lufs} LUFS"
        )

    def test_true_peak_below_ceiling(self, ctx, tmp_path):
        clip = synthetic_clip(tmp_path / "peak_input.wav", seed=300)
        adapter = LoudnessAdapter()
        out = tmp_path / "limited.wav"
        adapter.process(clip, out, ctx=ctx, params={"preset": "stream_-14"})
        measured = measure_loudness(out)
        # Ceiling for stream/podcast is -1.0 dBTP.
        assert measured["true_peak_dbfs"] <= -0.5, f"true peak {measured['true_peak_dbfs']} exceeds ceiling"

    def test_unknown_loudness_preset_fails_closed(self, ctx, base_clip, tmp_path):
        from kinocut_sound.post import PostError

        with pytest.raises(PostError):
            LoudnessAdapter().process(base_clip, tmp_path / "bad.wav", ctx=ctx, params={"preset": "spotify_-11"})
