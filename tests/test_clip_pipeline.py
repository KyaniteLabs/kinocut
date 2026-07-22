"""Tests for :mod:`kinocut.product.clip_pipeline`.

Covers the platform-budget contract (YouTube Shorts 180 s, Instagram Reels
90 s), complete-thought preservation, safe static composition fallback for
low-confidence / abstained tracks, deterministic plan ids, and the fail-closed
behaviour on unknown platforms and malformed moments.

The helpers under test never invoke FFmpeg and never touch media; the tests
stay pure-Python and deterministic.
"""

from __future__ import annotations

import pytest

from kinocut.product.clip_pipeline import (
    CLIP_DURATION_BELOW_MINIMUM,
    CLIP_INVALID_TIME_RANGE,
    CLIP_UNKNOWN_PLATFORM,
    ClipPlan,
    ClippedMoment,
    MIN_CLIP_DURATION_SECONDS,
    PLATFORM_MAX_DURATIONS,
    PLATFORMS,
    StaticCompositionRequest,
    clip_moment,
    clip_moments,
    plan_safe_static_composition,
    platform_max_duration,
)


# --- platform max durations --------------------------------------------------


def test_platform_max_durations_youtube_shorts_is_180_seconds() -> None:
    """The canonical YouTube Shorts cap is 180 seconds (3 minutes)."""

    assert PLATFORM_MAX_DURATIONS["youtube_shorts"] == 180.0
    assert platform_max_duration("youtube_shorts") == 180.0


def test_platform_max_durations_instagram_reels_is_90_seconds() -> None:
    """The canonical Instagram Reels cap is 90 seconds."""

    assert PLATFORM_MAX_DURATIONS["instagram_reels"] == 90.0
    assert platform_max_duration("instagram_reels") == 90.0


def test_platforms_tuple_lists_exactly_two_known_platforms() -> None:
    """The frozen platform set is closed; the orchestrator never picks another."""

    assert set(PLATFORMS) == {"youtube_shorts", "instagram_reels"}
    assert len(PLATFORMS) == 2


def test_unknown_platform_raises_fail_closed() -> None:
    """An unknown platform fails closed with the canonical error code."""

    with pytest.raises(ValueError) as exc_info:
        platform_max_duration("tiktok")
    assert CLIP_UNKNOWN_PLATFORM in str(exc_info.value)


def test_platform_max_durations_is_immutable() -> None:
    """The budget table is read-only so downstream code cannot widen it."""

    with pytest.raises(TypeError):
        PLATFORM_MAX_DURATIONS["youtube_shorts"] = 999.0  # type: ignore[index]


# --- complete-thought preservation -------------------------------------------


def test_clip_moment_preserves_range_when_within_budget() -> None:
    """A moment inside the platform budget keeps its original range unchanged."""

    moment = {"moment_id": "m:abc123", "start": 10.0, "end": 25.0}
    clipped = clip_moment(moment, platform="youtube_shorts")
    assert clipped.was_clipped is False
    assert clipped.start_seconds == 10.0
    assert clipped.end_seconds == 25.0
    assert clipped.duration_seconds == 15.0
    assert clipped.original_start_seconds == 10.0
    assert clipped.original_end_seconds == 25.0
    assert clipped.original_duration_seconds == 15.0
    assert clipped.review_warning is None


def test_clip_moment_truncates_when_over_youtube_budget() -> None:
    """A moment over the YouTube Shorts cap is truncated, original preserved."""

    moment = {"moment_id": "m:over", "start": 0.0, "end": 240.0}
    clipped = clip_moment(moment, platform="youtube_shorts")
    assert clipped.was_clipped is True
    assert clipped.start_seconds == 0.0
    assert clipped.end_seconds == 180.0
    assert clipped.duration_seconds == 180.0
    assert clipped.original_start_seconds == 0.0
    assert clipped.original_end_seconds == 240.0
    assert clipped.original_duration_seconds == 240.0
    assert clipped.review_warning is not None
    assert "exceeded" in clipped.review_warning


def test_clip_moment_truncates_when_over_instagram_budget() -> None:
    """The Reels cap is strictly tighter; an over-budget moment is truncated."""

    moment = {"moment_id": "m:reelover", "start": 5.0, "end": 200.0}
    clipped = clip_moment(moment, platform="instagram_reels")
    assert clipped.was_clipped is True
    assert clipped.start_seconds == 5.0
    assert clipped.end_seconds == 5.0 + 90.0
    assert clipped.duration_seconds == 90.0
    assert clipped.original_start_seconds == 5.0
    assert clipped.original_end_seconds == 200.0


def test_clip_moment_exact_budget_is_not_clipped() -> None:
    """A moment whose duration equals the platform cap is NOT clipped."""

    moment = {"moment_id": "m:exact", "start": 0.0, "end": 180.0}
    clipped = clip_moment(moment, platform="youtube_shorts")
    assert clipped.was_clipped is False
    assert clipped.duration_seconds == 180.0


def test_clip_moment_keeps_complete_thought_when_within_budget() -> None:
    """Original range is preserved when it already fits — complete-thought contract."""

    moment = {"moment_id": "m:thought", "start": 30.0, "end": 175.0}
    clipped = clip_moment(moment, platform="youtube_shorts")
    assert clipped.was_clipped is False
    assert (clipped.start_seconds, clipped.end_seconds) == (30.0, 175.0)


# --- moment validation -------------------------------------------------------


def test_clip_moment_rejects_invalid_time_range() -> None:
    """end <= start is a fail-closed violation."""

    with pytest.raises(ValueError) as exc_info:
        clip_moment({"moment_id": "m:bad", "start": 10.0, "end": 5.0}, platform="youtube_shorts")
    assert CLIP_INVALID_TIME_RANGE in str(exc_info.value)


def test_clip_moment_rejects_missing_moment_id() -> None:
    """A moment mapping without an id is rejected."""

    with pytest.raises(ValueError) as exc_info:
        clip_moment({"start": 0.0, "end": 10.0}, platform="youtube_shorts")
    assert CLIP_INVALID_TIME_RANGE in str(exc_info.value)


def test_clip_moment_below_minimum_uses_safe_fallback_by_default() -> None:
    """Sub-minimum durations get a safe preview + a review warning, not a raise."""

    moment = {"moment_id": "m:short", "start": 0.0, "end": 0.5}
    clipped = clip_moment(moment, platform="youtube_shorts")
    assert clipped.was_clipped is False
    assert clipped.review_warning is not None
    assert "below" in clipped.review_warning


def test_clip_moment_below_minimum_raises_when_safe_fallback_disabled() -> None:
    """With ``allow_safe_fallback=False`` the helper fails closed."""

    moment = {"moment_id": "m:short", "start": 0.0, "end": 0.5}
    with pytest.raises(ValueError) as exc_info:
        clip_moment(moment, platform="youtube_shorts", allow_safe_fallback=False)
    assert CLIP_DURATION_BELOW_MINIMUM in str(exc_info.value)


def test_clip_moment_accepts_object_with_attributes() -> None:
    """Objects exposing ``moment_id``, ``start``, ``end`` also work."""

    class _Obj:
        moment_id = "m:obj"
        start = 5.0
        end = 50.0

    clipped = clip_moment(_Obj(), platform="youtube_shorts")
    assert clipped.start_seconds == 5.0
    assert clipped.end_seconds == 50.0


# --- clip_moments (plan) -----------------------------------------------------


def test_clip_moments_builds_deterministic_plan() -> None:
    """A multi-moment plan is deterministic and JSON-stable."""

    moments = (
        {"moment_id": "m:1", "start": 0.0, "end": 30.0},
        {"moment_id": "m:2", "start": 60.0, "end": 120.0},
    )
    a = clip_moments(moments, platform="youtube_shorts")
    b = clip_moments(moments, platform="youtube_shorts")
    assert a.plan_id == b.plan_id
    assert a.plan_id.startswith("sha256:")
    assert a.platform == "youtube_shorts"
    assert a.platform_max_duration_seconds == 180.0
    assert len(a.clipped_moments) == 2
    assert a.clipped_moments[0].moment_id == "m:1"
    assert a.clipped_moments[1].moment_id == "m:2"


def test_clip_moments_captures_rejections_and_warnings() -> None:
    """Malformed moments are captured in ``rejected_moments``, plan still builds."""

    moments = (
        {"moment_id": "m:good", "start": 0.0, "end": 10.0},
        {"moment_id": "m:bad", "start": 20.0, "end": 10.0},  # invalid range
    )
    plan = clip_moments(moments, platform="youtube_shorts")
    assert len(plan.clipped_moments) == 1
    assert plan.clipped_moments[0].moment_id == "m:good"
    assert plan.rejected_moments == ("m:bad",)
    assert any("rejected moment" in warning for warning in plan.review_warnings)


def test_clip_moments_emits_no_review_warnings_when_all_fit() -> None:
    """Well-formed moments within budget produce zero review warnings."""

    moments = ({"moment_id": "m:a", "start": 0.0, "end": 10.0},)
    plan = clip_moments(moments, platform="instagram_reels")
    assert plan.review_warnings == ()


def test_clip_plan_strict_model_rejects_invalid_inputs() -> None:
    """The frozen strict model refuses extra fields and bad ids."""

    with pytest.raises(Exception):
        ClipPlan(
            plan_id="not-a-sha",
            platform="youtube_shorts",
            platform_max_duration_seconds=180.0,
        )
    with pytest.raises(Exception):
        ClipPlan(
            plan_id="sha256:" + "a" * 64,
            platform="not_a_platform",
            platform_max_duration_seconds=180.0,
        )


# --- safe static composition fallback ---------------------------------------


def test_plan_safe_static_composition_builds_single_partial_plan() -> None:
    """The fallback returns exactly one moment, marked static_composition=True."""

    request = StaticCompositionRequest(
        moment_id="m:fallback",
        platform="youtube_shorts",
        start_seconds=10.0,
        end_seconds=20.0,
        reason="no_face_detected",
    )
    plan = plan_safe_static_composition(request)
    assert isinstance(plan, ClipPlan)
    assert plan.static_composition is True
    assert len(plan.clipped_moments) == 1
    assert plan.clipped_moments[0].moment_id == "m:fallback"
    assert plan.clipped_moments[0].review_warning is not None
    assert "PARTIAL" in plan.clipped_moments[0].review_warning
    assert any("PARTIAL" in warning for warning in plan.review_warnings)


def test_plan_safe_static_composition_accepts_mapping() -> None:
    """The fallback accepts loose mappings as well as strict requests."""

    plan = plan_safe_static_composition(
        {
            "moment_id": "m:dict",
            "platform": "instagram_reels",
            "start_seconds": 0.0,
            "end_seconds": 30.0,
            "reason": "abstained",
        }
    )
    assert plan.static_composition is True
    assert plan.platform == "instagram_reels"
    assert plan.platform_max_duration_seconds == 90.0


def test_plan_safe_static_composition_fails_closed_on_oversized_range() -> None:
    """The fallback never produces a clip beyond the platform cap."""

    with pytest.raises(ValueError):
        plan_safe_static_composition(
            {
                "moment_id": "m:big",
                "platform": "instagram_reels",
                "start_seconds": 0.0,
                "end_seconds": 200.0,  # > 90 s
                "reason": "test",
            }
        )


def test_plan_safe_static_composition_rejects_static_composition_with_multiple_moments() -> None:
    """The strict model rejects a plan that mislabels multiple moments as static."""

    with pytest.raises(Exception):
        ClipPlan(
            plan_id="sha256:" + "a" * 64,
            platform="youtube_shorts",
            platform_max_duration_seconds=180.0,
            clipped_moments=(
                ClippedMoment(
                    moment_id="a",
                    platform="youtube_shorts",
                    start_seconds=0.0,
                    end_seconds=10.0,
                    duration_seconds=10.0,
                    original_start_seconds=0.0,
                    original_end_seconds=10.0,
                    original_duration_seconds=10.0,
                ),
                ClippedMoment(
                    moment_id="b",
                    platform="youtube_shorts",
                    start_seconds=20.0,
                    end_seconds=30.0,
                    duration_seconds=10.0,
                    original_start_seconds=20.0,
                    original_end_seconds=30.0,
                    original_duration_seconds=10.0,
                ),
            ),
            static_composition=True,
        )


def test_clip_plan_id_is_deterministic_across_calls() -> None:
    """Two equal inputs collapse to the same plan id."""

    moments = ({"moment_id": "m:x", "start": 0.0, "end": 10.0},)
    a = clip_moments(moments, platform="instagram_reels")
    b = clip_moments(moments, platform="instagram_reels")
    assert a.plan_id == b.plan_id


def test_min_clip_duration_is_one_second() -> None:
    """The floor is fixed; the orchestrator never plans sub-second clips."""

    assert MIN_CLIP_DURATION_SECONDS == 1.0


def test_static_composition_request_rejects_inverted_range() -> None:
    """The strict request model rejects end <= start."""

    with pytest.raises(Exception):
        StaticCompositionRequest(
            moment_id="m:bad",
            platform="youtube_shorts",
            start_seconds=10.0,
            end_seconds=5.0,
            reason="x",
        )


def test_clip_moment_accepts_candidate_id_alias() -> None:
    """Moments using ``candidate_id`` (the strict ``CandidateMoment`` field) also work."""

    moment = {"candidate_id": "moment:abc123def4567", "start": 10.0, "end": 25.0}
    clipped = clip_moment(moment, platform="youtube_shorts")
    assert clipped.moment_id == "moment:abc123def4567"
    assert clipped.was_clipped is False


def test_clip_moment_accepts_candidate_id_object() -> None:
    """An object exposing ``candidate_id`` / ``start`` / ``end`` also works."""

    class _Candidate:
        candidate_id = "moment:xyz789"
        start = 5.0
        end = 50.0

    clipped = clip_moment(_Candidate(), platform="youtube_shorts")
    assert clipped.moment_id == "moment:xyz789"
    assert clipped.start_seconds == 5.0
    assert clipped.end_seconds == 50.0
