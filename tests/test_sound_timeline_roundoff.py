"""Adjacent decimal cue boundaries must survive binary float arithmetic."""

from math import inf, nextafter

import pytest
from pydantic import ValidationError

from kinocut_sound.mix import MixClip, MixRenderer
from kinocut_sound.mix._wav import parse_wav, synthesize_tone
from kinocut_sound.timeline import Cue, CueKind, Timeline


def _cue(name, start, duration):
    return Cue(
        cue_id=name, start_seconds=start, duration_seconds=duration, kind=CueKind.LINE, source_ref=f"v/{name}.wav"
    )


def test_four_adjacent_decimal_cues_render_without_false_overlap():
    timeline = Timeline(cues=tuple(_cue(f"line_{i}", i / 10, 0.1) for i in range(4)), gap_tolerance_seconds=0)
    wav = synthesize_tone(duration_seconds=0.1)
    result = MixRenderer().render(timeline=timeline, clips=tuple(MixClip(cue.cue_id, wav) for cue in timeline.cues))
    samples, rate = parse_wav(result.master_wav)
    assert len(samples) == round(0.4 * rate)
    assert result.measured_duration_seconds == 0.4
    assert result.within_tolerance


def test_gap_at_declared_tolerance_survives_subtraction_roundoff():
    timeline = Timeline(cues=(_cue("a", 0, 0.29), _cue("b", 0.30, 0.1)), gap_tolerance_seconds=0.01)
    assert timeline.cues[1].start_seconds == 0.30


@pytest.mark.parametrize("start", [0.299, nextafter(nextafter(0.3, -inf), -inf)])
def test_overlap_beyond_one_float_step_is_rejected(start):
    with pytest.raises(ValidationError, match="before previous cue ends"):
        Timeline(cues=(_cue("a", 0, 0.3), _cue("b", start, 0.1)))


@pytest.mark.parametrize("start", [0.30001, nextafter(nextafter(0.29 + 0.01, inf), inf)])
def test_gap_beyond_one_float_step_is_rejected(start):
    with pytest.raises(ValidationError, match="unexplained gap"):
        Timeline(cues=(_cue("a", 0, 0.29), _cue("b", start, 0.1)), gap_tolerance_seconds=0.01)
