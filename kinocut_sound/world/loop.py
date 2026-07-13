"""Seamless ambient loop generator with loop-seam and scene crossfades.

W4.3: ambient beds must loop seamlessly for 10-20 minute episodes, and scene
crossfades must smooth transitions between locations. The S9 mix leaf renders
the actual PCM crossfade. This module owns the deterministic *plan*: given a
source asset duration, a target output duration, and a crossfade length, it
computes the number of repeats required, the effective output duration, and
the ordered seam timestamps where S9 must apply a crossfade.

Everything here is pure and deterministic: identical inputs yield identical
seam reports and output hashes, which is required for cache stability and for
the render-fingerprint cache key (S3).

Design references (sonic-world design):
* W4.3 — seamless looping + scene crossfading.
* G04 — placement, fades, loops.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound.limits import MIN_TIME_SECONDS
from kinocut_sound.world._errors import world_error

# A loop step must add a strictly positive amount of new audio. The crossfade
# may not consume the whole source (otherwise the effective step is zero).
_MAX_REPEATS = 10_000


class SeamlessLoop(FrozenModel):
    """Declared loop plan: source duration, target duration, crossfade length.

    The crossfade overlaps the tail of one source copy with the head of the
    next. The effective per-repeat step is ``source_duration_seconds -
    crossfade_seconds``; this must be strictly positive so a loop actually
    advances. The target duration is the minimum required output length.
    """

    source_duration_seconds: float = Field(gt=MIN_TIME_SECONDS)
    target_duration_seconds: float = Field(gt=MIN_TIME_SECONDS)
    crossfade_seconds: float = Field(gt=MIN_TIME_SECONDS)
    loop_label: str = Field(min_length=1)

    @field_validator("loop_label")
    @classmethod
    def _label_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator(
        "source_duration_seconds",
        "target_duration_seconds",
        "crossfade_seconds",
    )
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("loop numeric must not be a boolean")
        return value

    @property
    def step_seconds(self) -> float:
        """The effective new audio added per repeat (must be positive)."""

        return self.source_duration_seconds - self.crossfade_seconds


@dataclass(frozen=True)
class SeamReport:
    """One seam where S9 must apply a crossfade."""

    index: int
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class LoopResult:
    """Deterministic result of a seamless-loop plan."""

    loop_label: str
    repeats: int
    effective_duration_seconds: float
    seams: tuple[SeamReport, ...]

    def digest(self) -> Sha256:
        """Return ``sha256:<hex>`` over the deterministic loop-result payload."""

        payload = {
            "loop_label": self.loop_label,
            "repeats": self.repeats,
            "effective_duration_seconds": self.effective_duration_seconds,
            "seams": [
                {
                    "index": seam.index,
                    "start_seconds": seam.start_seconds,
                    "end_seconds": seam.end_seconds,
                }
                for seam in self.seams
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SceneCrossfade:
    """Declared crossfade between two scene/location beds (S9 applies)."""

    from_bed_id: str
    to_bed_id: str
    crossfade_seconds: float
    start_seconds: float


def generate_loop(plan: SeamlessLoop) -> LoopResult:
    """Compute the deterministic repeat count, effective duration, and seams.

    The generator chooses the smallest number of source repeats whose effective
    duration meets or exceeds the target. When one copy already covers the
    target, no seams are produced and the effective duration equals the source
    duration (the S9 mix still trims to the target). Otherwise seams are
    emitted at each repeat boundary.
    """

    step = plan.step_seconds
    if step <= MIN_TIME_SECONDS:
        raise world_error(
            "crossfade must be shorter than the source duration",
            "loop_invalid",
        )
    if plan.target_duration_seconds <= plan.source_duration_seconds:
        # Source alone covers the target; no loop seam required.
        return LoopResult(
            loop_label=plan.loop_label,
            repeats=1,
            effective_duration_seconds=plan.source_duration_seconds,
            seams=(),
        )
    # repeats: smallest N such that source + (N-1)*step >= target.
    deficit = plan.target_duration_seconds - plan.source_duration_seconds
    extra = 0
    while extra * step < deficit:
        extra += 1
        if extra > _MAX_REPEATS:
            raise world_error(
                "loop target exceeds the maximum repeat ceiling",
                "loop_invalid",
            )
    repeats = extra + 1
    seams: list[SeamReport] = []
    for index in range(1, repeats):
        seam_start = index * step
        seam_end = seam_start + plan.crossfade_seconds
        seams.append(SeamReport(index=index, start_seconds=seam_start, end_seconds=seam_end))
    effective = plan.source_duration_seconds + extra * step
    return LoopResult(
        loop_label=plan.loop_label,
        repeats=repeats,
        effective_duration_seconds=effective,
        seams=tuple(seams),
    )


def scene_crossfade(
    *,
    from_bed_id: str,
    to_bed_id: str,
    crossfade_seconds: float,
    start_seconds: float,
) -> SceneCrossfade:
    """Build a declared scene crossfade for S9 (deterministic, no PCM)."""

    BoundedCode(from_bed_id)
    BoundedCode(to_bed_id)
    if from_bed_id == to_bed_id:
        raise world_error(
            "scene crossfade beds must differ",
            "loop_invalid",
        )
    if crossfade_seconds <= MIN_TIME_SECONDS or start_seconds < MIN_TIME_SECONDS:
        raise world_error(
            "scene crossfade timings must be strictly positive",
            "loop_invalid",
        )
    if isinstance(crossfade_seconds, bool) or isinstance(start_seconds, bool):
        raise world_error(
            "scene crossfade timings must not be booleans",
            "loop_invalid",
        )
    return SceneCrossfade(
        from_bed_id=from_bed_id,
        to_bed_id=to_bed_id,
        crossfade_seconds=crossfade_seconds,
        start_seconds=start_seconds,
    )
