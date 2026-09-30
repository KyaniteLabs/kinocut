"""Public long-form transcription facade and orchestration."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _get_video_duration
from ..limits import LONGFORM_TRANSCRIBE_OVERLAP_SECONDS, MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS
from ._longform_merge import _merge_chunk, _word_probability
from ._longform_models import (
    LongformChunk,
    LongformSegment,
    LongformTranscribePlan,
    LongformTranscribeResult,
    LongformWord,
)
from ._longform_planning import plan_longform_transcription
from ._longform_runtime import _format_chunk_result, _transcribe_chunk
from ._longform_validation import (
    _validate_chunk_seconds,
    _validate_longform_path,
    _validate_overlap_seconds,
)
from .transcribe import _validate_whisper_model

_MIN_WORD_WIDTH_SECONDS = 0.001


def _invalid_plan(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="invalid_plan")


def _validate_replay_plan(video: str, plan: LongformTranscribePlan, *, verify_media: bool) -> None:
    """Fail closed when a replay plan does not describe this complete source."""
    if not plan.chunks:
        raise _invalid_plan("Long-form plan is empty; refusing to transcribe")
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
        if expected_index and (chunk.start > previous_end or previous_end - chunk.start > plan.overlap_seconds + 1e-9):
            raise _invalid_plan("Long-form plan chunks must provide bounded, gap-free coverage")
        previous_end = chunk.end
    if abs(previous_end - plan.duration) > 1e-9:
        raise _invalid_plan("Long-form plan must cover the complete source duration")


def _enforce_monotonic_words(words: list[LongformWord]) -> None:
    """Snap boundary overlaps forward while retaining at least 1ms word width."""
    for index in range(1, len(words)):
        previous = words[index - 1]
        current = words[index]
        if current.start < previous.end:
            start = previous.end
            end = max(current.end, start + _MIN_WORD_WIDTH_SECONDS)
            words[index] = current.model_copy(update={"start": start, "end": end})


def transcribe_longform(
    video: str,
    *,
    model: str = "base",
    language: str | None = None,
    chunk_seconds: int = MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    overlap_seconds: int = LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    scene_aware: bool = True,
    plan: LongformTranscribePlan | None = None,
) -> LongformTranscribeResult:
    """Transcribe media through deterministic overlapping Whisper chunks."""
    _validate_whisper_model(model)
    if plan is None:
        plan = plan_longform_transcription(
            video,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
            scene_aware=scene_aware,
        )
        video = plan.video_path
        _validate_replay_plan(video, plan, verify_media=False)
    else:
        video = _validate_longform_path(video)
        _validate_chunk_seconds(plan.chunk_seconds)
        _validate_overlap_seconds(plan.overlap_seconds, plan.chunk_seconds)
        _validate_replay_plan(video, plan, verify_media=True)

    words: list[LongformWord] = []
    segments: list[LongformSegment] = []
    detected_language = language or "unknown"
    previous_end: float | None = None
    model_cache: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="kc_longform_") as work_dir:
        for chunk in plan.chunks:
            chunk_result = _transcribe_chunk(
                video,
                chunk,
                model=model,
                language=language,
                work_dir=work_dir,
                model_cache=model_cache,
            )
            if chunk_result.get("language", "unknown") != "unknown":
                detected_language = str(chunk_result["language"])
            _merge_chunk(
                words,
                segments,
                chunk_result,
                chunk,
                overlap_seconds=plan.overlap_seconds,
                prev_chunk_end=previous_end,
            )
            previous_end = chunk.end

    words.sort(key=lambda word: (word.start, word.end, word.chunk_index))
    segments.sort(key=lambda segment: (segment.start, segment.end, segment.chunk_index))
    _enforce_monotonic_words(words)
    transcript = " ".join(word.word for word in words).strip()
    if not transcript:
        transcript = " ".join(segment.text for segment in segments).strip()
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
