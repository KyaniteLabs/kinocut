"""Standalone, deterministic script parsing for sound episode planning.

Only hashes and bounded routing metadata leave this module. Raw script text is
validated and hashed in-memory, then discarded before the typed record is
returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from kinocut_sound._canonical import (
    BoundedCode,
    FrozenModel,
    RecordBase,
    Sha256,
    canonical_digest,
    canonical_record_id,
    location_violation,
)
from kinocut_sound._errors import SoundContractError
from kinocut_sound._input_bounds import validate_wf_name, validate_wf_routes
from kinocut_sound._model_boundary import dump_revalidate_index
from kinocut_sound._script_integrity import (
    validate_script_relationships,
    validate_target_id_uniqueness,
)
from kinocut_sound._script_resource_limits import SCRIPT_LIMITS, script_limit_violation
from kinocut_sound.lines import Emotion, Line, ProfileRef, Prosody
from kinocut_sound.limits import MIN_TEXT_LENGTH_CHARS, MIN_TIME_SECONDS, MIN_VERSION


class ScriptParseError(SoundContractError):
    """A bounded, privacy-safe script parsing failure."""


class ScriptLineKind(StrEnum):
    """Closed routing intents for spoken screenplay lines."""

    DIALOGUE = "dialogue"
    CONFESSIONAL = "confessional"
    OFF_SCREEN = "off_screen"
    NARRATION = "narration"
    ACTION = "action"
    VOICEOVER = "voiceover"


class BeatKind(StrEnum):
    """Closed set of non-spoken screenplay beats."""

    PACE = "pace"
    FOLEY = "foley"
    DESIGNED_SILENCE = "designed_silence"


class SilenceQuality(StrEnum):
    """Closed qualities for designed-silence beats."""

    DEAD = "dead"
    ROOM_TONE = "room_tone"
    HELD_BREATH = "held_breath"


class ParsedEventKind(StrEnum):
    """Closed event kinds retained in source order."""

    LINE = "line"
    CHAPTER_CARD = "chapter_card"
    BEAT = "beat"


class ActorRoute(FrozenModel):
    """A fully resolved actor-to-voice and spatial route."""

    actor_id: str = Field(min_length=1)
    profile: ProfileRef
    dialogue_spatial_preset: str = Field(min_length=1)
    confessional_spatial_preset: str = Field(min_length=1)
    off_screen_spatial_preset: str = Field(min_length=1)
    narration_spatial_preset: str = Field(min_length=1)
    prosody: Prosody
    emotion: Emotion
    inherit_loudness: bool = Field(strict=True)

    @field_validator(
        "actor_id",
        "dialogue_spatial_preset",
        "confessional_spatial_preset",
        "off_screen_spatial_preset",
        "narration_spatial_preset",
    )
    @classmethod
    def _codes_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class ParsedLine(FrozenModel):
    """One privacy-safe parsed line plus deterministic cue metadata."""

    scene_id: str = Field(min_length=1)
    line_index: int = Field(ge=MIN_VERSION, strict=True)
    cue_id: str = Field(min_length=1)
    pause_after_seconds: float = Field(ge=MIN_TIME_SECONDS, strict=True)
    performance_kind: ScriptLineKind
    line: Line

    @field_validator("scene_id", "cue_id")
    @classmethod
    def _codes_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("line_index", mode="before")
    @classmethod
    def _line_index_is_strict(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("line_index must be an integer")
        return value

    @field_validator("pause_after_seconds")
    @classmethod
    def _pause_is_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("pause_after_seconds must not be a boolean")
        return value


class ParsedScene(FrozenModel):
    """A validated scene with ordered line ids and declared trailing pause."""

    scene_id: str = Field(min_length=1)
    line_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    pause_after_seconds: float = Field(ge=MIN_TIME_SECONDS, strict=True)

    @field_validator("scene_id")
    @classmethod
    def _scene_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("line_ids")
    @classmethod
    def _line_ids_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for line_id in value:
            BoundedCode(line_id)
        return value

    @field_validator("event_ids")
    @classmethod
    def _event_ids_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("scene must contain at least one event")
        for event_id in value:
            BoundedCode(event_id)
        return value

    @field_validator("pause_after_seconds")
    @classmethod
    def _pause_is_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("pause_after_seconds must not be a boolean")
        return value


class ParsedBeat(FrozenModel):
    """One hashed, source-ordered pacing, Foley, or silence beat."""

    beat_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    kind: BeatKind
    text_hash: Sha256
    text_length_chars: int = Field(ge=MIN_TEXT_LENGTH_CHARS, strict=True)
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS, strict=True)
    after_line_id: str | None
    asset_ref: str | None
    asset_hash: Sha256 | None
    silence_quality: SilenceQuality | None

    @field_validator("beat_id", "scene_id", "after_line_id")
    @classmethod
    def _ids_are_bounded(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else value

    @field_validator("asset_ref")
    @classmethod
    def _asset_ref_is_safe(cls, value: str | None) -> str | None:
        if value is not None:
            reason = location_violation(value)
            if reason is not None:
                raise ValueError(f"asset_ref {reason}")
        return value

    @model_validator(mode="after")
    def _kind_specific_fields_match(self) -> ParsedBeat:
        has_asset = self.asset_ref is not None and self.asset_hash is not None
        if self.kind == BeatKind.FOLEY and not has_asset:
            raise ValueError("Foley beat requires asset ref and hash")
        if self.kind != BeatKind.FOLEY and (self.asset_ref is not None or self.asset_hash is not None):
            raise ValueError("only Foley beats may carry an asset")
        if self.kind == BeatKind.DESIGNED_SILENCE and self.silence_quality is None:
            raise ValueError("designed silence requires a quality")
        if self.kind != BeatKind.DESIGNED_SILENCE and self.silence_quality is not None:
            raise ValueError("only designed silence may carry a quality")
        return self


class ChapterCard(FrozenModel):
    """WF narrator metadata retained as a hash, never a spoken line."""

    chapter_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    text_hash: Sha256
    text_length_chars: int = Field(ge=MIN_TEXT_LENGTH_CHARS, strict=True)

    @field_validator("chapter_id", "scene_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class ParsedEvent(FrozenModel):
    """One source-order reference to a line, beat, or chapter card."""

    event_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    kind: ParsedEventKind

    @field_validator("event_id", "scene_id")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class ParsedScript(RecordBase):
    """Canonical, privacy-safe result of parsing one structured episode."""

    record_kind: Literal["parsed_script"] = "parsed_script"
    episode_id: str = Field(min_length=1)
    source_hash: Sha256
    scenes: tuple[ParsedScene, ...]
    parsed_lines: tuple[ParsedLine, ...]
    cue_order: tuple[str, ...]
    beats: tuple[ParsedBeat, ...]
    chapter_cards: tuple[ChapterCard, ...]
    events: tuple[ParsedEvent, ...]

    @field_validator("episode_id")
    @classmethod
    def _episode_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @model_validator(mode="after")
    def _ordering_is_self_consistent(self) -> ParsedScript:
        validate_target_id_uniqueness(
            parsed_lines=self.parsed_lines,
            beats=self.beats,
            chapter_cards=self.chapter_cards,
        )
        line_ids = tuple(item.line.line_id for item in self.parsed_lines)
        cue_ids = tuple(item.cue_id for item in self.parsed_lines)
        if len(set(line_ids)) != len(line_ids):
            raise ValueError("parsed line ids must be unique")
        if cue_ids != self.cue_order or len(set(cue_ids)) != len(cue_ids):
            raise ValueError("cue_order must exactly match unique parsed line cues")
        scene_ids = tuple(scene.scene_id for scene in self.scenes)
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("scene ids must be unique")
        expected_lines: list[str] = []
        expected_events: list[str] = []
        for scene in self.scenes:
            scene_lines = tuple(item.line.line_id for item in self.parsed_lines if item.scene_id == scene.scene_id)
            if scene.line_ids != scene_lines:
                raise ValueError("scene line membership must exactly match parsed line order")
            expected_lines.extend(scene.line_ids)
            expected_events.extend(scene.event_ids)
        if tuple(expected_lines) != line_ids:
            raise ValueError("scene line membership must cover every parsed line exactly once")
        event_ids = tuple(event.event_id for event in self.events)
        if tuple(expected_events) != event_ids or len(set(event_ids)) != len(event_ids):
            raise ValueError("scene event membership must exactly match unique event order")
        known_ids = (
            line_ids
            + tuple(item.beat_id for item in self.beats)
            + tuple(item.chapter_id for item in self.chapter_cards)
        )
        if set(event_ids) != set(known_ids):
            raise ValueError("events must reference every parsed object exactly once")
        validate_script_relationships(
            scenes=self.scenes,
            parsed_lines=self.parsed_lines,
            beats=self.beats,
            chapter_cards=self.chapter_cards,
            events=self.events,
        )
        return self

    def canonical_id(self) -> str:
        """Return the canonical semantic digest for receipt compatibility."""

        return canonical_record_id(self)


class _LineInput(FrozenModel):
    actor_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=SCRIPT_LIMITS.text)
    kind: ScriptLineKind
    pause_after_seconds: float = Field(ge=MIN_TIME_SECONDS, strict=True)

    @field_validator("actor_id")
    @classmethod
    def _actor_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("text")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("line text must not be blank")
        return value

    @field_validator("pause_after_seconds")
    @classmethod
    def _pause_is_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("pause_after_seconds must not be a boolean")
        return value


class _BeatInput(FrozenModel):
    kind: BeatKind
    text: str = Field(min_length=1, max_length=SCRIPT_LIMITS.text)
    after_line_index: int = Field(ge=MIN_TIME_SECONDS, strict=True)
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS, strict=True)
    asset_ref: str | None = None
    asset_hash: Sha256 | None = None
    silence_quality: SilenceQuality | None = None

    @field_validator("text")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("beat text must not be blank")
        return value

    @field_validator("asset_ref")
    @classmethod
    def _asset_ref_is_safe(cls, value: str | None) -> str | None:
        if value is not None:
            reason = location_violation(value)
            if reason is not None:
                raise ValueError(f"asset_ref {reason}")
        return value

    @model_validator(mode="after")
    def _kind_specific_fields_match(self) -> _BeatInput:
        has_asset = self.asset_ref is not None and self.asset_hash is not None
        if self.kind == BeatKind.FOLEY and not has_asset:
            raise ValueError("Foley beat requires asset ref and hash")
        if self.kind != BeatKind.FOLEY and (self.asset_ref is not None or self.asset_hash is not None):
            raise ValueError("only Foley beats may carry an asset")
        if self.kind == BeatKind.DESIGNED_SILENCE and self.silence_quality is None:
            raise ValueError("designed silence requires a quality")
        if self.kind != BeatKind.DESIGNED_SILENCE and self.silence_quality is not None:
            raise ValueError("only designed silence may carry a quality")
        return self


class _SceneInput(FrozenModel):
    scene_id: str = Field(min_length=1)
    pause_after_seconds: float = Field(ge=MIN_TIME_SECONDS, strict=True)
    lines: tuple[_LineInput, ...] = Field(max_length=SCRIPT_LIMITS.lines)
    beats: tuple[_BeatInput, ...] = Field(default=(), max_length=SCRIPT_LIMITS.beats)

    @field_validator("scene_id")
    @classmethod
    def _scene_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @model_validator(mode="after")
    def _scene_has_events(self) -> _SceneInput:
        if not self.lines and not self.beats:
            raise ValueError("scene must contain at least one line or beat")
        if any(beat.after_line_index > len(self.lines) for beat in self.beats):
            raise ValueError("beat after_line_index exceeds scene line count")
        if len(self.lines) + len(self.beats) > SCRIPT_LIMITS.events:
            raise ValueError("scene event count exceeds resource ceiling")
        return self

    @field_validator("pause_after_seconds")
    @classmethod
    def _pause_is_not_boolean(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("pause_after_seconds must not be a boolean")
        return value


class _ScriptInput(FrozenModel):
    episode_id: str = Field(min_length=1)
    scenes: tuple[_SceneInput, ...] = Field(max_length=SCRIPT_LIMITS.scenes)

    @field_validator("episode_id")
    @classmethod
    def _episode_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("scenes")
    @classmethod
    def _episode_has_scenes(cls, value: tuple[_SceneInput, ...]) -> tuple[_SceneInput, ...]:
        if not value:
            raise ValueError("episode must contain at least one scene")
        return value


class _WfTurnInput(FrozenModel):
    character: str = Field(min_length=1, max_length=SCRIPT_LIMITS.name, strict=True)
    text: str = Field(min_length=1, max_length=SCRIPT_LIMITS.text)
    confessional: bool = Field(strict=True)

    @field_validator("character", "text")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 0x20 for char in value):
            raise ValueError("WF text fields must be nonblank and contain no controls")
        return value


class _WfSceneInput(FrozenModel):
    scene_id: str = Field(min_length=1)
    turns: tuple[_WfTurnInput, ...] = Field(max_length=SCRIPT_LIMITS.turns)

    @field_validator("scene_id")
    @classmethod
    def _scene_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("turns")
    @classmethod
    def _scene_has_turns(cls, value: tuple[_WfTurnInput, ...]) -> tuple[_WfTurnInput, ...]:
        if not value:
            raise ValueError("WF scene must contain at least one turn")
        return value


class _WfScriptInput(FrozenModel):
    episode_id: str = Field(min_length=1)
    scenes: tuple[_WfSceneInput, ...] = Field(max_length=SCRIPT_LIMITS.scenes)

    @field_validator("episode_id")
    @classmethod
    def _episode_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("scenes")
    @classmethod
    def _episode_has_scenes(cls, value: tuple[_WfSceneInput, ...]) -> tuple[_WfSceneInput, ...]:
        if not value:
            raise ValueError("WF episode must contain at least one scene")
        return value


def _parse_error(message: str, code: str) -> ScriptParseError:
    return ScriptParseError(message, code=code, suggested_action={"auto_fix": False})


def _validation_code(exc: ValidationError) -> str:
    locations = tuple(part for error in exc.errors() for part in error["loc"])
    if "lines" in locations or "text" in locations:
        return "invalid_line"
    if "scene_id" in locations:
        return "invalid_scene"
    return "invalid_script"


def _spatial_preset(route: ActorRoute, kind: ScriptLineKind) -> str:
    return {
        ScriptLineKind.DIALOGUE: route.dialogue_spatial_preset,
        ScriptLineKind.CONFESSIONAL: route.confessional_spatial_preset,
        ScriptLineKind.OFF_SCREEN: route.off_screen_spatial_preset,
        ScriptLineKind.NARRATION: route.narration_spatial_preset,
        ScriptLineKind.ACTION: route.narration_spatial_preset,
        ScriptLineKind.VOICEOVER: route.narration_spatial_preset,
    }[kind]


def _build_line(
    source: _LineInput,
    route: ActorRoute,
    *,
    scene_id: str,
    scene_index: int,
    line_index: int,
) -> ParsedLine:
    line_id = f"line_{scene_index:04d}_{line_index:04d}"
    cue_id = f"cue_{scene_index:04d}_{line_index:04d}"
    line = Line(
        line_id=line_id,
        character_id=route.actor_id,
        profile=route.profile,
        text_hash=canonical_digest({"text": source.text}),
        text_length_chars=len(source.text),
        prosody=route.prosody,
        emotion=route.emotion,
        spatial_preset=_spatial_preset(route, source.kind),
        pronunciation_overrides=(),
        inherit_loudness=route.inherit_loudness,
    )
    return ParsedLine(
        scene_id=scene_id,
        line_index=line_index,
        cue_id=cue_id,
        pause_after_seconds=source.pause_after_seconds,
        line=line,
        performance_kind=source.kind,
    )


def _build_beat(
    source: _BeatInput,
    *,
    scene_id: str,
    scene_index: int,
    beat_index: int,
    line_ids: tuple[str, ...],
) -> ParsedBeat:
    beat_id = f"beat_{scene_index:04d}_{beat_index:04d}"
    after_line_id = line_ids[source.after_line_index - 1] if source.after_line_index > MIN_TIME_SECONDS else None
    return ParsedBeat(
        beat_id=beat_id,
        scene_id=scene_id,
        kind=source.kind,
        text_hash=canonical_digest({"text": source.text}),
        text_length_chars=len(source.text),
        duration_seconds=source.duration_seconds,
        after_line_id=after_line_id,
        asset_ref=source.asset_ref,
        asset_hash=source.asset_hash,
        silence_quality=source.silence_quality,
    )


def _scene_events(
    scene_id: str,
    line_ids: tuple[str, ...],
    beats: tuple[ParsedBeat, ...],
) -> tuple[ParsedEvent, ...]:
    events: list[ParsedEvent] = []
    for beat in (item for item in beats if item.after_line_id is None):
        events.append(ParsedEvent(event_id=beat.beat_id, scene_id=scene_id, kind=ParsedEventKind.BEAT))
    for line_id in line_ids:
        events.append(ParsedEvent(event_id=line_id, scene_id=scene_id, kind=ParsedEventKind.LINE))
        for beat in (item for item in beats if item.after_line_id == line_id):
            events.append(ParsedEvent(event_id=beat.beat_id, scene_id=scene_id, kind=ParsedEventKind.BEAT))
    return tuple(events)


def _build_scene(
    scene: _SceneInput,
    *,
    scene_index: int,
    actors: dict[str, ActorRoute],
) -> tuple[ParsedScene, tuple[ParsedLine, ...], tuple[ParsedBeat, ...], tuple[ParsedEvent, ...]]:
    parsed_lines: list[ParsedLine] = []
    for line_index, source in enumerate(scene.lines, start=1):
        route = actors.get(source.actor_id)
        if route is None:
            raise _parse_error("line references an unknown actor id", "unknown_actor")
        parsed_lines.append(
            _build_line(
                source,
                route,
                scene_id=scene.scene_id,
                scene_index=scene_index,
                line_index=line_index,
            )
        )
    line_ids = tuple(item.line.line_id for item in parsed_lines)
    beats = tuple(
        _build_beat(
            source,
            scene_id=scene.scene_id,
            scene_index=scene_index,
            beat_index=beat_index,
            line_ids=line_ids,
        )
        for beat_index, source in enumerate(scene.beats, start=1)
    )
    events = _scene_events(scene.scene_id, line_ids, beats)
    parsed_scene = ParsedScene(
        scene_id=scene.scene_id,
        line_ids=line_ids,
        event_ids=tuple(event.event_id for event in events),
        pause_after_seconds=scene.pause_after_seconds,
    )
    return parsed_scene, tuple(parsed_lines), beats, events


def parse_episode_script(
    document: Mapping[str, Any],
    *,
    project_id: str,
    created_by: str,
    actors: tuple[ActorRoute, ...],
) -> ParsedScript:
    """Parse structured episode data into a canonical, privacy-safe record."""

    if script_limit_violation(document):
        raise _parse_error("script exceeds a named resource ceiling", "invalid_script")
    try:
        actor_map = dump_revalidate_index(actors, ActorRoute, "actor_id")
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise _parse_error("actor roster failed strict validation", "invalid_actor_roster") from None

    try:
        script = _ScriptInput.model_validate(document)
    except ValidationError as exc:
        raise _parse_error("script input failed strict structural validation", _validation_code(exc)) from None
    scene_ids = tuple(scene.scene_id for scene in script.scenes)
    if len(set(scene_ids)) != len(scene_ids):
        raise _parse_error("episode contains duplicate scene ids", "invalid_scene")
    scenes: list[ParsedScene] = []
    lines: list[ParsedLine] = []
    beats: list[ParsedBeat] = []
    events: list[ParsedEvent] = []
    for scene_index, scene in enumerate(script.scenes, start=1):
        parsed_scene, parsed_lines, parsed_beats, parsed_events = _build_scene(
            scene, scene_index=scene_index, actors=actor_map
        )
        scenes.append(parsed_scene)
        lines.extend(parsed_lines)
        beats.extend(parsed_beats)
        events.extend(parsed_events)
    try:
        return ParsedScript(
            project_id=project_id,
            created_by=created_by,
            episode_id=script.episode_id,
            source_hash=canonical_digest(script.model_dump(mode="json")),
            scenes=tuple(scenes),
            parsed_lines=tuple(lines),
            cue_order=tuple(line.cue_id for line in lines),
            beats=tuple(beats),
            chapter_cards=(),
            events=tuple(events),
        )
    except ValidationError:
        raise _parse_error("parsed script failed canonical validation", "invalid_script") from None


def _wf_character_map(
    character_routes: Mapping[str, str],
    actors: dict[str, ActorRoute],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for character, actor_id in character_routes.items():
        try:
            bounded_actor_id = BoundedCode(actor_id)
        except (TypeError, ValueError):
            raise _parse_error("WF character route contains an invalid actor id", "invalid_actor_roster") from None
        if bounded_actor_id not in actors:
            raise _parse_error("WF character route references an unknown actor id", "unknown_actor")
        resolved[character] = bounded_actor_id
    return resolved


def _build_wf_scene(
    scene: _WfSceneInput,
    *,
    scene_index: int,
    actors: dict[str, ActorRoute],
    character_routes: dict[str, str],
    narrator_character: str,
) -> tuple[ParsedScene, tuple[ParsedLine, ...], tuple[ChapterCard, ...], tuple[ParsedEvent, ...]]:
    lines: list[ParsedLine] = []
    cards: list[ChapterCard] = []
    events: list[ParsedEvent] = []
    for turn in scene.turns:
        if turn.character == narrator_character:
            chapter_id = f"chapter_{scene_index:04d}_{len(cards) + 1:04d}"
            card = ChapterCard(
                chapter_id=chapter_id,
                scene_id=scene.scene_id,
                text_hash=canonical_digest({"text": turn.text}),
                text_length_chars=len(turn.text),
            )
            cards.append(card)
            events.append(
                ParsedEvent(
                    event_id=chapter_id,
                    scene_id=scene.scene_id,
                    kind=ParsedEventKind.CHAPTER_CARD,
                )
            )
            continue
        actor_id = character_routes.get(turn.character)
        route = actors.get(actor_id) if actor_id is not None else None
        if route is None:
            raise _parse_error("WF turn references an unknown character", "unknown_actor")
        kind = ScriptLineKind.CONFESSIONAL if turn.confessional else ScriptLineKind.DIALOGUE
        source = _LineInput(
            actor_id=actor_id,
            text=turn.text,
            kind=kind,
            pause_after_seconds=MIN_TIME_SECONDS,
        )
        line = _build_line(
            source,
            route,
            scene_id=scene.scene_id,
            scene_index=scene_index,
            line_index=len(lines) + 1,
        )
        lines.append(line)
        events.append(
            ParsedEvent(
                event_id=line.line.line_id,
                scene_id=scene.scene_id,
                kind=ParsedEventKind.LINE,
            )
        )
    parsed_scene = ParsedScene(
        scene_id=scene.scene_id,
        line_ids=tuple(line.line.line_id for line in lines),
        event_ids=tuple(event.event_id for event in events),
        pause_after_seconds=MIN_TIME_SECONDS,
    )
    return parsed_scene, tuple(lines), tuple(cards), tuple(events)


def parse_wf_episode_script(
    document: Mapping[str, Any],
    *,
    project_id: str,
    created_by: str,
    actors: tuple[ActorRoute, ...],
    character_routes: Mapping[str, str],
    narrator_character: str,
) -> ParsedScript:
    """Parse bounded WF scenes and turns while retaining narrator cards as metadata."""

    if script_limit_violation(document, wf=True):
        raise _parse_error("WF script exceeds a named resource ceiling", "invalid_script")
    try:
        narrator_character = validate_wf_name(narrator_character)
    except (TypeError, ValueError):
        raise _parse_error("WF narrator character is invalid", "invalid_script") from None
    try:
        actor_map = dump_revalidate_index(actors, ActorRoute, "actor_id")
        character_routes = validate_wf_routes(character_routes)
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise _parse_error("actor roster failed strict validation", "invalid_actor_roster") from None

    route_map = _wf_character_map(character_routes, actor_map)
    try:
        script = _WfScriptInput.model_validate(document)
    except ValidationError as exc:
        raise _parse_error("WF script failed strict structural validation", _validation_code(exc)) from None
    scene_ids = tuple(scene.scene_id for scene in script.scenes)
    if len(set(scene_ids)) != len(scene_ids):
        raise _parse_error("WF episode contains duplicate scene ids", "invalid_scene")
    scenes: list[ParsedScene] = []
    lines: list[ParsedLine] = []
    cards: list[ChapterCard] = []
    events: list[ParsedEvent] = []
    for scene_index, scene in enumerate(script.scenes, start=1):
        parsed_scene, scene_lines, scene_cards, scene_events = _build_wf_scene(
            scene,
            scene_index=scene_index,
            actors=actor_map,
            character_routes=route_map,
            narrator_character=narrator_character,
        )
        scenes.append(parsed_scene)
        lines.extend(scene_lines)
        cards.extend(scene_cards)
        events.extend(scene_events)
    try:
        return ParsedScript(
            project_id=project_id,
            created_by=created_by,
            episode_id=script.episode_id,
            source_hash=canonical_digest(script.model_dump(mode="json")),
            scenes=tuple(scenes),
            parsed_lines=tuple(lines),
            cue_order=tuple(line.cue_id for line in lines),
            beats=(),
            chapter_cards=tuple(cards),
            events=tuple(events),
        )
    except ValidationError:
        raise _parse_error("WF parsed script failed canonical validation", "invalid_script") from None
