"""Final decoded mastering levels and timing, measured independently of the filter."""

import shutil

import numpy as np
import pytest

from kinocut_sound.delivery import DeliveryPreset, LoudnessTarget
from kinocut_sound.post._fixtures import measure_loudness, read_wav, write_wav
from kinocut_sound.post.chain import PostContext
from kinocut_sound.post.loudness import LoudnessAdapter

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires installed FFmpeg")
METER_PRECISION_DB = 0.1
CALIBRATED_LEVEL_TOLERANCE_LU = 0.2


@pytest.mark.parametrize("preset", list(DeliveryPreset))
@pytest.mark.parametrize("output_rate", [48000, 44100])
def test_calibrated_mastering_preserves_target(tmp_path, preset, output_rate):
    rate = 48000
    time = np.arange(10 * rate) / rate
    source = write_wav(tmp_path / "input.wav", 0.1 * np.sin(2 * np.pi * 1000 * time), rate)
    output = tmp_path / "output.wav"
    target = LoudnessTarget.for_preset(preset)
    result = LoudnessAdapter().process(
        source, output, ctx=PostContext(tmp_path, sample_rate_hz=output_rate), params={"preset": preset.value}
    )
    measured = measure_loudness(output)
    error = abs(measured["integrated_lufs"] - target.integrated_lufs)
    assert error <= CALIBRATED_LEVEL_TOLERANCE_LU
    assert error <= target.tolerance_lu
    assert measured["true_peak_dbfs"] <= target.true_peak_dbtp + METER_PRECISION_DB
    samples, actual_rate = read_wav(output)
    assert actual_rate == output_rate
    assert len(samples) == 10 * output_rate
    assert result.metrics["target_integrated_lufs"] == target.integrated_lufs


@pytest.mark.parametrize("output_rate", [48000, 44100])
def test_limiter_preserves_onset_and_final_tail(tmp_path, output_rate):
    rate = 48000
    samples = np.zeros(10 * rate)
    samples[rate // 2] = 0.1
    samples[-2] = 0.1
    source = write_wav(tmp_path / "impulses.wav", samples, rate)
    output = tmp_path / "timed.wav"
    LoudnessAdapter().process(
        source,
        output,
        ctx=PostContext(tmp_path, sample_rate_hz=output_rate),
        params={"preset": "broadcast_ebu_r128_-23"},
    )
    rendered, actual_rate = read_wav(output)
    assert actual_rate == output_rate
    assert len(rendered) == 10 * output_rate
    assert abs(int(np.argmax(abs(rendered[:output_rate]))) - output_rate // 2) <= 1
    assert np.max(abs(rendered[-8:])) > 0.01
    assert int(np.argmax(abs(rendered[-64:]))) >= 60


@pytest.mark.parametrize("output_rate", [48000, 44100])
def test_intersample_signal_final_peak_and_level(tmp_path, output_rate):
    rate = 48000
    time = np.arange(10 * rate) / rate
    envelope = np.minimum(1, np.minimum(time / 0.05, (10 - time) / 0.05))
    samples = 0.8 * envelope * np.sin(2 * np.pi * 12000 * time + np.pi / 4)
    source = write_wav(tmp_path / "intersample.wav", samples, rate)
    output = tmp_path / "master.wav"
    target = LoudnessTarget.for_preset(DeliveryPreset.STREAM_MINUS_14)
    LoudnessAdapter().process(
        source, output, ctx=PostContext(tmp_path, sample_rate_hz=output_rate), params={"preset": "stream_-14"}
    )
    measured = measure_loudness(output)
    assert abs(measured["integrated_lufs"] - target.integrated_lufs) <= target.tolerance_lu
    assert measured["true_peak_dbfs"] <= target.true_peak_dbtp + METER_PRECISION_DB
