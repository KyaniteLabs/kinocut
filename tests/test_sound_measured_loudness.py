"""Actual metering must replace invented proxy metrics and unconditional success."""

from array import array
import math
import shutil

import pytest

from kinocut_sound.delivery import DeliveryPolicy, LoudnessTarget
from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.qa import QaError, check_loudness, measure_loudness


@pytest.fixture
def calibration_wave():
    if not shutil.which("ffmpeg"):
        pytest.skip("real FFmpeg calibration requires installed backend")
    rate = 48000
    samples = array("h", (round(32767 * 0.1 * math.sin(2 * math.pi * 1000 * i / rate)) for i in range(10 * rate)))
    return pcm_to_wav(samples, sample_rate_hz=rate)


def test_constant_signal_has_measured_zero_lra(calibration_wave):
    integrated, peak, lra = measure_loudness(calibration_wave)
    assert integrated == pytest.approx(-23.0, abs=0.2)
    assert peak == pytest.approx(-20.0, abs=0.1)
    assert lra == pytest.approx(0, abs=0.2)


def test_incompatible_target_cannot_pass(calibration_wave):
    with pytest.raises(QaError) as failure:
        check_loudness(calibration_wave, DeliveryPolicy())
    assert failure.value.code == "qa_loudness_fail"


def test_matching_target_and_stricter_peak_ceiling(calibration_wave):
    policy = DeliveryPolicy(loudness=LoudnessTarget(integrated_lufs=-23, true_peak_dbtp=-19))
    assert check_loudness(calibration_wave, policy).within_tolerance
    strict = policy.model_copy(update={"true_peak_ceiling_dbtp": -21})
    with pytest.raises(QaError):
        check_loudness(calibration_wave, strict)


@pytest.mark.parametrize("count", [0, 8000, 32000])
def test_empty_short_silent_material_cannot_claim_measurement(count):
    with pytest.raises(QaError):
        measure_loudness(pcm_to_wav(array("h", [0] * count), sample_rate_hz=8000))


def test_real_loudness_range_uses_gated_programme_levels():
    rate = 48000
    samples = array("h")
    for i in range(60 * rate):
        amplitude = 10 ** ((-10 if 20 * rate <= i < 40 * rate else -30) / 20)
        samples.append(round(32767 * amplitude * math.sin(2 * math.pi * 1000 * i / rate)))
    integrated, peak, lra = measure_loudness(pcm_to_wav(samples, sample_rate_hz=rate))
    assert integrated == pytest.approx(-13, abs=0.3)  # Quiet blocks excluded by integrated relative gate.
    assert peak == pytest.approx(-10, abs=0.1)
    assert lra == pytest.approx(20, abs=0.7)


def test_true_peak_detects_reconstruction_above_sample_peak():
    rate = 48000
    samples = array("h")
    for i in range(10 * rate):
        t = i / rate
        amplitude = 0.8 * min(1, t / 0.05, (10 - t) / 0.05)
        samples.append(round(32767 * amplitude * math.sin(2 * math.pi * 12000 * t + math.pi / 4)))
    sample_peak = 20 * math.log10(max(abs(s) for s in samples) / 32768)
    _, true_peak, _ = measure_loudness(pcm_to_wav(samples, sample_rate_hz=rate))
    assert sample_peak == pytest.approx(-4.9485, abs=0.01)
    assert true_peak == pytest.approx(-1.9382, abs=0.5)
    assert true_peak > sample_peak + 2
