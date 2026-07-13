"""Batch planner tests for the S5 voice leaf.

Covers W1.5 (batch generation from parsed script) and the determinism,
over-limit, cancellation, hostile-input, and no-leakage guarantees:

* Batch renders all lines with correct per-line profile/spatial routing.
* Batch is deterministic: same plan + same slot + same prosody -> same hash.
* Over-limit generators and plans fail closed with bounded errors.
* Cancellation callback propagates a bounded ADAPTER_CANCELLED error.
* Hostile/lying mapping inputs (lying slot resolver, non-SoundPlan input)
  fail closed.
* No private marker, local path, credential, or raw provider error leaks
  into the receipt section.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable

import pytest

from kinocut_sound import (
    AudioFormat,
    ChannelLayout,
    ConversionPolicy,
    Cue,
    CueKind,
    DeliveryPolicy,
    DitherPolicy,
    Emotion,
    Line,
    PlanProvenance,
    ProfileRef,
    Prosody,
    Routing,
    SampleFormat,
    SoundPlan,
    TimeBase,
    Timeline,
)
from kinocut_sound.voice import (
    ADAPTER_CANCELLED,
    ADAPTER_LIMIT_EXCEEDED,
    BATCH_PLAN_INVALID,
    BatchPlanner,
    BatchResult,
    CLOUD_NOT_ALLOWED,
    CloudTtsAdapterStub,
    DEFAULT_MAX_BATCH_LINES,
    LocalSynthesisAdapter,
    RenderedClip,
    VoiceError,
    VoiceRoster,
    VoiceSlot,
    default_roster,
    default_slot_resolver,
)


def _format() -> AudioFormat:
    return AudioFormat(
        channel_layout=ChannelLayout.MONO,
        sample_rate_hz=22050,
        sample_format=SampleFormat.PCM_S16LE,
        time_base=TimeBase.CONTINUOUS,
        conversion=ConversionPolicy(),
        dither=DitherPolicy.NONE,
    )


def _line(
    *,
    line_id: str,
    character_id: str = "hero",
    slot_id: str = "hero_tenor",
    text_seed: str = "a",
    text_length_chars: int = 18,
    prosody: Prosody | None = None,
    emotion: Emotion | None = None,
    spatial_preset: str = "medium_room",
) -> Line:
    return Line(
        line_id=line_id,
        character_id=character_id,
        profile=ProfileRef(profile_id=slot_id, version=1),
        text_hash="sha256:" + (text_seed * 64)[:64],
        text_length_chars=text_length_chars,
        prosody=prosody or Prosody(),
        emotion=emotion or Emotion(label="neutral", intensity=0.0),
        spatial_preset=spatial_preset,
        inherit_loudness=True,
    )


def _plan(
    lines: Iterable[Line] | tuple[Line, ...],
    *,
    project_id: str = "proj_a",
    episode_id: str = "ep_1",
) -> SoundPlan:
    return SoundPlan(
        project_id=project_id,
        episode_id=episode_id,
        format=_format(),
        timeline=Timeline(
            cues=(
                Cue(
                    cue_id="cue_intro",
                    start_seconds=0.0,
                    duration_seconds=1.0,
                    kind=CueKind.SILENCE,
                    source_ref="silence/room_tone.wav",
                ),
            ),
        ),
        lines=tuple(lines) if not isinstance(lines, tuple) else lines,
        beds=(),
        layers=(),
        routing=Routing(),
        delivery=DeliveryPolicy(),
        provenance=PlanProvenance(),
        created_by="tool:test",
    )


def test_batch_renders_all_lines_with_correct_profile_and_spatial_routing():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    lines = (
        _line(line_id="line_a", slot_id="hero_tenor", text_seed="a", spatial_preset="medium_room"),
        _line(line_id="line_b", slot_id="villain_baritone", text_seed="b", spatial_preset="close_mic"),
        _line(line_id="line_c", slot_id="narrator_female_warm", text_seed="c", spatial_preset="hall"),
    )
    plan = _plan(lines)
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        result = planner.render_plan(plan)
        assert isinstance(result, BatchResult)
        assert len(result.clips) == 3
        for clip, line in zip(result.clips, lines, strict=True):
            assert isinstance(clip, RenderedClip)
            assert clip.line_id == line.line_id
            assert clip.character_id == line.character_id
            assert clip.slot_id == line.profile.profile_id
            assert clip.spatial_preset == line.spatial_preset
            assert clip.sample_rate_hz == adapter.sample_rate_hz
            assert clip.channel_count == 1
            assert clip.output_path.startswith("voice/")
            assert clip.output_hash.startswith("sha256:")
            full = os.path.join(tmp, *clip.output_path.split("/"))
            assert os.path.exists(full), f"missing wav at {clip.output_path}"


def test_batch_is_deterministic_for_same_plan_and_slot_and_prosody():
    roster = default_roster()
    lines = (
        _line(line_id="line_a", slot_id="hero_tenor", text_seed="a"),
        _line(line_id="line_b", slot_id="villain_baritone", text_seed="b"),
    )
    plan = _plan(lines)
    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        planner_a = BatchPlanner(adapter=LocalSynthesisAdapter(), roster=roster, output_dir=tmp_a)
        planner_b = BatchPlanner(adapter=LocalSynthesisAdapter(), roster=roster, output_dir=tmp_b)
        result_a = planner_a.render_plan(plan)
        result_b = planner_b.render_plan(plan)
        assert tuple(c.output_hash for c in result_a.clips) == tuple(c.output_hash for c in result_b.clips)
        assert result_a.receipt_section.plan_hash == result_b.receipt_section.plan_hash


def test_batch_per_line_profile_versions_match_plan_lines():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    lines = (
        _line(line_id="line_a", slot_id="hero_tenor", text_seed="a"),
        _line(line_id="line_b", slot_id="android_neutral", text_seed="b"),
    )
    plan = _plan(lines)
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        result = planner.render_plan(plan)
        section = result.receipt_section
        expected = tuple((line.profile.profile_id, line.profile.version) for line in plan.lines)
        assert section.profile_versions == expected


def test_batch_receipt_section_has_bounded_loudness_and_human_review_required():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    plan = _plan((_line(line_id="only_line"),))
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        result = planner.render_plan(plan)
        loudness = result.receipt_section.loudness
        assert loudness.integrated_lufs < 0
        assert loudness.true_peak_dbtp < 0
        assert 0 <= loudness.lra_lu <= 24
        assert loudness.within_tolerance is True
        assert result.receipt_section.human_review_required is True


def test_batch_over_limit_lines_fail_closed():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    # Generator that exceeds the small ceiling.
    too_many = (_line(line_id=f"line_{i}") for i in range(8))
    plan = _plan(too_many)
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir=tmp,
            max_lines=4,
        )
        with pytest.raises(VoiceError) as exc:
            planner.render_plan(plan)
        assert exc.value.code == ADAPTER_LIMIT_EXCEEDED


def test_batch_over_limit_static_lines_fail_closed():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    lines = tuple(_line(line_id=f"line_{i}") for i in range(5))
    plan = _plan(lines)
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir=tmp,
            max_lines=4,
        )
        with pytest.raises(VoiceError) as exc:
            planner.render_plan(plan)
        assert exc.value.code == ADAPTER_LIMIT_EXCEEDED


def test_batch_refuses_cloud_stub_adapter_without_opt_in():
    roster = default_roster()
    stub = CloudTtsAdapterStub()
    plan = _plan((_line(line_id="only_line"),))
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=stub, roster=roster, output_dir=tmp)
        with pytest.raises(VoiceError) as exc:
            planner.render_plan(plan)
        assert exc.value.code == CLOUD_NOT_ALLOWED


def test_batch_cancellation_callback_propagates_bounded_error():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    lines = tuple(_line(line_id=f"line_{i}") for i in range(3))
    plan = _plan(lines)

    def _cancel() -> None:
        raise RuntimeError("user pressed cancel")

    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        with pytest.raises(VoiceError) as exc:
            planner.render_plan(plan, check_cancelled=_cancel)
        assert exc.value.code == ADAPTER_CANCELLED


def test_batch_cancellation_with_voice_error_passes_through():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    lines = (_line(line_id="line_a"), _line(line_id="line_b"))
    plan = _plan(lines)

    sentinel = VoiceError("sentinel", code="custom_signal", suggested_action={"auto_fix": False})

    def _cancel() -> None:
        raise sentinel

    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        with pytest.raises(VoiceError) as exc:
            planner.render_plan(plan, check_cancelled=_cancel)
        assert exc.value is sentinel


def test_batch_rejects_non_soundplan_input():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        with pytest.raises(VoiceError) as exc:
            planner.render_plan("not_a_plan")  # type: ignore[arg-type]
        assert exc.value.code == BATCH_PLAN_INVALID


def test_batch_default_slot_resolver_uses_profile_id():
    roster = default_roster()
    line = _line(line_id="only", slot_id="hero_tenor")
    slot = default_slot_resolver(line, roster)
    assert isinstance(slot, VoiceSlot)
    assert slot.slot_id == "hero_tenor"


def test_batch_default_slot_resolver_fails_for_unknown_profile_id():
    roster = default_roster()
    line = _line(line_id="only", slot_id="missing_slot_id_xyz")
    with pytest.raises(VoiceError):
        default_slot_resolver(line, roster)


def test_batch_rejects_lying_slot_resolver_returning_unknown_slot():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    plan = _plan((_line(line_id="only", slot_id="hero_tenor"),))

    def _lying(line: Line, roster: VoiceRoster) -> VoiceSlot:
        # Returns a slot that exists as an object but is not in the roster's
        # sealed slot map (a different id).
        return roster.get("villain_baritone")

    # Mutate the slot id on the returned slot by re-fetching and creating a
    # fresh slot the planner cannot find in its roster.
    from kinocut_sound.voice.roster import VoiceSlot, VoiceSlotBase

    base = VoiceSlotBase(pitch_semitones=0.0, rate=1.0, volume_db=0.0, formant_offset=0.0)
    lying_slot = VoiceSlot(
        slot_id="not_in_roster",
        display_label="not_in_roster",
        base=base,
        description_hash="sha256:" + "0" * 64,
    )

    def _resolver(line: Line, roster: VoiceRoster) -> VoiceSlot:
        return lying_slot

    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir=tmp,
            slot_resolver=_resolver,
        )
        with pytest.raises(VoiceError) as exc:
            planner.render_plan(plan)
        assert exc.value.code == BATCH_PLAN_INVALID


def test_batch_rejects_non_voice_slot_resolver_return_value():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    plan = _plan((_line(line_id="only"),))

    def _bad(line: Line, roster: VoiceRoster) -> object:
        return "not_a_slot"

    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir=tmp,
            slot_resolver=_bad,  # type: ignore[arg-type]
        )
        with pytest.raises(VoiceError) as exc:
            planner.render_plan(plan)
        assert exc.value.code == BATCH_PLAN_INVALID


def test_batch_receipt_does_not_leak_host_paths_credentials_or_prompts():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    plan = _plan((_line(line_id="only"),))
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        result = planner.render_plan(plan)
        section_repr = repr(result.receipt_section.model_dump(mode="json"))
        assert tmp not in section_repr  # output_dir never serialized
        assert "/home/" not in section_repr
        assert "password" not in section_repr.lower()
        assert "api_key" not in section_repr.lower()
        for clip in result.clips:
            assert tmp not in clip.output_path
            assert clip.output_path.startswith("voice/")
            # Raw prompt text never appears (only text_hash).
            assert "secret text" not in clip.output_path.lower()


def test_batch_write_outputs_false_skips_disk_write_but_keeps_receipt():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    plan = _plan((_line(line_id="only"),))
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        result = planner.render_plan(plan, write_outputs=False)
        assert len(result.clips) == 1
        # Output file is not written.
        full = os.path.join(tmp, *result.clips[0].output_path.split("/"))
        assert not os.path.exists(full)
        # But the hash/duration are still present.
        assert result.clips[0].output_hash.startswith("sha256:")
        assert result.clips[0].duration_seconds > 0


def test_batch_default_max_lines_matches_design_ceiling():
    assert DEFAULT_MAX_BATCH_LINES == 4096


def test_batch_rejects_invalid_constructor_inputs():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    with pytest.raises(VoiceError):
        BatchPlanner(adapter=adapter, roster=roster, output_dir="", max_lines=10)
    with pytest.raises(VoiceError):
        BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir="out",
            max_lines=0,
        )
    with pytest.raises(VoiceError):
        BatchPlanner(
            adapter=adapter,
            roster=roster,
            output_dir="out",
            max_lines=True,  # type: ignore[arg-type]
        )


def test_batch_adapts_to_distinct_roster_slot_per_line_through_overrides():
    roster = default_roster()
    adapter = LocalSynthesisAdapter()
    lines = (
        _line(line_id="line_a", slot_id="hero_tenor", text_seed="a"),
        _line(line_id="line_b", slot_id="heroine_soprano", text_seed="b"),
    )
    plan = _plan(lines)
    with tempfile.TemporaryDirectory() as tmp:
        planner = BatchPlanner(adapter=adapter, roster=roster, output_dir=tmp)
        result = planner.render_plan(plan)
        slot_ids = {clip.slot_id for clip in result.clips}
        assert slot_ids == {"hero_tenor", "heroine_soprano"}
        # Per-line output paths route through the slot id directory.
        for clip, line in zip(result.clips, lines, strict=True):
            assert clip.output_path == f"voice/{line.profile.profile_id}/{line.line_id}.wav"
