"""DSP and synthesis regressions from the roast audit.

Covers: the ADSR envelope that crashed when a stage outgrew the clip and never
sounded its decay; fades that stopped at -43 dB; the reverb that took a Python
pass per sample; distortion whose ``tone`` knob did nothing and whose unknown
types were silent no-ops; effect values that crashed numpy or allocated
gigabytes; ``intensity``/``pitch`` that most presets ignored; and the sequencer
that pitch-shifted any track not at the mix rate. Every test checks signal
content or raises the typed error, never a mocked call.
"""

from __future__ import annotations

import math
import sys
import wave

import numpy as np
import pytest

from kinocut.audio_engine import core, sequencing
from kinocut.audio_engine.synthesis import audio_preset, audio_synthesize
from kinocut.errors import MCPVideoError

SR = 44100


def _read_wav(path: str) -> tuple[int, np.ndarray]:
    with wave.open(path, "rb") as wav_file:
        rate = wav_file.getframerate()
        pcm = wav_file.readframes(wav_file.getnframes())
    return rate, np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768.0


def _dominant_hz(samples: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / rate)[int(spectrum.argmax())])


def _hf_ratio(samples: np.ndarray, rate: int, split_hz: float = 4000.0) -> float:
    power = np.abs(np.fft.rfft(samples)) ** 2
    freqs = np.fft.rfftfreq(len(samples), 1 / rate)
    return float(power[freqs > split_hz].sum() / power.sum())


# --- envelope and fades -------------------------------------------------------


def test_envelope_fits_a_clip_shorter_than_its_stages_and_ends_at_zero() -> None:
    ones = np.ones(int(0.1 * SR))
    # attack+decay+release (0.5 s) exceed the 0.1 s clip: used to raise ValueError.
    env = core.apply_envelope(ones, 0.005, 0.08, 0.5, 0.4, 0.1, SR) / ones
    assert np.isfinite(env).all()
    assert env[0] == pytest.approx(0.0, abs=1e-6)
    assert env[-1] == pytest.approx(0.0, abs=1e-6)


def test_envelope_decay_stage_is_audible() -> None:
    ones = np.ones(SR)
    env = core.apply_envelope(ones, 0.01, 0.1, 0.4, 0.2, 1.0, SR)
    attack_end, decay_end = int(0.01 * SR), int(0.11 * SR)
    assert env[attack_end] == pytest.approx(1.0, abs=0.01)
    # The decay ramp was written at the wrong offset and then overwritten by sustain.
    assert env[decay_end] == pytest.approx(0.4, abs=0.01)
    assert env[decay_end + 100 : -int(0.2 * SR)].mean() == pytest.approx(0.4, abs=0.01)


def test_fades_reach_zero_and_multiply_when_they_overlap() -> None:
    ones = np.ones(int(0.2 * SR))
    env = core.apply_fade(ones, 0.15, 0.15, 0.2, SR)
    assert env[0] == pytest.approx(0.0, abs=1e-6)
    assert env[-1] == pytest.approx(0.0, abs=1e-6)
    # In the overlap the later fade must attenuate the earlier one, not replace it.
    overlap = int(0.1 * SR)
    assert env[overlap] < 1.0
    assert env[-1] < core.apply_fade(ones, 0.15, 0.0, 0.2, SR)[-1] + 1e-9


# --- reverb and delay ---------------------------------------------------------


def _reference_reverb(samples: np.ndarray, room_size: float, damping: float, wet_level: float) -> np.ndarray:
    """The per-sample loop the block implementation replaced."""
    n = len(samples)
    wet = np.zeros(n)
    for delay in (1557, 1617, 1491, 1422, 1277, 1356, 1188, 1116):
        d = int(delay * (0.5 + room_size))
        buffer = np.zeros(d)
        ptr = 0
        feedback = 0.84 * room_size
        for i in range(n):
            output = samples[i] + buffer[ptr] * feedback
            buffer[ptr] = output * (1.0 - damping) + buffer[ptr] * damping
            ptr = (ptr + 1) % d
            wet[i] += output
    wet /= 8.0
    for delay in (225, 556, 441, 341):
        buffer = np.zeros(delay)
        ptr = 0
        for i in range(n):
            buf_out = buffer[ptr]
            buffer[ptr] = wet[i] + buf_out * 0.5
            wet[i] = buf_out - wet[i] * 0.5
            ptr = (ptr + 1) % delay
    return samples * (1.0 - wet_level) + wet * wet_level


def test_reverb_is_bit_identical_to_the_reference_loop() -> None:
    x = np.random.default_rng(3).uniform(-0.8, 0.8, 9000)
    for room_size, damping, wet in ((0.5, 0.5, 0.2), (0.95, 0.15, 0.55), (0.3, 0.5, 0.15)):
        produced = core.apply_reverb(x, room_size, damping, wet, SR)
        assert np.array_equal(produced, _reference_reverb(x, room_size, damping, wet))


def test_reverb_no_longer_costs_a_python_pass_per_sample() -> None:
    import time

    x = np.random.default_rng(3).uniform(-0.8, 0.8, SR * 10)
    started = time.perf_counter()
    core.apply_reverb(x, 0.9, 0.2, 0.4, SR)
    # The old loop needed about 11 seconds for 10 seconds of audio.
    assert time.perf_counter() - started < 5.0


# --- distortion, EQ, filters, PCM --------------------------------------------


def test_distortion_tone_controls_brightness_and_unknown_type_is_an_error() -> None:
    x = np.random.default_rng(5).uniform(-0.8, 0.8, SR // 2)
    soft = core.apply_distortion(x, 0.5, 0.5, "soft", SR)
    dark = core.apply_distortion(x, 0.5, 0.0, "soft", SR)
    bright = core.apply_distortion(x, 0.5, 1.0, "soft", SR)
    assert _hf_ratio(dark, SR) < _hf_ratio(soft, SR) < _hf_ratio(bright, SR)
    with pytest.raises(MCPVideoError):
        core.apply_distortion(x, 0.5, 0.5, "hard", SR)


def test_compressor_tolerates_a_zero_attack() -> None:
    x = np.random.default_rng(6).uniform(-0.9, 0.9, SR // 2)
    out = core.apply_compressor(x, 0.3, 4.0, 0.0, 0.1, 1.0, SR)
    assert np.isfinite(out).all()
    assert np.sqrt(np.mean(out**2)) < np.sqrt(np.mean(x**2))


def test_eq_without_scipy_is_a_dependency_error_not_a_silent_no_op(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "scipy", None)
    x = np.random.default_rng(7).uniform(-0.8, 0.8, 4096)
    with pytest.raises(MCPVideoError) as missing:
        core.apply_eq(x, mid_gain=6.0)
    assert missing.value.code == "missing_scipy"
    assert missing.value.error_type == "dependency_error"


@pytest.mark.parametrize("cutoff", [30000.0, 0.0, -5.0, float("nan"), "big"])
def test_filter_cutoffs_outside_nyquist_are_input_errors(cutoff) -> None:
    x = np.zeros(4096)
    with pytest.raises(MCPVideoError):
        core.apply_lowpass(x, cutoff, SR)


def test_float_to_pcm_rounds_and_never_emits_nan_garbage() -> None:
    pcm = core._float_to_pcm(np.array([0.4999, float("nan"), float("inf"), -1.5]))
    assert np.frombuffer(pcm, dtype=np.int16).tolist() == [16380, 0, 32767, -32767]


# --- effect value validation --------------------------------------------------


@pytest.mark.parametrize(
    "effects",
    [
        {"delay": {"delay_time": 0}},
        {"delay": {"delay_time": 1e9}},
        {"delay": {"feedback": 2}},
        {"reverb": "big"},
        {"reverb": {"room_size": -1}},
        {"reverb": {"room_size": 1e9}},
        {"lowpass": 30000},
        {"lowpass": {"type": "sweep_sideways"}},
        {"distortion": {"type": "hard"}},
        {"chorus": {"voice": 3}},
    ],
)
def test_synthesizer_rejects_bad_effect_values_before_any_dsp(effects, tmp_path) -> None:
    with pytest.raises(MCPVideoError) as rejected:
        audio_synthesize(str(tmp_path / "out.wav"), duration=0.05, effects=effects)
    assert rejected.value.error_type == "validation_error"
    assert not (tmp_path / "out.wav").exists()


def test_effects_tool_rejects_bad_values_too(tmp_path) -> None:
    source = str(tmp_path / "in.wav")
    audio_synthesize(source, duration=0.1)
    with pytest.raises(MCPVideoError):
        sequencing.audio_effects(source, str(tmp_path / "out.wav"), [{"type": "lowpass", "frequency": 30000}])


def test_synthesizer_accepts_every_shipped_preset_at_default_intensity(tmp_path) -> None:
    from kinocut.audio_engine.presets import list_presets

    for name in list_presets():
        out = str(tmp_path / f"{name}.wav")
        assert audio_preset(name, out) == out
        assert len(_read_wav(out)[1]) > 0


# --- intensity and pitch ------------------------------------------------------


def test_intensity_scales_loudness_for_every_preset_not_just_four(tmp_path) -> None:
    from kinocut.audio_engine.presets import list_presets

    for name in list_presets():
        quiet = _read_wav(audio_preset(name, str(tmp_path / f"q-{name}.wav"), intensity=0.0, duration=0.3))[1]
        loud = _read_wav(audio_preset(name, str(tmp_path / f"l-{name}.wav"), intensity=1.0, duration=0.3))[1]
        assert np.sqrt(np.mean(quiet**2)) > 0, name  # intensity 0 used to render some presets silent
        assert np.sqrt(np.mean(loud**2)) > np.sqrt(np.mean(quiet**2)), name


def test_pitch_changes_noise_presets_through_their_filters(tmp_path) -> None:
    low = _read_wav(audio_preset("hi-hat", str(tmp_path / "lo.wav"), pitch="low"))[1]
    high = _read_wav(audio_preset("hi-hat", str(tmp_path / "hi.wav"), pitch="high"))[1]
    assert _hf_ratio(high, SR, split_hz=9000) > _hf_ratio(low, SR, split_hz=9000)


# --- sequencer ----------------------------------------------------------------


def _tone_wav(path: str, rate: int, seconds: float, hz: float) -> None:
    t = np.arange(int(rate * seconds)) / rate
    pcm = (np.sin(2 * np.pi * hz * t) * 0.6 * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(pcm)


def test_compose_resamples_tracks_that_are_not_at_the_mix_rate(tmp_path) -> None:
    track = str(tmp_path / "48k.wav")
    _tone_wav(track, 48000, 1.0, 1000.0)
    out = sequencing.audio_compose([{"file": track, "volume": 1.0}], 1.0, str(tmp_path / "out.wav"), SR)
    rate, samples = _read_wav(out)
    assert rate == SR
    # Unresampled, the 1000 Hz tone came out at about 918 Hz and 8 percent short.
    assert _dominant_hz(samples, rate) == pytest.approx(1000.0, abs=8.0)
    assert abs(len(samples) / rate - 1.0) < 0.01


def test_sequence_preset_event_keeps_the_preset_duration_and_rate(tmp_path) -> None:
    out = sequencing.audio_sequence(
        [{"type": "preset", "name": "drone-low", "at": 0}], str(tmp_path / "o.wav"), sample_rate=8000
    )
    rate, samples = _read_wav(out)
    # drone-low lasts 5 s; the old default stretched the budget to 1 s and pitch-shifted the 44.1 kHz render.
    assert abs(len(samples) / rate - 5.0) < 0.05
    assert np.sqrt(np.mean(samples**2)) > 0.01


@pytest.mark.parametrize(
    "event",
    [
        {"type": "tone", "at": float("nan"), "duration": 1},
        {"type": "tone", "at": float("inf"), "duration": 1},
        {"type": "tone", "at": -1, "duration": 1},
        {"type": "tone", "at": 0, "duration": float("nan")},
        {"type": "tone", "at": 1e5, "duration": 1},
    ],
)
def test_sequence_rejects_non_finite_negative_and_oversized_events(event, tmp_path) -> None:
    with pytest.raises(MCPVideoError):
        sequencing.audio_sequence([event], str(tmp_path / "o.wav"), sample_rate=8000)


@pytest.mark.parametrize(
    "tracks, duration",
    [
        ([{"file": "x.wav", "start": float("nan")}], 0.1),
        ([{"file": "x.wav", "start": -0.5}], 0.1),
        ([{"file": "x.wav", "volume": float("nan")}], 0.1),
        ([{"file": "x.wav"}], 1e9),
    ],
)
def test_compose_rejects_bad_start_volume_and_duration(tracks, duration, tmp_path) -> None:
    with pytest.raises(MCPVideoError):
        sequencing.audio_compose(tracks, duration, str(tmp_path / "o.wav"), sample_rate=8000)


def test_math_is_finite_guard_exists() -> None:
    # Guards against the validator being bypassed by bool (an int subclass).
    with pytest.raises(MCPVideoError):
        sequencing._require_finite_number(True, "value")
    assert math.isfinite(sequencing._require_finite_number(1.5, "value"))
