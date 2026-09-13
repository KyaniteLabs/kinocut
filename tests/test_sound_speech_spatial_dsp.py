"""Shared distance profile has the intended gain/shelf and exact PCM shape."""

from array import array
import math
import tempfile
import pytest

from kinocut_sound.mix._wav import pcm_to_wav, parse_wav
from kinocut_sound.public.dub_request import CaptionCue
from kinocut_sound.public.dub_spatial import _args, _binary, _processed
from kinocut_sound.public.mix_process import run_worker_sync
from kinocut_sound.post.spatial import _distance_filter


@pytest.mark.parametrize("frequency,expected_db", [(200, -6.0), (9000, -12.0)])
def test_distance_gain_and_high_frequency_attenuation(frequency, expected_db):
    rate, frames = 22050, 22050
    pcm = array("h", (round(12000 * math.sin(2 * math.pi * frequency * i / rate)) for i in range(frames)))
    data = pcm_to_wav(pcm, sample_rate_hz=rate)
    with tempfile.TemporaryFile() as raw:
        code, status = run_worker_sync(_args(_binary()), data, (), 10, stdout_sink=raw, stdout_limit=frames * 2)
        assert status == b""
        output = _processed(raw, code, frames, 1, CaptionCue(0, 2000, "test"))
    actual, actual_rate = parse_wav(output)
    assert actual_rate == rate and len(actual) == frames
    middle = actual[512:-512]
    ratio = math.sqrt(sum(value * value for value in middle) / len(middle)) / (12000 / math.sqrt(2))
    assert abs(20 * math.log10(ratio) - expected_db) < 0.3


def test_shared_adapter_defaults_and_profile_parameters():
    dry_filter, dry_metrics = _distance_filter()
    far_filter, far_metrics = _distance_filter({"distance_pct": 100})
    assert dry_metrics == {"distance_pct": 0, "hf_gain_db": 0, "gain_db": 0}
    assert far_metrics == {"distance_pct": 100, "hf_gain_db": -6, "gain_db": -6}
    assert "volume=-6.00dB" in far_filter and "f=4000.00" in far_filter
    assert dry_filter != far_filter
