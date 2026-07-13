"""Seamless loop generator tests for the S8 world leaf.

Covers required row:
* loop generator produces expected duration with seamless crossfade.

Plus hardening: crossfade-too-large fails closed; loop digest is stable; scene
crossfade beds must differ.
"""

from __future__ import annotations

import pytest

from kinocut_sound.world import (
    LoopResult,
    SceneCrossfade,
    SeamlessLoop,
    WorldError,
    generate_loop,
    scene_crossfade,
)


def test_loop_source_alone_covers_target_emits_no_seams():
    plan = SeamlessLoop(
        loop_label="short",
        source_duration_seconds=120.0,
        target_duration_seconds=60.0,
        crossfade_seconds=0.5,
    )
    result = generate_loop(plan)
    assert result.repeats == 1
    assert result.effective_duration_seconds == pytest.approx(120.0)
    assert result.seams == ()


def test_loop_generator_produces_expected_duration_with_seam_crossfade():
    plan = SeamlessLoop(
        loop_label="common_room",
        source_duration_seconds=120.0,
        target_duration_seconds=900.0,
        crossfade_seconds=0.5,
    )
    result = generate_loop(plan)
    # Step = 120 - 0.5 = 119.5. repeats is smallest N so 120 + (N-1)*119.5 >= 900.
    # 120 + 7*119.5 = 956.5 >= 900 -> 8 repeats.
    assert result.repeats == 8
    assert result.effective_duration_seconds == pytest.approx(956.5)
    # Seven seams, each of length crossfade_seconds, spaced by the step.
    assert len(result.seams) == 7
    first = result.seams[0]
    assert first.index == 1
    assert first.start_seconds == pytest.approx(119.5)
    assert first.end_seconds == pytest.approx(120.0)
    # Seams are monotonically ordered in time.
    starts = [seam.start_seconds for seam in result.seams]
    assert starts == sorted(starts)
    # The effective duration is the final seam end (last repeat finishes).
    last = result.seams[-1]
    assert last.end_seconds == pytest.approx(last.start_seconds + 0.5)


def test_loop_digest_is_stable_for_identical_plans():
    plan = SeamlessLoop(
        loop_label="garden",
        source_duration_seconds=240.0,
        target_duration_seconds=960.0,
        crossfade_seconds=1.0,
    )
    a = generate_loop(plan).digest()
    b = generate_loop(plan).digest()
    assert a == b
    # A different label yields a different digest.
    other = generate_loop(
        SeamlessLoop(
            loop_label="garden_alt",
            source_duration_seconds=240.0,
            target_duration_seconds=960.0,
            crossfade_seconds=1.0,
        )
    ).digest()
    assert other != a


def test_crossfade_consuming_whole_source_fails_closed():
    with pytest.raises(WorldError) as exc:
        generate_loop(
            SeamlessLoop(
                loop_label="bad",
                source_duration_seconds=120.0,
                target_duration_seconds=900.0,
                crossfade_seconds=120.0,  # step -> 0
            )
        )
    assert exc.value.code == "loop_invalid"


def test_loop_result_round_trips_through_digest_fields():
    plan = SeamlessLoop(
        loop_label="corridor",
        source_duration_seconds=90.0,
        target_duration_seconds=360.0,
        crossfade_seconds=0.25,
    )
    result = generate_loop(plan)
    assert isinstance(result, LoopResult)
    # Effective duration covers the target.
    assert result.effective_duration_seconds >= 360.0
    # Re-computing the same plan returns the same effective duration and seams.
    again = generate_loop(plan)
    assert again.effective_duration_seconds == result.effective_duration_seconds
    assert again.seams == result.seams


def test_scene_crossfade_requires_distinct_beds_and_positive_timings():
    cross = scene_crossfade(
        from_bed_id="bed_common_room",
        to_bed_id="bed_garden",
        crossfade_seconds=2.0,
        start_seconds=120.0,
    )
    assert isinstance(cross, SceneCrossfade)
    assert cross.from_bed_id == "bed_common_room"
    # Same bed is rejected.
    with pytest.raises(WorldError) as exc:
        scene_crossfade(
            from_bed_id="bed_x",
            to_bed_id="bed_x",
            crossfade_seconds=1.0,
            start_seconds=10.0,
        )
    assert exc.value.code == "loop_invalid"
    # Non-positive timing is rejected.
    with pytest.raises(WorldError):
        scene_crossfade(
            from_bed_id="bed_a",
            to_bed_id="bed_b",
            crossfade_seconds=0.0,
            start_seconds=10.0,
        )
