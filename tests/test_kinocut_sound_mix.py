"""RED/green tests for S9 mix assembly leaf (W3.x, G06-G09, G20)."""

from __future__ import annotations

import os
import tempfile

import pytest

from kinocut_sound.delivery import DeliveryPolicy, StemLayout, StemRecombinationPolicy
from kinocut_sound.mix import (
    MixClip,
    MixError,
    MixRenderer,
    compensate_latency,
    crossfade_pair,
    duck_bed_under_speech,
    place_clips,
    recombine_stems,
    render_silence,
    build_stem_bundle,
)
from kinocut_sound.mix._wav import duration_seconds, synthesize_tone
from kinocut_sound.script_parser import SilenceQuality
from kinocut_sound.timeline import Cue, CueKind, Timeline


def _timeline() -> Timeline:
    return Timeline(
        cues=(
            Cue(
                cue_id="line_1",
                start_seconds=0.0,
                duration_seconds=0.5,
                kind=CueKind.LINE,
                source_ref="voice/hero/line_1.wav",
            ),
            Cue(
                cue_id="gap_1",
                start_seconds=0.5,
                duration_seconds=0.2,
                kind=CueKind.SILENCE,
                source_ref="silence/dead.wav",
            ),
            Cue(
                cue_id="line_2",
                start_seconds=0.7,
                duration_seconds=0.5,
                kind=CueKind.LINE,
                source_ref="voice/hero/line_2.wav",
            ),
            Cue(
                cue_id="sfx_1",
                start_seconds=1.2,
                duration_seconds=0.3,
                kind=CueKind.FOLEY,
                source_ref="sfx/door.wav",
            ),
        )
    )


def test_place_clips_orders_and_assigns_stems():
    plan = place_clips(
        _timeline(),
        clip_durations={"line_1": 0.5, "line_2": 0.5, "sfx_1": 0.3},
    )
    assert plan.silence_cues == ("gap_1",)
    assert [p.cue_id for p in plan.placements] == ["line_1", "line_2", "sfx_1"]
    stems = {p.cue_id: p.stem_id for p in plan.placements}
    assert stems["line_1"] == "dialogue"
    assert stems["sfx_1"] == "sfx"
    assert plan.timeline_duration_seconds >= 1.3


def test_place_clips_fails_closed_on_missing_duration():
    with pytest.raises(MixError) as exc:
        place_clips(_timeline(), clip_durations={"line_1": 0.5})
    assert exc.value.code == "mix_placement_invalid"


def test_crossfade_pair_length_and_determinism():
    a = synthesize_tone(duration_seconds=0.4, frequency_hz=220.0, seed=1)
    b = synthesize_tone(duration_seconds=0.4, frequency_hz=440.0, seed=2)
    out1 = crossfade_pair(a, b, fade_seconds=0.05)
    out2 = crossfade_pair(a, b, fade_seconds=0.05)
    assert out1 == out2
    # shorter than concat without fade
    plain = duration_seconds(a) + duration_seconds(b)
    assert duration_seconds(out1) < plain
    assert duration_seconds(out1) == pytest.approx(plain - 0.05, abs=0.02)


def test_render_silence_qualities():
    dead = render_silence(duration_seconds=0.25, quality=SilenceQuality.DEAD)
    room = render_silence(duration_seconds=0.25, quality="room_tone")
    assert duration_seconds(dead) == pytest.approx(0.25, abs=0.02)
    assert dead != room


def test_duck_bed_reduces_energy_under_speech():
    speech = synthesize_tone(duration_seconds=0.4, frequency_hz=300.0, amplitude=0.4, seed=3)
    bed = synthesize_tone(duration_seconds=0.4, frequency_hz=80.0, amplitude=0.4, seed=4)
    ducked = duck_bed_under_speech(speech, bed, attenuation_db=12.0)
    assert len(ducked) == len(bed)
    # ducked should differ from original bed
    assert ducked != bed


def test_latency_compensation_delays():
    wav = synthesize_tone(duration_seconds=0.1, seed=5)
    delayed = compensate_latency(wav, residual_samples=100)
    assert duration_seconds(delayed) > duration_seconds(wav)


def test_stem_recombine_roundtrip():
    d = synthesize_tone(duration_seconds=0.2, frequency_hz=200.0, seed=6)
    a = synthesize_tone(duration_seconds=0.2, frequency_hz=100.0, seed=7)
    layout = StemLayout(stem_ids=("dialogue", "ambience"))
    bundle = build_stem_bundle(layout=layout, stem_wavs={"dialogue": d, "ambience": a})
    master = recombine_stems(bundle, policy=StemRecombinationPolicy())
    assert duration_seconds(master) == pytest.approx(0.2, abs=0.02)


def test_mix_renderer_duration_proof_and_stems():
    timeline = _timeline()
    clips = (
        MixClip(cue_id="line_1", wav_bytes=synthesize_tone(duration_seconds=0.5, seed=10), stem_id="dialogue"),
        MixClip(cue_id="line_2", wav_bytes=synthesize_tone(duration_seconds=0.5, seed=11), stem_id="dialogue"),
        MixClip(cue_id="sfx_1", wav_bytes=synthesize_tone(duration_seconds=0.3, seed=12), stem_id="sfx"),
    )
    bed = synthesize_tone(duration_seconds=1.5, frequency_hz=70.0, amplitude=0.15, seed=13)
    renderer = MixRenderer(tail_seconds=0.1)
    result = renderer.render(
        timeline=timeline,
        clips=clips,
        bed_wav=bed,
        delivery=DeliveryPolicy(stems=StemLayout(stem_ids=("dialogue", "ambience", "sfx"))),
        crossfade_seconds=0.05,
        duck_bed=True,
    )
    assert result.within_tolerance is True
    assert result.measured_duration_seconds == pytest.approx(result.declared_duration_seconds, abs=0.02)
    assert result.declared_duration_seconds >= 1.4
    assert set(result.stems.stems) >= {"dialogue", "ambience", "sfx"}
    assert result.seam_report.count >= 1


def test_mix_export_rejects_traversal():
    timeline = Timeline(
        cues=(
            Cue(
                cue_id="line_1",
                start_seconds=0.0,
                duration_seconds=0.2,
                kind=CueKind.LINE,
                source_ref="voice/a.wav",
            ),
        )
    )
    renderer = MixRenderer()
    result = renderer.render(
        timeline=timeline,
        clips=(MixClip(cue_id="line_1", wav_bytes=synthesize_tone(duration_seconds=0.2, seed=1)),),
    )
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(MixError):
            renderer.export_master(result, output_path="../escape.wav", output_dir=tmp)
        path = renderer.export_master(result, output_path="mix/master.wav", output_dir=tmp)
        assert os.path.exists(os.path.join(tmp, "mix", "master.wav"))
        assert path == "mix/master.wav"


def test_mix_package_public_surface():
    from kinocut_sound import mix as m

    assert {"MixRenderer", "place_clips", "crossfade_pair", "render_silence", "duck_bed_under_speech"} <= set(m.__all__)
