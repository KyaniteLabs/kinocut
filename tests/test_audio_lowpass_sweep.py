"""Lowpass sweep_up / sweep_down really move the cutoff (issue #843)."""

import numpy as np
import pytest

from kinocut.audio_engine.synthesis import _apply_filter_effects
from kinocut.errors import MCPVideoError

SR = 44100


def _centroid(x):
    p = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return float((f * p).sum() / p.sum())


def _noise(seconds=1.0):
    return np.random.default_rng(0).standard_normal(int(SR * seconds))


def _ends(y):
    n = len(y) // 5
    return _centroid(y[:n]), _centroid(y[-n:])


def test_sweep_down_moves_energy_down():
    y = _apply_filter_effects(_noise(), {"lowpass": {"frequency": 4000, "type": "sweep_down"}}, SR)
    first, last = _ends(y)
    assert first > 2 * last


def test_sweep_up_moves_energy_up():
    y = _apply_filter_effects(_noise(), {"lowpass": {"frequency": 200, "type": "sweep_up"}}, SR)
    first, last = _ends(y)
    assert last > 2 * first


def test_sweep_keeps_length_and_is_finite():
    x = _noise(0.35)
    y = _apply_filter_effects(x, {"lowpass": {"frequency": 4000, "type": "sweep_down", "to": 300}}, SR)
    assert len(y) == len(x) and np.isfinite(y).all()


def test_static_lowpass_unchanged_path():
    x = _noise(0.2)
    a = _apply_filter_effects(x, {"lowpass": 2000}, SR)
    b = _apply_filter_effects(x, {"lowpass": {"frequency": 2000, "type": "static"}}, SR)
    assert np.allclose(a, b)


def test_unknown_type_is_rejected():
    with pytest.raises(MCPVideoError):
        _apply_filter_effects(_noise(0.1), {"lowpass": {"frequency": 2000, "type": "wobble"}}, SR)
