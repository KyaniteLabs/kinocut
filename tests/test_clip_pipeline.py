"""Tests for the platform-aware clip pipeline."""

from __future__ import annotations

import pytest

from kinocut.product.clip_pipeline import (
    CLIP_DURATION_BELOW_MINIMUM,
    CLIP_INVALID_TIME_RANGE,
    CLIP_UNKNOWN_PLATFORM,
    ClippedMoment,
    PLATFORM_MAX_DURATIONS,
    PLATFORMS,
    clip_moment,
    platform_max_duration,
)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("youtube_shorts", 180.0), ("instagram_reels", 90.0)],
)
def test_platform_max_durations(platform: str, expected: float) -> None:
    assert platform_max_duration(platform) == expected
    assert PLATFORM_MAX_DURATIONS[platform] == expected


def test_platform_max_durations_is_immutable() -> None:
    with pytest.raises(TypeError):
        PLATFORM_MAX_DURATIONS["youtube_shorts"] = 999.0  # type: ignore[index]


def test_unknown_platform_raises_fail_closed() -> None:
    with pytest.raises(ValueError) as exc_info:
        platform_max_duration("tiktok")
    assert CLIP_UNKNOWN_PLATFORM in str(exc_info.value)


def test_platform_literal_is_closed_to_two_known_ids() -> None:
    assert set(PLATFORMS) == {"youtube_shorts", "instagram_reels"}


def test_clip_moment_preserves_range_when_within_budget() -> None:
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


@pytest.mark.parametrize(
    ("platform", "start", "end", "effective_end"),
    [("youtube_shorts", 0.0, 240.0, 180.0), ("instagram_reels", 5.0, 200.0, 95.0)],
)
def test_clip_moment_explicit_truncation(platform: str, start: float, end: float, effective_end: float) -> None:
    clipped = clip_moment({"moment_id": "m:over", "start": start, "end": end}, platform=platform)
    assert clipped.was_clipped is True
    assert clipped.start_seconds == start
    assert clipped.end_seconds == effective_end
    assert clipped.duration_seconds == effective_end - start
    assert clipped.original_start_seconds == start
    assert clipped.original_end_seconds == end
    assert clipped.original_duration_seconds == end - start
    assert clipped.review_warning is not None
    assert "exceeded" in clipped.review_warning


def test_clip_moment_short_preview_emits_warning_by_default() -> None:
    moment = {"moment_id": "m:short", "start": 0.0, "end": 0.5}
    clipped = clip_moment(moment, platform="youtube_shorts")
    assert clipped.was_clipped is False
    assert clipped.start_seconds == 0.0
    assert clipped.end_seconds == 0.5
    assert clipped.review_warning is not None
    assert "below" in clipped.review_warning
    assert "short preview" in clipped.review_warning


def test_clip_moment_below_minimum_raises_when_safe_fallback_disabled() -> None:
    moment = {"moment_id": "m:short", "start": 0.0, "end": 0.5}
    with pytest.raises(ValueError) as exc_info:
        clip_moment(moment, platform="youtube_shorts", allow_safe_fallback=False)
    assert CLIP_DURATION_BELOW_MINIMUM in str(exc_info.value)


def test_clip_moment_rejects_inverted_range() -> None:
    with pytest.raises(ValueError) as exc_info:
        clip_moment({"moment_id": "m:bad", "start": 10.0, "end": 5.0}, platform="youtube_shorts")
    assert CLIP_INVALID_TIME_RANGE in str(exc_info.value)


@pytest.mark.parametrize(
    "moment",
    [
        {"moment_id": "negative", "start": -1.0, "end": 2.0},
        {"moment_id": "bool", "start": False, "end": True},
    ],
)
def test_clip_moment_rejects_non_media_ranges(moment: dict[str, object]) -> None:
    with pytest.raises(ValueError) as exc_info:
        clip_moment(moment, platform="youtube_shorts")
    assert CLIP_INVALID_TIME_RANGE in str(exc_info.value)


def test_clip_moment_rejects_missing_moment_id() -> None:
    with pytest.raises(ValueError) as exc_info:
        clip_moment({"start": 0.0, "end": 10.0}, platform="youtube_shorts")
    assert CLIP_INVALID_TIME_RANGE in str(exc_info.value)


def test_clipped_moment_is_strict_deterministic_value_object() -> None:
    moment = {"moment_id": "m:det", "start": 10.0, "end": 25.0}
    a = clip_moment(moment, platform="youtube_shorts")
    b = clip_moment(moment, platform="youtube_shorts")
    assert a.model_dump(mode="json") == b.model_dump(mode="json")
    with pytest.raises(Exception):
        ClippedMoment.model_validate(
            {"moment_id": "m:x", "platform": "not_a_platform", "start_seconds": 0.0, "end_seconds": 1.0}
        )


def test_clipped_moment_rejects_direct_over_budget_construction() -> None:
    with pytest.raises(ValueError, match="platform maximum"):
        ClippedMoment(
            moment_id="over",
            platform="instagram_reels",
            start_seconds=0.0,
            end_seconds=100.0,
            duration_seconds=100.0,
            original_start_seconds=0.0,
            original_end_seconds=100.0,
            original_duration_seconds=100.0,
        )
