"""Batch re-generation of lines/episodes referencing a profile.

When a :class:`VoiceProfile` is updated, every line that references it must
be re-rendered deterministically. This module walks episode plans, filters
to lines matching a ``profile_id``, and renders them through an S5
:class:`BatchPlanner`.
"""

from __future__ import annotations

from dataclasses import dataclass

from kinocut_sound.sound_plan import SoundPlan

from kinocut_sound.voice.batch import BatchPlanner, BatchResult, RenderedClip

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_METRIC_INVALID,
    CONSISTENCY_REGENERATION_FAILED,
    bounded_consistency_error,
)


@dataclass(frozen=True)
class RegenerationReport:
    """Result of re-generating all lines for a profile."""

    profile_id: str
    plan_hashes: tuple[str, ...]
    rendered_clips: tuple[RenderedClip, ...]
    warnings: tuple[str, ...]


def _filter_plans(
    episodes: tuple[SoundPlan, ...],
    profile_id: str,
) -> tuple[SoundPlan, ...]:
    """Return episodes reduced to lines that reference ``profile_id``."""

    result: list[SoundPlan] = []
    for episode in episodes:
        if not isinstance(episode, SoundPlan):
            raise bounded_consistency_error(
                "episodes must be SoundPlan instances",
                CONSISTENCY_METRIC_INVALID,
            )
        matching = tuple(
            line for line in episode.lines if line.profile.profile_id == profile_id
        )
        if matching:
            result.append(episode.model_copy(update={"lines": matching}))
    return tuple(result)


def _run_batch(
    *,
    planner: BatchPlanner,
    plan: SoundPlan,
    write_outputs: bool,
) -> BatchResult:
    """Render one plan through ``planner`` with bounded error handling."""

    try:
        return planner.render_plan(plan, write_outputs=write_outputs)
    except Exception as exc:
        raise bounded_consistency_error(
            f"regeneration batch failed: {exc}",
            CONSISTENCY_REGENERATION_FAILED,
        ) from exc


def _collect_clips(
    results: tuple[BatchResult, ...],
    profile_id: str,
) -> tuple[RenderedClip, ...]:
    """Return clips from matching plans (already profile-filtered)."""

    clips: list[RenderedClip] = []
    for result in results:
        for clip in result.clips:
            clips.append(clip)
    return tuple(clips)


def regenerate_for_profile(
    *,
    profile_id: str,
    episodes: tuple[SoundPlan, ...],
    planner: BatchPlanner,
    write_outputs: bool = True,
) -> RegenerationReport:
    """Re-render every line across ``episodes`` that references ``profile_id``."""

    if not isinstance(profile_id, str) or not profile_id:
        raise bounded_consistency_error(
            "profile_id must be a non-empty string",
            CONSISTENCY_METRIC_INVALID,
        )
    matching = _filter_plans(episodes, profile_id)
    results: list[BatchResult] = []
    warnings: list[str] = []
    for plan in matching:
        result = _run_batch(
            planner=planner,
            plan=plan,
            write_outputs=write_outputs,
        )
        results.append(result)
        if result.warnings:
            warnings.extend(result.warnings)
    clips = _collect_clips(tuple(results), profile_id)
    return RegenerationReport(
        profile_id=profile_id,
        plan_hashes=tuple(r.plan_hash for r in results),
        rendered_clips=clips,
        warnings=tuple(warnings),
    )
