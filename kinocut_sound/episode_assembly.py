"""Pure deterministic planning for sound episode assembly.

This module performs no I/O and imports no rendering or vendor runtime. It
turns a parsed-script record plus fake-or-real hashed clip/cue references into
an authoritative timeline and explicit routing plan.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from kinocut_sound._assembly_integrity import validate_episode_assembly
from kinocut_sound._canonical import (
    BoundedCode,
    FrozenModel,
    RecordBase,
    Sha256,
    canonical_record_id,
    location_violation,
)
from kinocut_sound._errors import SoundContractError
from kinocut_sound._input_bounds import bounded_model_iterable
from kinocut_sound._model_boundary import dump_revalidate_model
from kinocut_sound._timeline_identity import (
    bounded_pause_cue_id as _bounded_pause_cue_id,
)

from kinocut_sound.lines import ProfileRef
from kinocut_sound.limits import (
    MAX_ASSEMBLY_CLIPS,
    MAX_ASSEMBLY_FOLEY_INTENTS,
    MAX_ASSEMBLY_SILENCE_INTENTS,
    MAX_ASSEMBLY_TIMELINE_CUES,
    MIN_TIME_SECONDS,
)
from kinocut_sound.script_parser import (
    BeatKind,
    ChapterCard,
    ParsedBeat,
    ParsedEventKind,
    ParsedLine,
    ParsedScript,
    SilenceQuality,
)
from kinocut_sound.timeline import Cue, CueKind, Timeline


class AssemblyPlanningError(SoundContractError):
    """A bounded, privacy-safe episode planning failure."""


class ClipRef(FrozenModel):
    """A privacy-safe rendered-line artifact reference."""

    line_id: str = Field(min_length=1)
    artifact_hash: Sha256
    source_ref: str = Field(min_length=1)
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS, strict=True)

    @field_validator("line_id")
    @classmethod
    def _line_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("source_ref")
    @classmethod
    def _source_ref_is_safe(cls, value: str) -> str:
        reason = location_violation(value)
        if reason is not None:
            raise ValueError(f"source_ref {reason}")
        return value

    @field_validator("duration_seconds")
    @classmethod
    def _duration_is_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("duration_seconds must not be a boolean")
        return value


class FoleyCueIntent(FrozenModel):
    """A deterministic Foley cue spotted relative to a parsed line."""

    cue_id: str = Field(min_length=1)
    after_line_id: str = Field(min_length=1)
    asset_ref: str = Field(min_length=1)
    asset_hash: Sha256
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS, strict=True)

    @field_validator("cue_id", "after_line_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("asset_ref")
    @classmethod
    def _asset_ref_is_safe(cls, value: str) -> str:
        reason = location_violation(value)
        if reason is not None:
            raise ValueError(f"asset_ref {reason}")
        return value

    @field_validator("duration_seconds")
    @classmethod
    def _duration_is_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("duration_seconds must not be a boolean")
        return value


class DesignedSilenceIntent(FrozenModel):
    """One explicit designed-silence cue relative to a parsed line."""

    cue_id: str = Field(min_length=1)
    after_line_id: str = Field(min_length=1)
    quality: SilenceQuality
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS, strict=True)

    @field_validator("cue_id", "after_line_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("duration_seconds")
    @classmethod
    def _duration_is_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("duration_seconds must not be a boolean")
        return value


class AssemblyRoute(FrozenModel):
    """Resolved line routing intent in final script order."""

    line_id: str = Field(min_length=1)
    cue_id: str = Field(min_length=1)
    profile: ProfileRef
    spatial_preset: str = Field(min_length=1)

    @field_validator("line_id", "cue_id", "spatial_preset")
    @classmethod
    def _codes_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class EpisodeAssembly(RecordBase):
    """Canonical, privacy-safe output of pure episode assembly planning."""

    record_kind: Literal["episode_assembly"] = "episode_assembly"
    episode_id: str = Field(min_length=1)
    parsed_script_id: Sha256
    timeline: Timeline
    line_cue_order: tuple[str, ...]
    line_ids: tuple[str, ...]
    routes: tuple[AssemblyRoute, ...]
    clip_hashes: tuple[Sha256, ...]
    foley_hashes: tuple[Sha256, ...]
    foley_cue_ids: tuple[str, ...]
    chapter_cards: tuple[ChapterCard, ...]

    @field_validator("episode_id")
    @classmethod
    def _episode_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @model_validator(mode="after")
    def _assembly_is_self_consistent(self) -> EpisodeAssembly:
        validate_episode_assembly(self)
        return self

    def canonical_id(self) -> str:
        """Return the canonical semantic digest for receipt compatibility."""

        return canonical_record_id(self)


def _planning_error(message: str, code: str) -> AssemblyPlanningError:
    return AssemblyPlanningError(message, code=code, suggested_action={"auto_fix": False})


def _unique_index(
    values: tuple[ClipRef, ...],
) -> dict[str, ClipRef]:
    line_ids = tuple(value.line_id for value in values)
    if len(set(line_ids)) != len(line_ids):
        raise _planning_error("clip inputs contain a duplicate line id", "duplicate_clip")
    return {value.line_id: value for value in values}


def _validate_cue_contracts(
    parsed: ParsedScript,
    foley_cues: tuple[FoleyCueIntent, ...],
    designed_silences: tuple[DesignedSilenceIntent, ...],
) -> None:
    line_ids = {item.line.line_id for item in parsed.parsed_lines}
    intents = (*foley_cues, *designed_silences)
    cue_ids = tuple(intent.cue_id for intent in intents)
    if len(set(cue_ids)) != len(cue_ids):
        raise _planning_error("cue contracts contain a duplicate cue id", "invalid_cue_contract")
    if any(intent.after_line_id not in line_ids for intent in intents):
        raise _planning_error("cue contract references an unknown line id", "invalid_cue_contract")


CueIntent = FoleyCueIntent | DesignedSilenceIntent


def _group_by_line(values: tuple[CueIntent, ...]) -> dict[str, tuple[CueIntent, ...]]:
    grouped: dict[str, list[CueIntent]] = {}
    for value in values:
        line_id = value.after_line_id
        grouped.setdefault(line_id, []).append(value)
    return {line_id: tuple(sorted(items, key=lambda item: item.cue_id)) for line_id, items in grouped.items()}


def _append_cue(
    cues: list[Cue],
    *,
    cue_id: str,
    start_seconds: float,
    duration_seconds: float,
    kind: CueKind,
    source_ref: str,
) -> float:
    cues.append(
        Cue(
            cue_id=cue_id,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
            kind=kind,
            source_ref=source_ref,
        )
    )
    return start_seconds + duration_seconds


def _line_route(item: ParsedLine) -> AssemblyRoute:
    return AssemblyRoute(
        line_id=item.line.line_id,
        cue_id=item.cue_id,
        profile=item.line.profile,
        spatial_preset=item.line.spatial_preset,
    )


def _append_beat(beat: ParsedBeat, current: float, cues: list[Cue]) -> float:
    if beat.kind == BeatKind.FOLEY:
        if beat.asset_ref is None:
            raise _planning_error("Foley beat is missing its asset reference", "invalid_assembly")
        kind = CueKind.FOLEY
        source_ref = beat.asset_ref
    elif beat.kind == BeatKind.DESIGNED_SILENCE:
        if beat.silence_quality is None:
            raise _planning_error("silence beat is missing its quality", "invalid_assembly")
        kind = CueKind.SILENCE
        source_ref = f"silence/{beat.silence_quality.value}.json"
    else:
        kind = CueKind.SILENCE
        source_ref = "silence/pace.json"
    return _append_cue(
        cues,
        cue_id=beat.beat_id,
        start_seconds=current,
        duration_seconds=beat.duration_seconds,
        kind=kind,
        source_ref=source_ref,
    )


def _plan_line_extras(
    item: ParsedLine,
    current: float,
    cues: list[Cue],
    silences: tuple[DesignedSilenceIntent, ...],
    foley: tuple[FoleyCueIntent, ...],
) -> float:
    if item.pause_after_seconds > MIN_TIME_SECONDS:
        current = _append_cue(
            cues,
            cue_id=_bounded_pause_cue_id("line", item.line.line_id),
            start_seconds=current,
            duration_seconds=item.pause_after_seconds,
            kind=CueKind.SILENCE,
            source_ref="silence/line_pause.json",
        )
    for intent in silences:
        current = _append_cue(
            cues,
            cue_id=intent.cue_id,
            start_seconds=current,
            duration_seconds=intent.duration_seconds,
            kind=CueKind.SILENCE,
            source_ref=f"silence/{intent.quality.value}.json",
        )
    for intent in foley:
        current = _append_cue(
            cues,
            cue_id=intent.cue_id,
            start_seconds=current,
            duration_seconds=intent.duration_seconds,
            kind=CueKind.FOLEY,
            source_ref=intent.asset_ref,
        )
    return current


def _build_timeline(
    parsed: ParsedScript,
    clips: dict[str, ClipRef],
    foley_by_line: dict[str, tuple[CueIntent, ...]],
    silence_by_line: dict[str, tuple[CueIntent, ...]],
) -> tuple[Timeline, tuple[AssemblyRoute, ...]]:
    parsed_by_id = {item.line.line_id: item for item in parsed.parsed_lines}
    beat_by_id = {beat.beat_id: beat for beat in parsed.beats}
    event_by_id = {event.event_id: event for event in parsed.events}
    cues: list[Cue] = []
    routes: list[AssemblyRoute] = []
    current = MIN_TIME_SECONDS
    for scene in parsed.scenes:
        for event_id in scene.event_ids:
            event = event_by_id[event_id]
            if event.kind == ParsedEventKind.CHAPTER_CARD:
                continue
            if event.kind == ParsedEventKind.BEAT:
                current = _append_beat(beat_by_id[event_id], current, cues)
                continue
            item = parsed_by_id[event_id]
            clip = clips[event_id]
            current = _append_cue(
                cues,
                cue_id=item.cue_id,
                start_seconds=current,
                duration_seconds=clip.duration_seconds,
                kind=CueKind.LINE,
                source_ref=clip.source_ref,
            )
            routes.append(_line_route(item))
            current = _plan_line_extras(
                item,
                current,
                cues,
                silence_by_line.get(event_id, ()),
                foley_by_line.get(event_id, ()),
            )
        if scene.pause_after_seconds > MIN_TIME_SECONDS:
            current = _append_cue(
                cues,
                cue_id=_bounded_pause_cue_id("scene", scene.scene_id),
                start_seconds=current,
                duration_seconds=scene.pause_after_seconds,
                kind=CueKind.SILENCE,
                source_ref="silence/scene_pause.json",
            )
    return (
        Timeline(cues=tuple(cues), require_at_least_one_cue=bool(cues)),
        tuple(routes),
    )


def plan_episode_assembly(
    parsed: ParsedScript,
    *,
    clips: Iterable[ClipRef],
    foley_cues: Iterable[FoleyCueIntent] = (),
    designed_silences: Iterable[DesignedSilenceIntent] = (),
    created_by: str,
    cancellation_requested: bool,
) -> EpisodeAssembly:
    """Return an all-or-nothing deterministic episode assembly plan."""
    if not isinstance(cancellation_requested, bool):
        raise _planning_error("cancellation flag must be a boolean", "invalid_assembly")

    if cancellation_requested:
        raise _planning_error("episode assembly planning was cancelled", "assembly_cancelled")
    try:
        parsed = dump_revalidate_model(parsed, ParsedScript)
        clips = bounded_model_iterable(clips, ClipRef, MAX_ASSEMBLY_CLIPS)
        foley_cues = bounded_model_iterable(foley_cues, FoleyCueIntent, MAX_ASSEMBLY_FOLEY_INTENTS)
        designed_silences = bounded_model_iterable(
            designed_silences, DesignedSilenceIntent, MAX_ASSEMBLY_SILENCE_INTENTS
        )
        _validate_projected_cue_count(parsed, foley_cues, designed_silences)
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise _planning_error("assembly inputs failed strict boundary validation", "invalid_assembly") from None
    clip_index = _unique_index(clips)
    expected_line_ids = tuple(item.line.line_id for item in parsed.parsed_lines)
    if set(clip_index) != set(expected_line_ids):
        raise _planning_error("clip inputs do not exactly match parsed lines", "clip_set_mismatch")
    _validate_cue_contracts(parsed, foley_cues, designed_silences)
    foley_by_line = _group_by_line(foley_cues)
    silence_by_line = _group_by_line(designed_silences)
    try:
        timeline, routes = _build_timeline(parsed, clip_index, foley_by_line, silence_by_line)
        foley_hash_by_id = {
            beat.beat_id: beat.asset_hash
            for beat in parsed.beats
            if beat.kind == BeatKind.FOLEY and beat.asset_hash is not None
        }
        foley_hash_by_id.update({cue.cue_id: cue.asset_hash for cue in foley_cues})
        foley_cue_ids = tuple(cue.cue_id for cue in timeline.cues if cue.kind == CueKind.FOLEY)
        parsed_id = parsed.canonical_id()
        return EpisodeAssembly(
            project_id=parsed.project_id,
            created_by=created_by,
            source_record_ids=(parsed_id,),
            episode_id=parsed.episode_id,
            parsed_script_id=parsed_id,
            timeline=timeline,
            line_cue_order=parsed.cue_order,
            line_ids=expected_line_ids,
            routes=routes,
            clip_hashes=tuple(clip_index[line_id].artifact_hash for line_id in expected_line_ids),
            foley_hashes=tuple(foley_hash_by_id[cue_id] for cue_id in foley_cue_ids),
            foley_cue_ids=foley_cue_ids,
            chapter_cards=parsed.chapter_cards,
        )
    except (ValidationError, KeyError):
        raise _planning_error("episode timeline failed canonical validation", "invalid_assembly") from None


def _validate_projected_cue_count(
    parsed: ParsedScript,
    foley_cues: tuple[FoleyCueIntent, ...],
    designed_silences: tuple[DesignedSilenceIntent, ...],
) -> None:
    projected = (
        len(parsed.parsed_lines)
        + len(parsed.beats)
        + sum(item.pause_after_seconds > MIN_TIME_SECONDS for item in parsed.parsed_lines)
        + sum(scene.pause_after_seconds > MIN_TIME_SECONDS for scene in parsed.scenes)
        + len(foley_cues)
        + len(designed_silences)
    )
    if projected > MAX_ASSEMBLY_TIMELINE_CUES:
        raise ValueError("projected timeline exceeds the cue ceiling")
