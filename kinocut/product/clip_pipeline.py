"""Platform-aware clipping helpers for the shorts orchestrator."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, get_args

from pydantic import ConfigDict, Field, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.limits import (
    INSTAGRAM_REELS_MAX_DURATION_SECONDS,
    MIN_SHORTS_PREVIEW_DURATION_SECONDS,
    YOUTUBE_SHORTS_MAX_DURATION_SECONDS,
)


Platform = Literal["youtube_shorts", "instagram_reels"]

PLATFORMS: tuple[str, ...] = get_args(Platform)


PLATFORM_MAX_DURATIONS: Mapping[str, float] = MappingProxyType(
    {
        "youtube_shorts": YOUTUBE_SHORTS_MAX_DURATION_SECONDS,
        "instagram_reels": INSTAGRAM_REELS_MAX_DURATION_SECONDS,
    }
)


CLIP_INVALID_TIME_RANGE = "clip_invalid_time_range"
CLIP_DURATION_BELOW_MINIMUM = "clip_duration_below_minimum"
CLIP_UNKNOWN_PLATFORM = "clip_unknown_platform"


def _clip_error(message: str, code: str) -> ValueError:
    return ValueError(f"{code}: {message}")


class _StrictModel(ValueObject):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ClippedMoment(_StrictModel):
    """A platform-bounded moment retaining its original source range."""

    moment_id: str = Field(min_length=1)
    platform: Platform
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0)
    original_start_seconds: float = Field(ge=0.0)
    original_end_seconds: float = Field(ge=0.0)
    original_duration_seconds: float = Field(ge=0.0)
    was_clipped: bool = False
    review_warning: str | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> ClippedMoment:
        if self.end_seconds <= self.start_seconds:
            raise ValueError(f"end_seconds must exceed start_seconds; got {self.start_seconds}->{self.end_seconds}")
        if self.original_end_seconds <= self.original_start_seconds:
            raise ValueError("original_end_seconds must exceed original_start_seconds")
        expected = self.end_seconds - self.start_seconds
        if math.isfinite(expected) and abs(expected - self.duration_seconds) > 1e-9:
            raise ValueError("duration_seconds must equal end_seconds - start_seconds")
        if self.duration_seconds > PLATFORM_MAX_DURATIONS[self.platform] + 1e-9:
            raise ValueError("duration_seconds exceeds the platform maximum")
        return self


def platform_max_duration(platform: str) -> float:
    """Return the canonical maximum duration or reject an unknown platform."""
    if platform not in PLATFORM_MAX_DURATIONS:
        raise _clip_error(
            f"unknown platform {platform!r}; expected one of {list(PLATFORM_MAX_DURATIONS)}",
            CLIP_UNKNOWN_PLATFORM,
        )
    return PLATFORM_MAX_DURATIONS[platform]


def _resolve_id(moment: Mapping[str, Any] | Any) -> str | None:
    if isinstance(moment, Mapping):
        for key in ("moment_id", "candidate_id"):
            value = moment.get(key)
            if isinstance(value, str) and value:
                return value
        return None
    for attr in ("moment_id", "candidate_id"):
        value = getattr(moment, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def _validate_moment(moment: Mapping[str, Any] | Any) -> tuple[float, float, str]:
    moment_id = _resolve_id(moment)
    if not moment_id:
        raise _clip_error("moment mapping requires a non-empty 'moment_id' or 'candidate_id'", CLIP_INVALID_TIME_RANGE)
    if isinstance(moment, Mapping):
        start = moment.get("start")
        end = moment.get("end")
    else:
        start = getattr(moment, "start", None)
        end = getattr(moment, "end", None)
    if (
        not isinstance(start, (int, float))
        or isinstance(start, bool)
        or not isinstance(end, (int, float))
        or isinstance(end, bool)
    ):
        raise _clip_error(f"moment {moment_id!r} requires numeric 'start' and 'end' fields", CLIP_INVALID_TIME_RANGE)
    if math.isnan(float(start)) or math.isinf(float(start)) or math.isnan(float(end)) or math.isinf(float(end)):
        raise _clip_error(f"moment {moment_id!r} has non-finite start/end", CLIP_INVALID_TIME_RANGE)
    start_f = float(start)
    end_f = float(end)
    if start_f < 0.0:
        raise _clip_error(
            f"moment {moment_id!r} start must be non-negative",
            CLIP_INVALID_TIME_RANGE,
        )
    if end_f <= start_f:
        raise _clip_error(
            f"moment {moment_id!r} requires end > start (got {start_f} -> {end_f})",
            CLIP_INVALID_TIME_RANGE,
        )
    return start_f, end_f, moment_id


def clip_moment(
    moment: Mapping[str, Any] | Any,
    *,
    platform: str,
    allow_safe_fallback: bool = True,
) -> ClippedMoment:
    """Clip a moment to the platform cap while retaining its original bounds."""

    max_duration = platform_max_duration(platform)
    start, end, moment_id = _validate_moment(moment)
    original_duration = end - start
    if original_duration > max_duration:
        clipped_end = start + max_duration
        return ClippedMoment(
            moment_id=moment_id,
            platform=platform,  # type: ignore[arg-type]
            start_seconds=start,
            end_seconds=clipped_end,
            duration_seconds=clipped_end - start,
            original_start_seconds=start,
            original_end_seconds=end,
            original_duration_seconds=original_duration,
            was_clipped=True,
            review_warning=(
                f"moment {moment_id!r} duration {original_duration:.3f}s exceeded "
                f"{platform} max {max_duration:.3f}s; clipped to {clipped_end - start:.3f}s"
            ),
        )
    if original_duration < MIN_SHORTS_PREVIEW_DURATION_SECONDS:
        if not allow_safe_fallback:
            raise _clip_error(
                f"moment {moment_id!r} duration {original_duration:.3f}s below "
                f"minimum {MIN_SHORTS_PREVIEW_DURATION_SECONDS:.3f}s",
                CLIP_DURATION_BELOW_MINIMUM,
            )
        return ClippedMoment(
            moment_id=moment_id,
            platform=platform,  # type: ignore[arg-type]
            start_seconds=start,
            end_seconds=end,
            duration_seconds=original_duration,
            original_start_seconds=start,
            original_end_seconds=end,
            original_duration_seconds=original_duration,
            was_clipped=False,
            review_warning=(
                f"moment {moment_id!r} duration {original_duration:.3f}s below "
                f"minimum {MIN_SHORTS_PREVIEW_DURATION_SECONDS:.3f}s; short preview fallback applied"
            ),
        )
    return ClippedMoment(
        moment_id=moment_id,
        platform=platform,  # type: ignore[arg-type]
        start_seconds=start,
        end_seconds=end,
        duration_seconds=original_duration,
        original_start_seconds=start,
        original_end_seconds=end,
        original_duration_seconds=original_duration,
        was_clipped=False,
    )


__all__ = sorted(
    [
        "CLIP_DURATION_BELOW_MINIMUM",
        "CLIP_INVALID_TIME_RANGE",
        "CLIP_UNKNOWN_PLATFORM",
        "ClippedMoment",
        "PLATFORM_MAX_DURATIONS",
        "PLATFORMS",
        "Platform",
        "clip_moment",
        "platform_max_duration",
    ]
)
