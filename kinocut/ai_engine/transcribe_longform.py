"""Public long-form transcription facade and orchestration."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _get_video_duration
from ..limits import (
    LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNKS,
)
from ._longform_merge import _merge_chunk, _word_probability
from ._longform_models import (
    LongformChunk,
    LongformSegment,
    LongformTranscribePlan,
    LongformTranscribeResult,
    LongformWord,
    LongformTimingAdjustment,
)
from ._longform_planning import plan_longform_transcription
from ._longform_runtime import _format_chunk_result, _transcribe_chunk
from ._longform_validation import (
    _validate_chunk_seconds,
    _validate_longform_path,
    _validate_overlap_seconds,
)
from .transcribe import _validate_whisper_model


def _invalid_plan(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="invalid_plan")


def _validate_replay_plan(video: str, plan: LongformTranscribePlan, *, verify_media: bool) -> None:
    """Fail closed when a replay plan does not describe this complete source."""
    if not isinstance(plan, LongformTranscribePlan):
        raise _invalid_plan("Long-form replay requires a validated plan")
    if not isinstance(plan.chunks, tuple) or not plan.chunks:
        raise _invalid_plan("Long-form plan has no validated chunks; refusing to transcribe")
    if len(plan.chunks) > MAX_LONGFORM_TRANSCRIBE_CHUNKS:
        raise _invalid_plan(f"Long-form plan exceeds {MAX_LONGFORM_TRANSCRIBE_CHUNKS} chunks")
    try:
        LongformTranscribePlan.model_validate(plan.model_dump(mode="python"))
    except (ValueError, TypeError) as exc:
        raise _invalid_plan("Long-form replay plan contains invalid typed fields") from exc
    if Path(plan.video_path).resolve() != Path(video).resolve():
        raise _invalid_plan("Long-form plan source does not match the requested video")
    if verify_media and abs(_get_video_duration(video) - plan.duration) > 0.05:
        raise _invalid_plan("Long-form plan duration does not match the requested video")
    previous_end = 0.0
    for expected_index, chunk in enumerate(plan.chunks):
        if chunk.index != expected_index:
            raise _invalid_plan("Long-form plan chunk indices must be contiguous")
        if chunk.end > plan.duration + 1e-9 or chunk.duration > plan.chunk_seconds + 1e-9:
            raise _invalid_plan("Long-form plan chunk exceeds its source or configured cap")
        if expected_index == 0 and chunk.start != 0.0:
            raise _invalid_plan("Long-form plan must start at zero")
        if expected_index and (chunk.start <= plan.chunks[expected_index - 1].start or chunk.end <= previous_end):
            raise _invalid_plan("Long-form plan chunks must advance source starts and ends")
        if expected_index and (chunk.start > previous_end or previous_end - chunk.start > plan.overlap_seconds + 1e-9):
            raise _invalid_plan("Long-form plan chunks must provide bounded, gap-free coverage")
        previous_end = chunk.end
    if abs(previous_end - plan.duration) > 1e-9:
        raise _invalid_plan("Long-form plan must cover the complete source duration")


def _enforce_monotonic_words(words: list[LongformWord]) -> tuple[LongformTimingAdjustment, ...]:
    """Trim overlapping prefixes within observed spans; never manufacture new time."""
    adjustments = []
    for index in range(1, len(words)):
        previous = words[index - 1]
        current = words[index]
        if current.start < previous.end:
            start = previous.end
            if current.end <= start:
                raise MCPVideoError(
                    "Distinct word timing is fully covered by its predecessor; explicit alignment required",
                    error_type="validation_error",
                    code="invalid_transcript_timing",
                    suggested_action={
                        "auto_fix": False,
                        "word_index": index,
                        "chunk_index": current.chunk_index,
                        "description": "Review conflicting observed word spans; no timing was invented",
                    },
                )
            adjustments.append(
                LongformTimingAdjustment(
                    word_index=index,
                    chunk_index=current.chunk_index,
                    original_start=current.start,
                    observed_end=current.end,
                    trimmed_start=start,
                )
            )
            words[index] = current.model_copy(update={"start": start})
    return tuple(adjustments)


def _select_chunk_language(
    current: str,
    language_from_speech: bool,
    explicit_language: str | None,
    chunk_result: dict[str, Any],
    *,
    chunk_has_speech: bool,
) -> tuple[str, bool]:
    """Keep explicit or speech-backed language; never let a silent chunk overwrite speech."""
    if explicit_language is not None:
        return current, True
    chunk_language = str(chunk_result.get("language") or "unknown").strip() or "unknown"
    if chunk_language == "unknown":
        return current, language_from_speech
    if chunk_has_speech:
        if not language_from_speech:
            return chunk_language, True
        return current, language_from_speech
    if not language_from_speech and current == "unknown":
        return chunk_language, False
    return current, language_from_speech


def _prepare_longform_plan(
    video: str,
    *,
    chunk_seconds: int,
    overlap_seconds: int,
    scene_aware: bool,
    plan: LongformTranscribePlan | None,
) -> tuple[str, LongformTranscribePlan]:
    if plan is None:
        resolved = plan_longform_transcription(
            video,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
            scene_aware=scene_aware,
        )
        _validate_replay_plan(resolved.video_path, resolved, verify_media=False)
        return resolved.video_path, resolved
    validated_video = _validate_longform_path(video)
    _validate_chunk_seconds(plan.chunk_seconds)
    _validate_overlap_seconds(plan.overlap_seconds, plan.chunk_seconds)
    _validate_replay_plan(validated_video, plan, verify_media=True)
    return validated_video, plan


def transcribe_longform(
    video: str,
    *,
    model: str = "base",
    language: str | None = None,
    chunk_seconds: int = MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    overlap_seconds: int = LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    scene_aware: bool = True,
    plan: LongformTranscribePlan | None = None,
    deduplicate_segments: bool = False,
    _raw_segments_out: list[dict[str, Any]] | None = None,
) -> LongformTranscribeResult:
    """Transcribe media through deterministic overlapping Whisper chunks."""
    _validate_whisper_model(model)
    video, plan = _prepare_longform_plan(
        video,
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
        scene_aware=scene_aware,
        plan=plan,
    )

    words: list[LongformWord] = []
    segments: list[LongformSegment] = []
    transcript_pieces: list[tuple[float, float, int, int, str]] = []
    raw_segments: list[tuple[float, float, int, dict[str, Any]]] = []
    detected_language = language or "unknown"
    language_from_speech = language is not None
    previous_end: float | None = None
    model_cache: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="kc_longform_") as work_dir:
        for chunk in plan.chunks:
            chunk_result = _transcribe_chunk(
                video, chunk, model=model, language=language, work_dir=work_dir, model_cache=model_cache
            )
            before_words, before_segments = len(words), len(segments)
            _merge_chunk(
                words,
                segments,
                chunk_result,
                chunk,
                overlap_seconds=plan.overlap_seconds,
                prev_chunk_end=previous_end,
                deduplicate_segments=deduplicate_segments,
                transcript_pieces=transcript_pieces,
                raw_segments_out=raw_segments if _raw_segments_out is not None else None,
            )
            detected_language, language_from_speech = _select_chunk_language(
                detected_language,
                language_from_speech,
                language,
                chunk_result,
                chunk_has_speech=len(words) > before_words or len(segments) > before_segments,
            )
            previous_end = chunk.end

    words.sort(key=lambda word: (word.start, word.end, word.chunk_index))
    segments.sort(key=lambda segment: (segment.start, segment.end, segment.chunk_index))
    transcript_pieces.sort(key=lambda piece: (piece[0], piece[1], piece[2], piece[3]))
    if _raw_segments_out is not None:
        raw_segments.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
        _raw_segments_out.extend({**entry[3], "id": index} for index, entry in enumerate(raw_segments))
    timing_adjustments = _enforce_monotonic_words(words)
    transcript = " ".join(piece[4] for piece in transcript_pieces).strip()
    return LongformTranscribeResult(
        video_path=video,
        duration=plan.duration,
        language=detected_language,
        transcript=transcript,
        segments=tuple(segments),
        words=tuple(words),
        chunk_count=len(plan.chunks),
        model=model,
        plan=plan,
        timing_adjustments=timing_adjustments,
    )


__all__ = [
    "LongformChunk",
    "LongformSegment",
    "LongformTranscribePlan",
    "LongformTranscribeResult",
    "LongformWord",
    "_format_chunk_result",
    "_merge_chunk",
    "_validate_chunk_seconds",
    "_validate_overlap_seconds",
    "_word_probability",
    "plan_longform_transcription",
    "transcribe_longform",
]
