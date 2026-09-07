"""PCM and timing proofs for explicit outgoing post-roll transitions."""

from array import array

import pytest

from kinocut_sound.mix import CrossfadeTransition, MixClip, MixError, MixRenderer, recombine_stems
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav
from kinocut_sound.timeline import Cue, CueKind, Timeline

RATE = 1000


def _wav(samples):
    return pcm_to_wav(array("h", samples), sample_rate_hz=RATE)


def _fixture():
    timeline = Timeline(
        cues=tuple(
            Cue(cue_id=name, start_seconds=start, duration_seconds=0.1, kind=CueKind.LINE, source_ref=f"v/{name}.wav")
            for name, start in (("a", 0.0), ("b", 0.1), ("c", 0.2))
        ),
        tail_seconds=0.05,
    )
    clips = (
        MixClip("a", _wav([1000] * 100 + [8000] * 20)),
        MixClip("b", _wav([-8000] * 20 + list(range(80)) + [4000] * 20)),
        MixClip("c", _wav([-4000] * 100)),
    )
    return timeline, clips


def test_crossfade_changes_only_explicit_windows_and_preserves_sources():
    timeline, clips = _fixture()
    renderer = MixRenderer(sample_rate_hz=RATE)
    plain = renderer.render(timeline=timeline, clips=clips)
    transitions = (CrossfadeTransition("a", "b", 0.02), CrossfadeTransition("b", "c", 0.02))
    result = renderer.render(timeline=timeline, clips=clips, transitions=transitions)
    samples, _ = parse_wav(result.master_wav)
    original, _ = parse_wav(plain.master_wav)
    assert samples[:100] == original[:100]
    assert samples[120:200] == original[120:200]
    assert samples[220:] == original[220:]
    assert samples[100] == 8000 and samples[110] == 0 and samples[119] < -7000
    assert samples[200] == 4000 and samples[210] == 0
    assert len(samples) == 350 and not any(samples[300:])
    assert result.measured_duration_seconds == 0.35
    assert result.declared_duration_seconds == pytest.approx(0.35)
    assert result.master_wav == recombine_stems(result.stems)
    assert (
        result.master_wav == renderer.render(timeline=timeline, clips=clips, transitions=transitions[::-1]).master_wav
    )
    assert [(event.at_seconds, event.duration_seconds) for event in result.seam_report.events] == [
        (0.1, 0.02),
        (0.2, 0.02),
    ]
    assert parse_wav(clips[0].wav_bytes)[0][100] == 8000


@pytest.mark.parametrize("duration", [-1, 0, float("nan"), float("inf"), True, None, "0.02"])
def test_invalid_transition_duration_fails_closed(duration):
    with pytest.raises(MixError, match="positive and finite"):
        CrossfadeTransition("a", "b", duration)


@pytest.mark.parametrize("legacy", [0.02, -1, float("nan"), float("inf"), True, None])
def test_legacy_scalar_cannot_emit_unrendered_receipts(legacy):
    timeline, clips = _fixture()
    with pytest.raises(MixError, match="explicit CrossfadeTransition"):
        MixRenderer(sample_rate_hz=RATE).render(timeline=timeline, clips=clips, crossfade_seconds=legacy)


@pytest.mark.parametrize(
    "transition",
    [
        CrossfadeTransition("a", "c", 0.02),
        CrossfadeTransition("absent", "b", 0.02),
        CrossfadeTransition("a", "b", 0.2),
        CrossfadeTransition("a", "b", 0.0001),
    ],
)
def test_invalid_transition_window_fails_closed(transition):
    timeline, clips = _fixture()
    with pytest.raises(MixError):
        MixRenderer(sample_rate_hz=RATE).render(timeline=timeline, clips=clips, transitions=(transition,))


@pytest.mark.parametrize("problem", ["postroll", "incoming", "stem", "rate", "duplicate", "duplicate_source", "layout"])
def test_incomplete_or_conflicting_sources_fail_closed(problem):
    timeline, clips = _fixture()
    clips = list(clips)
    transitions = (CrossfadeTransition("a", "b", 0.02),)
    if problem == "postroll":
        clips[0] = MixClip("a", _wav([1000] * 100))
    elif problem == "incoming":
        clips[1] = MixClip("b", _wav([1000] * 10))
    elif problem == "stem":
        clips[1] = MixClip("b", clips[1].wav_bytes, "sfx")
    elif problem == "rate":
        clips[0] = MixClip("a", pcm_to_wav(array("h", [1000] * 120), sample_rate_hz=2000))
    elif problem == "duplicate_source":
        clips.append(clips[0])
    elif problem == "layout":
        clips = [MixClip(clip.cue_id, clip.wav_bytes, "unlisted") for clip in clips]
    else:
        transitions *= 2
    with pytest.raises(MixError):
        MixRenderer(sample_rate_hz=RATE).render(timeline=timeline, clips=tuple(clips), transitions=transitions)


@pytest.mark.parametrize("kind", [CueKind.SILENCE, CueKind.CHAPTER_MARKER])
def test_transitions_cannot_cross_designed_silence_or_markers(kind):
    timeline, clips = _fixture()
    middle = timeline.cues[1].model_copy(update={"kind": kind})
    timeline = Timeline(cues=(timeline.cues[0], middle, timeline.cues[2]))
    used_clips = (clips[0], clips[2])
    plain = MixRenderer(sample_rate_hz=RATE).render(timeline=timeline, clips=used_clips)
    assert not any(parse_wav(plain.master_wav)[0][100:200])
    with pytest.raises(MixError):
        MixRenderer(sample_rate_hz=RATE).render(
            timeline=timeline, clips=used_clips, transitions=(CrossfadeTransition("a", "c", 0.02),)
        )


def test_crossfade_cannot_fill_an_allowed_timeline_gap():
    timeline, clips = _fixture()
    second = timeline.cues[1].model_copy(update={"start_seconds": 0.105, "duration_seconds": 0.095})
    timeline = Timeline(cues=(timeline.cues[0], second, timeline.cues[2]))
    with pytest.raises(MixError, match="gaps"):
        MixRenderer(sample_rate_hz=RATE).render(
            timeline=timeline, clips=clips, transitions=(CrossfadeTransition("a", "b", 0.02),)
        )


@pytest.mark.parametrize("start,duration,incoming", [(0.0006, 0.1006, 0.1012), (0.0004, 0.1004, 0.1008)])
def test_fractional_boundaries_cannot_overlap_or_gap_in_sample_space(start, duration, incoming):
    timeline, clips = _fixture()
    left = timeline.cues[0].model_copy(update={"start_seconds": start, "duration_seconds": duration})
    right = timeline.cues[1].model_copy(update={"start_seconds": incoming})
    timeline = Timeline(cues=(left, right))
    with pytest.raises(MixError, match="gaps"):
        MixRenderer(sample_rate_hz=RATE).render(
            timeline=timeline, clips=clips[:2], transitions=(CrossfadeTransition("a", "b", 0.02),)
        )


def test_receipt_uses_actual_sample_boundary_without_changing_logical_cues():
    timeline, clips = _fixture()
    left = timeline.cues[0].model_copy(update={"start_seconds": 0.0004})
    right = timeline.cues[1].model_copy(update={"start_seconds": 0.1004})
    timeline = Timeline(cues=(left, right))
    result = MixRenderer(sample_rate_hz=RATE).render(
        timeline=timeline, clips=clips[:2], transitions=(CrossfadeTransition("a", "b", 0.02),)
    )
    assert result.seam_report.events[0].at_seconds == 0.1
    assert parse_wav(result.master_wav)[0][100] == 8000
    assert timeline.cues[1].start_seconds == 0.1004
