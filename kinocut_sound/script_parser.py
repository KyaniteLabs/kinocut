"""Typed script records and numeric input contracts for sound episode planning."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import (
    BoundedCode,
    FrozenModel,
    RecordBase,
    Sha256,
    canonical_record_id,
    location_violation,
)
from kinocut_sound._errors import SoundContractError
from kinocut_sound._script_integrity import (
    validate_script_relationships,
    validate_target_id_uniqueness,
)
from kinocut_sound._script_resource_limits import SCRIPT_LIMITS
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

    @field_validator("pause_after_seconds", mode="before")
    @classmethod
    def _pause_is_not_boolean(cls, value: Any) -> Any:
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

    @field_validator("pause_after_seconds", mode="before")
    @classmethod
    def _pause_is_not_boolean(cls, value: Any) -> Any:
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
        lines_by_scene: dict[str, list[str]] = {}
        for item in self.parsed_lines:
            lines_by_scene.setdefault(item.scene_id, []).append(item.line.line_id)
        for scene in self.scenes:
            scene_lines = tuple(lines_by_scene.get(scene.scene_id, ()))
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

    @field_validator("pause_after_seconds", mode="before")
    @classmethod
    def _pause_is_not_boolean(cls, value: Any) -> Any:
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

    @field_validator("pause_after_seconds", mode="before")
    @classmethod
    def _pause_is_not_boolean(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("pause_after_seconds must not be a boolean")
        return value
