"""Clip placement on an authoritative SoundPlan timeline."""

from __future__ import annotations

from dataclasses import dataclass

from kinocut_sound.defaults import DEFAULT_GAP_TOLERANCE_SECONDS
from kinocut_sound.mix._errors import MIX_PLACEMENT_INVALID, mix_error
from kinocut_sound.timeline import Cue, CueKind, Timeline


@dataclass(frozen=True)
class PlacedClip:
    """One clip scheduled onto the timeline."""

    cue_id: str
    clip_id: str
    start_seconds: float
    duration_seconds: float
    source_ref: str
    stem_id: str


@dataclass(frozen=True)
class PlacementPlan:
    """Deterministic placement of clips and silence against a timeline."""

    timeline_duration_seconds: float
    placements: tuple[PlacedClip, ...]
    silence_cues: tuple[str, ...]


def place_clips(
    timeline: Timeline,
    *,
    clip_durations: dict[str, float],
    stem_for_cue: dict[str, str] | None = None,
    gap_tolerance_seconds: float = DEFAULT_GAP_TOLERANCE_SECONDS,
) -> PlacementPlan:
    """Place line/foley cues using timeline start/duration as authority.

    ``clip_durations`` maps cue_id -> rendered clip duration. A rendered clip
    shorter than the cue is zero-padded in the renderer; a longer clip is
    truncated. Missing durations for line/foley cues fail closed.
    """

    if not isinstance(timeline, Timeline):
        raise mix_error("timeline must be a Timeline", MIX_PLACEMENT_INVALID)
    stem_for_cue = stem_for_cue or {}
    placements: list[PlacedClip] = []
    silence: list[str] = []
    end = 0.0
    for cue in timeline.cues:
        if not isinstance(cue, Cue):
            raise mix_error("timeline cues must be Cue instances", MIX_PLACEMENT_INVALID)
        if cue.kind is CueKind.SILENCE:
            silence.append(cue.cue_id)
            end = max(end, cue.start_seconds + cue.duration_seconds)
            continue
        if cue.kind is CueKind.CHAPTER_MARKER:
            end = max(end, cue.start_seconds + cue.duration_seconds)
            continue
        if cue.cue_id not in clip_durations:
            raise mix_error(
                f"missing rendered duration for cue {cue.cue_id}",
                MIX_PLACEMENT_INVALID,
            )
        clip_dur = float(clip_durations[cue.cue_id])
        if clip_dur <= 0:
            raise mix_error("clip duration must be positive", MIX_PLACEMENT_INVALID)
        # Timeline duration is authoritative for placement window.
        window = float(cue.duration_seconds)
        if abs(clip_dur - window) > max(gap_tolerance_seconds, window):
            # Still place using timeline window; renderer pads/truncates.
            pass
        stem = stem_for_cue.get(cue.cue_id, _default_stem(cue.kind))
        placements.append(
            PlacedClip(
                cue_id=cue.cue_id,
                clip_id=cue.cue_id,
                start_seconds=float(cue.start_seconds),
                duration_seconds=window,
                source_ref=cue.source_ref,
                stem_id=stem,
            )
        )
        end = max(end, cue.start_seconds + window)
    auth = getattr(timeline, "authoritative_duration_seconds", None)
    if auth is not None:
        declared = float(auth)
        end = max(end, declared)
    return PlacementPlan(
        timeline_duration_seconds=end,
        placements=tuple(sorted(placements, key=lambda p: (p.start_seconds, p.cue_id))),
        silence_cues=tuple(silence),
    )


def _default_stem(kind: CueKind) -> str:
    if kind is CueKind.LINE:
        return "dialogue"
    if kind is CueKind.FOLEY:
        return "sfx"
    if kind is CueKind.BED:
        return "ambience"
    return "misc"
