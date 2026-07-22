"""Reusable platform-aware clipping helpers for the shorts orchestrator.

The orchestrator feeds candidate moments (start/end time ranges) into this
module and receives a deterministic, strict-model plan that:

* clips each moment to the platform's hard maximum duration (YouTube Shorts =
  180 s, Instagram Reels = 90 s);
* preserves the original complete-thought time range whenever the source
  moment already fits inside the platform maximum;
* falls back to a safe static composition (a single neutral centre crop
  covering the whole trimmed range) whenever the moment cannot be lowered or
  the platform budget cannot honour the original range — never silently crops
  the subject out and never raises when a safe fallback is possible;
* returns a deterministic, JSON-stable plan suitable for the orchestrator
  pipeline.

The module is planning-only: it never invokes FFmpeg, never mutates state, and
only depends on ``kinocut.contracts._common`` for the immutable strict-model
base. All operations are pure functions of their inputs.

Platform budget table — the authoritative values used by the orchestrator and
declared here so the orchestrator never has to re-derive them:

* ``youtube_shorts`` — 180 seconds (3 minutes)
* ``instagram_reels`` — 90 seconds (1 minute 30 seconds)
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Literal, get_args

from pydantic import ConfigDict, Field, model_validator

from kinocut.contracts._common import ValueObject


# --- platform enumeration ----------------------------------------------------


Platform = Literal["youtube_shorts", "instagram_reels"]

#: Tuple form for membership checks; mirrors :data:`Platform`.
PLATFORMS: tuple[str, ...] = get_args(Platform)


#: Frozen platform → maximum duration (seconds). Used as the hard budget by
#: :func:`clip_moment` and emitted verbatim in :class:`ClipPlan` so downstream
#: review tooling can verify the orchestrator applied the right cap without
#: re-deriving it.
PLATFORM_MAX_DURATIONS: Mapping[str, float] = MappingProxyType(
    {
        "youtube_shorts": 180.0,
        "instagram_reels": 90.0,
    }
)


#: Minimal viable clip duration (seconds). Moments shorter than this are
#: rejected so the orchestrator never plans a clip the platform will refuse.
MIN_CLIP_DURATION_SECONDS: float = 1.0


# --- error vocabulary --------------------------------------------------------


CLIP_DURATION_EXCEEDS_PLATFORM = "clip_duration_exceeds_platform_maximum"
CLIP_DURATION_BELOW_MINIMUM = "clip_duration_below_minimum"
CLIP_INVALID_TIME_RANGE = "clip_invalid_time_range"
CLIP_UNKNOWN_PLATFORM = "clip_unknown_platform"


def _clip_error(message: str, code: str) -> ValueError:
    """Surface a fail-closed planning error (no engine side-effects to wrap)."""

    return ValueError(f"{code}: {message}")


# --- strict value objects ----------------------------------------------------


class _StrictModel(ValueObject):
    """Local alias to keep the file self-documenting.

    Inherits :class:`ValueObject` so it is immutable, forbids extra fields, and
    rejects non-finite floats — the exact contract used elsewhere in the
    project for inline planning values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ClippedMoment(_StrictModel):
    """A moment clipped to a platform's maximum duration.

    ``original_start_seconds``/``original_end_seconds`` carry the source range
    unchanged so the orchestrator and human reviewer can prove the lower did
    not silently drop content. ``start_seconds``/``end_seconds`` are the
    effective (clipped) range; when the original was within budget, the two
    pairs are equal and ``was_clipped`` is ``False``.
    """

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
        """Reject degenerate / inverted ranges; recompute duration deterministically."""

        if self.end_seconds <= self.start_seconds:
            raise ValueError(f"end_seconds must exceed start_seconds; got {self.start_seconds}->{self.end_seconds}")
        if self.original_end_seconds <= self.original_start_seconds:
            raise ValueError("original_end_seconds must exceed original_start_seconds")
        expected = self.end_seconds - self.start_seconds
        if math.isfinite(expected) and abs(expected - self.duration_seconds) > 1e-9:
            raise ValueError("duration_seconds must equal end_seconds - start_seconds")
        return self


class ClipPlan(_StrictModel):
    """Deterministic, JSON-stable plan for the shorts orchestrator.

    ``clipped_moments`` carries every accepted moment in input order (preserved
    so a hand-written comparison fixture can be byte-stable), and
    ``review_warnings`` collects every PARTIAL flag for the human reviewer
    surface. ``plan_id`` is a content-derived sha256 so two logically-equal
    plans collapse to the same id and cache writes are stable.
    """

    plan_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    platform: Platform
    platform_max_duration_seconds: float = Field(gt=0.0)
    clipped_moments: tuple[ClippedMoment, ...] = ()
    rejected_moments: tuple[str, ...] = ()
    review_warnings: tuple[str, ...] = ()
    static_composition: bool = False

    @model_validator(mode="after")
    def _at_most_one_static_composition(self) -> ClipPlan:
        if self.static_composition and len(self.clipped_moments) != 1:
            raise ValueError("static_composition plans must contain exactly one clipped moment")
        return self


class StaticCompositionRequest(_StrictModel):
    """Inputs to the safe static composition fallback.

    Carried as a strict value object so the orchestrator can serialize the
    request and review it before any lower fires. The fallback never depends on
    a tracker or workflow op — it just centres the trimmed range, which is
    the behaviour the platform will accept even when the subject is not
    available (the review warning is the explicit signal that the subject was
    dropped).
    """

    moment_id: str = Field(min_length=1)
    platform: Platform
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_range(self) -> StaticCompositionRequest:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must exceed start_seconds")
        return self


# --- helpers -----------------------------------------------------------------


def platform_max_duration(platform: str) -> float:
    """Return the canonical max duration for ``platform``.

    Raises :class:`ValueError` (with the ``CLIP_UNKNOWN_PLATFORM`` code prefix)
    on any unknown platform so the orchestrator never silently applies the
    wrong cap.
    """

    if platform not in PLATFORM_MAX_DURATIONS:
        raise _clip_error(
            f"unknown platform {platform!r}; expected one of {list(PLATFORM_MAX_DURATIONS)}",
            CLIP_UNKNOWN_PLATFORM,
        )
    return PLATFORM_MAX_DURATIONS[platform]


def _resolve_id(moment: Mapping[str, Any] | Any) -> str | None:
    """Return the moment id from either ``moment_id`` or ``candidate_id``."""

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
    """Pull (start, end, id) out of any moment mapping, in a fail-closed way.

    Accepts moments keyed by either ``moment_id`` (the orchestrator-side
    alias) or ``candidate_id`` (the strict ``kinocut.product.models.
    CandidateMoment`` field name) so the same helper serves both surfaces.
    """

    moment_id = _resolve_id(moment)
    if not moment_id:
        raise _clip_error("moment mapping requires a non-empty 'moment_id' or 'candidate_id'", CLIP_INVALID_TIME_RANGE)
    if isinstance(moment, Mapping):
        start = moment.get("start")
        end = moment.get("end")
    else:
        start = getattr(moment, "start", None)
        end = getattr(moment, "end", None)
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise _clip_error(f"moment {moment_id!r} requires numeric 'start' and 'end' fields", CLIP_INVALID_TIME_RANGE)
    if math.isnan(float(start)) or math.isinf(float(start)) or math.isnan(float(end)) or math.isinf(float(end)):
        raise _clip_error(f"moment {moment_id!r} has non-finite start/end", CLIP_INVALID_TIME_RANGE)
    start_f = float(start)
    end_f = float(end)
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
    """Clip one moment to ``platform``'s max duration.

    Behaviour:

    * If the moment fits in the platform budget, the original range is
      returned unchanged and ``was_clipped`` is ``False`` — complete-thought
      preservation.
    * If the moment exceeds the budget, the range is truncated to ``[start,
      start + platform_max]`` and ``was_clipped`` is ``True``. The original
      range is preserved on the model so the reviewer can audit what was
      dropped.
    * If ``allow_safe_fallback`` is True (the default) and the moment is below
      ``MIN_CLIP_DURATION_SECONDS``, the moment is returned with
      ``review_warning`` set rather than rejected — the orchestrator can still
      render a short preview and the human reviewer is informed.
    * A moment below the minimum with ``allow_safe_fallback=False`` raises
      :class:`ValueError` (``CLIP_DURATION_BELOW_MINIMUM``).

    The function never silently drops content: ``original_start_seconds`` /
    ``original_end_seconds`` always equal the input.
    """

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
    if original_duration < MIN_CLIP_DURATION_SECONDS:
        if not allow_safe_fallback:
            raise _clip_error(
                f"moment {moment_id!r} duration {original_duration:.3f}s below "
                f"minimum {MIN_CLIP_DURATION_SECONDS:.3f}s",
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
                f"minimum {MIN_CLIP_DURATION_SECONDS:.3f}s; safe preview fallback applied"
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


def clip_moments(
    moments: Iterable[Mapping[str, Any] | Any],
    *,
    platform: str,
) -> ClipPlan:
    """Build a deterministic :class:`ClipPlan` for every moment in ``moments``.

    ``moments`` is iterated exactly once and the resulting
    ``clipped_moments`` tuple preserves the input order. Moments that raise
    during validation are captured in ``rejected_moments`` (their ids) and the
    plan still builds, so one malformed input never aborts the orchestrator.
    """

    max_duration = platform_max_duration(platform)
    clipped: list[ClippedMoment] = []
    rejected: list[str] = []
    warnings: list[str] = []
    for moment in moments:
        try:
            clipped_moment = clip_moment(moment, platform=platform)
        except ValueError as exc:
            moment_id = _resolve_id(moment)
            if moment_id is not None:
                rejected.append(moment_id)
            warnings.append(f"rejected moment: {exc}")
            continue
        clipped.append(clipped_moment)
        if clipped_moment.review_warning is not None:
            warnings.append(clipped_moment.review_warning)
    return ClipPlan(
        plan_id=_compute_plan_id(platform, max_duration, clipped),
        platform=platform,  # type: ignore[arg-type]
        platform_max_duration_seconds=max_duration,
        clipped_moments=tuple(clipped),
        rejected_moments=tuple(rejected),
        review_warnings=tuple(warnings),
    )


def plan_safe_static_composition(
    request: StaticCompositionRequest | Mapping[str, Any] | Any,
) -> ClipPlan:
    """Build the single-moment safe static composition fallback.

    Called when the reframe lowerer abstains or the orchestrator cannot trust
    the moment: emits exactly one :class:`ClippedMoment` with the request's
    range preserved verbatim and a deterministic ``static_composition=True``
    flag the orchestrator can surface to the reviewer. The human-review
    warning is explicit (``review_warnings``), never silent.

    Accepts either a strict :class:`StaticCompositionRequest` or any mapping
    that exposes ``moment_id``, ``platform``, ``start_seconds``,
    ``end_seconds``, and ``reason``.
    """

    parsed = _coerce_static_request(request)
    max_duration = platform_max_duration(parsed.platform)
    if parsed.end_seconds - parsed.start_seconds > max_duration:
        raise _clip_error(
            f"static composition range {parsed.end_seconds - parsed.start_seconds:.3f}s "
            f"exceeds {parsed.platform} max {max_duration:.3f}s",
            CLIP_DURATION_EXCEEDS_PLATFORM,
        )
    moment = ClippedMoment(
        moment_id=parsed.moment_id,
        platform=parsed.platform,
        start_seconds=parsed.start_seconds,
        end_seconds=parsed.end_seconds,
        duration_seconds=parsed.end_seconds - parsed.start_seconds,
        original_start_seconds=parsed.start_seconds,
        original_end_seconds=parsed.end_seconds,
        original_duration_seconds=parsed.end_seconds - parsed.start_seconds,
        was_clipped=False,
        review_warning=f"PARTIAL: static composition fallback applied ({parsed.reason})",
    )
    return ClipPlan(
        plan_id=_compute_plan_id(parsed.platform, max_duration, [moment]),
        platform=parsed.platform,
        platform_max_duration_seconds=max_duration,
        clipped_moments=(moment,),
        rejected_moments=(),
        review_warnings=(f"PARTIAL: {parsed.reason}",),
        static_composition=True,
    )


# --- internal helpers --------------------------------------------------------


def _coerce_static_request(
    request: StaticCompositionRequest | Mapping[str, Any] | Any,
) -> StaticCompositionRequest:
    """Normalize loose dict/object inputs into a strict StaticCompositionRequest."""

    if isinstance(request, StaticCompositionRequest):
        return request
    if isinstance(request, Mapping):
        return StaticCompositionRequest.model_validate(request)
    for attr in ("moment_id", "platform", "start_seconds", "end_seconds", "reason"):
        if not hasattr(request, attr):
            raise _clip_error(
                f"static composition request missing {attr!r}; provide StaticCompositionRequest or mapping",
                CLIP_INVALID_TIME_RANGE,
            )
    return StaticCompositionRequest(
        moment_id=request.moment_id,
        platform=request.platform,
        start_seconds=request.start_seconds,
        end_seconds=request.end_seconds,
        reason=request.reason,
    )


def _compute_plan_id(platform: str, max_duration: float, clipped: Iterable[ClippedMoment]) -> str:
    """Deterministic content-derived id for a :class:`ClipPlan`.

    The id is a stable ``sha256:<hex>`` over the canonical serialized plan
    payload — the same contract :mod:`kinocut.contracts._common` uses for
    records. Equal inputs always collapse to the same id so cache writes and
    orchestrator reconciliation are byte-stable.
    """

    payload = {
        "platform": platform,
        "platform_max_duration_seconds": max_duration,
        "clipped_moments": [moment.model_dump(mode="json") for moment in clipped],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = sorted(
    [
        "CLIP_DURATION_BELOW_MINIMUM",
        "CLIP_DURATION_EXCEEDS_PLATFORM",
        "CLIP_INVALID_TIME_RANGE",
        "CLIP_UNKNOWN_PLATFORM",
        "ClipPlan",
        "ClippedMoment",
        "MIN_CLIP_DURATION_SECONDS",
        "PLATFORM_MAX_DURATIONS",
        "PLATFORMS",
        "Platform",
        "StaticCompositionRequest",
        "clip_moment",
        "clip_moments",
        "plan_safe_static_composition",
        "platform_max_duration",
    ]
)
