"""Strict, source-time semantic timeline contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = str
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_SOURCE_ID_PATTERN = r"^source:[0-9a-f]{64}$"
_SPAN_ID_PATTERN = r"^[a-z_]+:[0-9a-f]{64}$"


class FrozenModel(BaseModel):
    """Immutable contract base used by semantic artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def canonical_digest(value: BaseModel | dict[str, Any], *, exclude: set[str] | None = None) -> Sha256:
    """Hash one JSON-compatible payload with stable field and separator ordering."""

    payload = value.model_dump(mode="json", exclude=exclude or set()) if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class SourceMedia(FrozenModel):
    schema_version: Literal[1] = 1
    source_id: str = Field(pattern=_SOURCE_ID_PATTERN)
    content_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    duration_seconds: float = Field(gt=0.0)

    @classmethod
    def create(cls, *, content_sha256: Sha256, duration_seconds: float) -> Self:
        digest = content_sha256.removeprefix("sha256:")
        return cls(
            source_id=f"source:{digest}",
            content_sha256=content_sha256,
            duration_seconds=duration_seconds,
        )

    @model_validator(mode="after")
    def stable_source_id(self) -> Self:
        expected = "source:" + self.content_sha256.removeprefix("sha256:")
        if self.source_id != expected:
            raise ValueError("source id does not match the source content hash")
        return self


class AnalyzerProvenance(FrozenModel):
    analyzer_id: str = Field(min_length=1, pattern=r"^[a-z0-9_.-]+$")
    analyzer_version: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    determinism_scope: str = Field(min_length=1)
    local_execution: Literal[True] = True
    network_used: Literal[False] = False


class SourceSpan(FrozenModel):
    """Base contract for evidence that maps to the immutable source clock."""

    KIND: ClassVar[str]

    schema_version: Literal[1] = 1
    kind: str
    span_id: str = Field(pattern=_SPAN_ID_PATTERN)
    span_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    source_id: str = Field(pattern=_SOURCE_ID_PATTERN)
    source_content_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    source_duration_seconds: float = Field(gt=0.0)
    source_start_seconds: float = Field(ge=0.0)
    source_end_seconds: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: AnalyzerProvenance
    uncertainty: tuple[str, ...] = ()

    @classmethod
    def _create(cls, *, source: SourceMedia, **values: Any) -> Self:
        payload = {
            "kind": cls.KIND,
            "source_id": source.source_id,
            "source_content_sha256": source.content_sha256,
            "source_duration_seconds": source.duration_seconds,
            **values,
        }
        prototype = cls.model_construct(
            span_id=f"{cls.KIND}:" + "0" * 64,
            span_sha256="sha256:" + "0" * 64,
            **payload,
        )
        digest = canonical_digest(prototype, exclude={"span_id", "span_sha256"})
        return cls(
            span_id=f"{cls.KIND}:{digest.removeprefix('sha256:')}",
            span_sha256=digest,
            **payload,
        )

    @model_validator(mode="after")
    def validate_source_time_and_identity(self) -> Self:
        if self.kind != self.KIND:
            raise ValueError(f"span kind must be {self.KIND}")
        if self.source_end_seconds < self.source_start_seconds:
            raise ValueError("source end must not precede source start")
        if self.source_end_seconds > self.source_duration_seconds:
            raise ValueError("span exceeds source duration")
        if self.KIND != "keyframe" and self.source_end_seconds == self.source_start_seconds:
            raise ValueError("non-keyframe spans require positive source duration")
        expected_hash = canonical_digest(self, exclude={"span_id", "span_sha256"})
        expected_id = f"{self.KIND}:{expected_hash.removeprefix('sha256:')}"
        if self.span_sha256 != expected_hash:
            raise ValueError("span hash does not match canonical span content")
        if self.span_id != expected_id:
            raise ValueError("stable span id does not match canonical span content")
        if len(self.uncertainty) != len(set(self.uncertainty)):
            raise ValueError("uncertainty reasons must be unique")
        return self


class WordSpan(SourceSpan):
    KIND: ClassVar[str] = "word"

    kind: Literal["word"] = "word"
    text: str | None = Field(default=None, min_length=1)
    text_status: Literal["observed", "uncertain", "unavailable"] = "observed"
    disfluency: Literal["none", "filler", "false_start"] = "none"
    retake_group_id: str | None = Field(default=None, min_length=1)
    take_id: str | None = Field(default=None, min_length=1)
    selected_take: bool | None = None

    @classmethod
    def create(
        cls,
        *,
        source: SourceMedia,
        start_seconds: float,
        end_seconds: float,
        confidence: float,
        provenance: AnalyzerProvenance,
        text: str | None,
        text_status: Literal["observed", "uncertain", "unavailable"] = "observed",
        uncertainty: tuple[str, ...] = (),
        disfluency: Literal["none", "filler", "false_start"] = "none",
        retake_group_id: str | None = None,
        take_id: str | None = None,
        selected_take: bool | None = None,
    ) -> Self:
        return cls._create(
            source=source,
            source_start_seconds=start_seconds,
            source_end_seconds=end_seconds,
            confidence=confidence,
            provenance=provenance,
            text=text,
            text_status=text_status,
            uncertainty=uncertainty,
            disfluency=disfluency,
            retake_group_id=retake_group_id,
            take_id=take_id,
            selected_take=selected_take,
        )

    @model_validator(mode="after")
    def preserve_text_uncertainty(self) -> Self:
        if self.text_status == "unavailable" and self.text is not None:
            raise ValueError("unavailable transcript text must remain absent")
        if self.text_status != "unavailable" and self.text is None:
            raise ValueError("observed or uncertain transcript spans require text")
        if self.text_status == "uncertain" and not self.uncertainty:
            raise ValueError("uncertain transcript text requires an uncertainty reason")
        retake_values = (self.retake_group_id, self.take_id, self.selected_take)
        if any(value is not None for value in retake_values) and any(value is None for value in retake_values):
            raise ValueError("retake evidence requires group, take, and selected status")
        return self


class SpeakerSpan(SourceSpan):
    KIND: ClassVar[str] = "speaker"

    kind: Literal["speaker"] = "speaker"
    speaker_label: str | None = Field(default=None, min_length=1)
    label_status: Literal["observed", "uncertain", "unavailable"] = "observed"

    @classmethod
    def create(
        cls,
        *,
        source: SourceMedia,
        start_seconds: float,
        end_seconds: float,
        confidence: float,
        provenance: AnalyzerProvenance,
        speaker_label: str | None,
        label_status: Literal["observed", "uncertain", "unavailable"] = "observed",
        uncertainty: tuple[str, ...] = (),
    ) -> Self:
        return cls._create(
            source=source,
            source_start_seconds=start_seconds,
            source_end_seconds=end_seconds,
            confidence=confidence,
            provenance=provenance,
            speaker_label=speaker_label,
            label_status=label_status,
            uncertainty=uncertainty,
        )

    @model_validator(mode="after")
    def preserve_label_uncertainty(self) -> Self:
        if self.label_status == "observed" and self.speaker_label is None:
            raise ValueError("observed speaker spans require a source label")
        if self.label_status == "unavailable" and self.speaker_label is not None:
            raise ValueError("unavailable speaker labels must remain absent")
        if self.label_status == "uncertain" and not self.uncertainty:
            raise ValueError("uncertain speaker labels require an uncertainty reason")
        return self


class ShotSpan(SourceSpan):
    KIND: ClassVar[str] = "shot"

    kind: Literal["shot"] = "shot"
    ordinal: int = Field(ge=0)

    @classmethod
    def create(
        cls,
        *,
        source: SourceMedia,
        start_seconds: float,
        end_seconds: float,
        confidence: float,
        provenance: AnalyzerProvenance,
        ordinal: int,
        uncertainty: tuple[str, ...] = (),
    ) -> Self:
        return cls._create(
            source=source,
            source_start_seconds=start_seconds,
            source_end_seconds=end_seconds,
            confidence=confidence,
            provenance=provenance,
            ordinal=ordinal,
            uncertainty=uncertainty,
        )


class SceneSpan(SourceSpan):
    KIND: ClassVar[str] = "scene"

    kind: Literal["scene"] = "scene"
    ordinal: int = Field(ge=0)

    @classmethod
    def create(
        cls,
        *,
        source: SourceMedia,
        start_seconds: float,
        end_seconds: float,
        confidence: float,
        provenance: AnalyzerProvenance,
        ordinal: int,
        uncertainty: tuple[str, ...] = (),
    ) -> Self:
        return cls._create(
            source=source,
            source_start_seconds=start_seconds,
            source_end_seconds=end_seconds,
            confidence=confidence,
            provenance=provenance,
            ordinal=ordinal,
            uncertainty=uncertainty,
        )


class SilenceSpan(SourceSpan):
    KIND: ClassVar[str] = "silence"

    kind: Literal["silence"] = "silence"
    mean_dbfs: float | None = None

    @classmethod
    def create(
        cls,
        *,
        source: SourceMedia,
        start_seconds: float,
        end_seconds: float,
        confidence: float,
        provenance: AnalyzerProvenance,
        mean_dbfs: float | None = None,
        uncertainty: tuple[str, ...] = (),
    ) -> Self:
        return cls._create(
            source=source,
            source_start_seconds=start_seconds,
            source_end_seconds=end_seconds,
            confidence=confidence,
            provenance=provenance,
            mean_dbfs=mean_dbfs,
            uncertainty=uncertainty,
        )


class AudioEventSpan(SourceSpan):
    KIND: ClassVar[str] = "audio_event"

    kind: Literal["audio_event"] = "audio_event"
    event_type: str = Field(min_length=1)

    @classmethod
    def create(
        cls,
        *,
        source: SourceMedia,
        start_seconds: float,
        end_seconds: float,
        confidence: float,
        provenance: AnalyzerProvenance,
        event_type: str,
        uncertainty: tuple[str, ...] = (),
    ) -> Self:
        return cls._create(
            source=source,
            source_start_seconds=start_seconds,
            source_end_seconds=end_seconds,
            confidence=confidence,
            provenance=provenance,
            event_type=event_type,
            uncertainty=uncertainty,
        )


class KeyframeSpan(SourceSpan):
    KIND: ClassVar[str] = "keyframe"

    kind: Literal["keyframe"] = "keyframe"

    @classmethod
    def create(
        cls,
        *,
        source: SourceMedia,
        timestamp_seconds: float,
        confidence: float,
        provenance: AnalyzerProvenance,
        uncertainty: tuple[str, ...] = (),
    ) -> Self:
        return cls._create(
            source=source,
            source_start_seconds=timestamp_seconds,
            source_end_seconds=timestamp_seconds,
            confidence=confidence,
            provenance=provenance,
            uncertainty=uncertainty,
        )


class SemanticTimeline(FrozenModel):
    schema_version: Literal[1] = 1
    artifact_kind: Literal["semantic_timeline"] = "semantic_timeline"
    source: SourceMedia
    words: tuple[WordSpan, ...] = ()
    speakers: tuple[SpeakerSpan, ...] = ()
    shots: tuple[ShotSpan, ...] = ()
    scenes: tuple[SceneSpan, ...] = ()
    silences: tuple[SilenceSpan, ...] = ()
    audio_events: tuple[AudioEventSpan, ...] = ()
    keyframes: tuple[KeyframeSpan, ...] = ()
    timeline_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @property
    def spans(self) -> tuple[SourceSpan, ...]:
        return (
            *self.words,
            *self.speakers,
            *self.shots,
            *self.scenes,
            *self.silences,
            *self.audio_events,
            *self.keyframes,
        )

    @classmethod
    def create(cls, *, source: SourceMedia, **tracks: Any) -> Self:
        canonical_tracks: dict[str, Any] = {
            name: tuple(
                sorted(
                    tracks.get(name, ()),
                    key=lambda span: (span.source_start_seconds, span.source_end_seconds, span.span_id),
                )
            )
            for name in ("words", "speakers", "shots", "scenes", "silences", "audio_events", "keyframes")
        }
        prototype = cls.model_construct(source=source, timeline_sha256="sha256:" + "0" * 64, **canonical_tracks)
        digest = canonical_digest(prototype, exclude={"timeline_sha256"})
        return cls(source=source, timeline_sha256=digest, **canonical_tracks)

    @model_validator(mode="after")
    def validate_timeline(self) -> Self:
        if any(span.source_id != self.source.source_id for span in self.spans):
            raise ValueError("every semantic span must map to the timeline source")
        if len({span.span_id for span in self.spans}) != len(self.spans):
            raise ValueError("semantic span ids must be unique")
        for track_name in ("words", "speakers", "shots", "scenes", "silences", "audio_events", "keyframes"):
            track = getattr(self, track_name)
            if (
                tuple(
                    sorted(track, key=lambda span: (span.source_start_seconds, span.source_end_seconds, span.span_id))
                )
                != track
            ):
                raise ValueError(f"{track_name} must use canonical source-time order")
        expected = canonical_digest(self, exclude={"timeline_sha256"})
        if self.timeline_sha256 != expected:
            raise ValueError("timeline hash does not match canonical timeline content")
        return self

    def span_by_id(self, span_id: str) -> SourceSpan | None:
        return next((span for span in self.spans if span.span_id == span_id), None)
