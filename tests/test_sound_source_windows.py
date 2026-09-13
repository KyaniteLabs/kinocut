"""Real source-window and additive-bed behavior at the renderer boundary."""

from array import array

import pytest

from kinocut_sound.mix import CrossfadeTransition, MixClip, MixRenderer
from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav
from kinocut_sound.timeline import Cue, CueKind, Timeline


def _wave(values):
    return pcm_to_wav(array("h", values), sample_rate_hz=8000)


def _cue(name="a", start=0, duration=0.001, **kwargs):
    return Cue(
        cue_id=name,
        source_ref="source.wav",
        start_seconds=start,
        duration_seconds=duration,
        kind=CueKind.LINE,
        **kwargs,
    )


def test_exact_window_padding_tail_and_receipt():
    cue = _cue(in_point_seconds=0.00025, out_point_seconds=0.00075)
    result = MixRenderer(sample_rate_hz=8000).render(
        timeline=Timeline(cues=(cue,), tail_seconds=0.00025),
        clips=(MixClip("a", _wave(range(100, 110))),),
    )
    assert list(parse_wav(result.master_wav)[0]) == [102, 103, 104, 105, 0, 0, 0, 0, 0, 0]
    proof = result.source_windows[0]
    assert (proof.in_sample, proof.out_sample, proof.sample_count, proof.sample_rate_hz) == (2, 6, 4, 8000)


@pytest.mark.parametrize(
    "points",
    [
        {"in_point_seconds": 0.001},
        {"out_point_seconds": 0.00100000001},
        {"in_point_seconds": 0.00001, "out_point_seconds": 0.00002},
    ],
)
def test_invalid_window_does_not_clamp_or_round_back_inside(points):
    with pytest.raises(MixError):
        MixRenderer(sample_rate_hz=8000).render(
            timeline=Timeline(cues=(_cue(**points),)),
            clips=(MixClip("a", _wave(range(8))),),
        )


def test_crossfade_cannot_use_postroll_outside_selected_window():
    left = _cue(out_point_seconds=0.001)
    right = _cue("b", 0.001)
    with pytest.raises(MixError, match="post-roll"):
        MixRenderer(sample_rate_hz=8000).render(
            timeline=Timeline(cues=(left, right)),
            clips=(MixClip("a", _wave([200] * 16)), MixClip("b", _wave([-100] * 8))),
            transitions=(CrossfadeTransition("a", "b", 0.0005),),
        )


@pytest.mark.parametrize("duck", [False, True])
def test_bed_preserves_ambience_sentinel(duck):
    cue = _cue()
    result = MixRenderer(sample_rate_hz=8000).render(
        timeline=Timeline(cues=(cue,)),
        clips=(MixClip("a", _wave([123] * 8), "ambience"),),
        bed_wav=_wave([200] * 8),
        duck_bed=duck,
    )
    assert list(parse_wav(result.stems.stems["ambience"])[0]) == [323] * 8


def test_additive_bed_saturates_without_wrapping():
    result = MixRenderer(sample_rate_hz=8000).render(
        timeline=Timeline(cues=(_cue(),)),
        clips=(MixClip("a", _wave([30000] * 8), "ambience"),),
        bed_wav=_wave([10000] * 8),
        duck_bed=True,
    )
    assert list(parse_wav(result.stems.stems["ambience"])[0]) == [32767] * 8


def test_speech_ducks_only_bed_while_later_ambience_survives():
    timeline = Timeline(cues=(_cue(duration=0.1), _cue("b", 0.1, 0.1)))
    clips = (MixClip("a", _wave([10000] * 800)), MixClip("b", _wave([123] * 800), "ambience"))
    result = MixRenderer(sample_rate_hz=8000).render(
        timeline=timeline,
        clips=clips,
        bed_wav=_wave([1000] * 1600),
        duck_bed=True,
    )
    bed = parse_wav(result.stems.stems["ambience"])[0]
    assert 250 <= bed[799] <= 252
    assert 374 <= bed[800] <= 376
    assert bed[1599] > bed[800]


def test_valid_fractional_selection_and_source_reuse():
    timeline = Timeline(
        cues=(
            _cue(in_point_seconds=0.0002, out_point_seconds=0.0007),
            _cue("b", 0.001, in_point_seconds=0.0005),
        )
    )
    source = _wave(range(100, 110))
    result = MixRenderer(sample_rate_hz=8000).render(
        timeline=timeline,
        clips=(MixClip("a", source), MixClip("b", source)),
    )
    assert list(parse_wav(result.master_wav)[0]) == [102, 103, 104, 105, 0, 0, 0, 0, 104, 105, 106, 107, 108, 109, 0, 0]


def test_silent_source_selection_is_rejected():
    cue = Cue(
        cue_id="quiet",
        source_ref="silence",
        start_seconds=0,
        duration_seconds=0.1,
        kind=CueKind.SILENCE,
        in_point_seconds=0,
    )
    with pytest.raises(MixError, match="silent cues"):
        MixRenderer(sample_rate_hz=8000).render(timeline=Timeline(cues=(cue,)), clips=())


def test_crossfade_uses_selected_sources_without_leading_sentinels():
    timeline = Timeline(
        cues=(
            _cue(in_point_seconds=0.0005, out_point_seconds=0.002),
            _cue("b", 0.001, in_point_seconds=0.0005, out_point_seconds=0.002),
        )
    )
    result = MixRenderer(sample_rate_hz=8000).render(
        timeline=timeline,
        clips=(MixClip("a", _wave([999] * 4 + [200] * 12)), MixClip("b", _wave([888] * 4 + [-100] * 12))),
        transitions=(CrossfadeTransition("a", "b", 0.0005),),
    )
    assert list(parse_wav(result.master_wav)[0]) == [200] * 8 + [200, 125, 50, -25] + [-100] * 4
    assert [(w.in_sample, w.out_sample) for w in result.source_windows] == [(4, 16), (4, 16)]
