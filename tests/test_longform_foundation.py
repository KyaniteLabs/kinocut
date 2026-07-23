from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.ai_engine import _longform_validation as validation
from kinocut.ai_engine._longform_models import (
    LongformChunk,
    LongformSegment,
    LongformTranscribePlan,
    LongformTranscribeResult,
    LongformWord,
)
from kinocut.ai_engine._longform_validation import (
    _validate_chunk_seconds,
    _validate_longform_path,
    _validate_overlap_seconds,
)
from kinocut.errors import InputFileError, MCPVideoError
from kinocut.limits import (
    LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNKS,
    MAX_VIDEO_DURATION,
    MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
)


def _chunk() -> LongformChunk:
    return LongformChunk(index=0, start=0, end=60, duration=60)


def _plan() -> LongformTranscribePlan:
    return LongformTranscribePlan(
        video_path="source.mp4",
        duration=60,
        chunk_seconds=60,
        overlap_seconds=5,
        chunks=[_chunk()],
    )


def _result() -> LongformTranscribeResult:
    return LongformTranscribeResult(
        video_path="source.mp4",
        duration=60,
        language="en",
        transcript="hello",
        segments=[LongformSegment(start=0, end=1, text="hello", chunk_index=0)],
        words=[LongformWord(word="hello", start=0, end=1, chunk_index=0, probability=0.8)],
        chunk_count=1,
        model="base",
        plan=_plan(),
    )


def test_longform_policy_constants_are_bounded() -> None:
    assert MAX_VIDEO_DURATION == 14_400
    assert MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS == 30
    assert MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS == 1_500
    assert LONGFORM_TRANSCRIBE_OVERLAP_SECONDS == 15
    assert MAX_LONGFORM_TRANSCRIBE_CHUNKS == 64


@pytest.mark.parametrize("factory", [_chunk, _plan, _result])
def test_models_are_strict_frozen_and_json_stable(factory) -> None:
    value = factory()
    assert type(value).model_validate_json(value.model_dump_json()) == value
    for field in ("chunks", "segments", "words"):
        if hasattr(value, field):
            assert isinstance(getattr(value, field), tuple)
    with pytest.raises(ValidationError):
        value.model_copy(update={"unknown": True}).model_validate({**value.model_dump(), "unknown": True})
    with pytest.raises(ValidationError):
        setattr(value, next(iter(type(value).model_fields)), "changed")


@pytest.mark.parametrize(
    "constructor,kwargs",
    [
        (LongformChunk, {"index": 0, "start": 1, "end": 1, "duration": 1}),
        (LongformChunk, {"index": 0, "start": 0, "end": 2, "duration": 1}),
        (LongformWord, {"word": "x", "start": 1, "end": 1, "chunk_index": 0}),
        (LongformSegment, {"start": 2, "end": 1, "text": "x", "chunk_index": 0}),
        (
            LongformTranscribePlan,
            {
                "video_path": "x",
                "duration": 1,
                "chunk_seconds": 30,
                "overlap_seconds": 30,
                "chunks": [],
            },
        ),
    ],
)
def test_models_reject_invalid_ranges(constructor, kwargs) -> None:
    with pytest.raises(ValidationError):
        constructor(**kwargs)


def test_result_must_match_plan_lineage() -> None:
    payload = _result().model_dump()
    payload["chunk_count"] = 0
    with pytest.raises(ValidationError, match="chunk_count"):
        LongformTranscribeResult.model_validate(payload)
    payload = _result().model_dump()
    payload["duration"] = 59
    with pytest.raises(ValidationError, match=r"plan\.duration"):
        LongformTranscribeResult.model_validate(payload)


@pytest.mark.parametrize(
    "value,code",
    [
        (0, "invalid_parameter"),
        (True, "invalid_parameter"),
        (MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS - 1, "chunk_too_small"),
        (MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS + 1, "chunk_too_large"),
    ],
)
def test_chunk_validation_rejects_invalid_values(value, code) -> None:
    with pytest.raises(MCPVideoError) as exc:
        _validate_chunk_seconds(value)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "overlap,chunk,code", [(-1, 60, "invalid_parameter"), (True, 60, "invalid_parameter"), (60, 60, "invalid_overlap")]
)
def test_overlap_validation_rejects_invalid_values(overlap, chunk, code) -> None:
    with pytest.raises(MCPVideoError) as exc:
        _validate_overlap_seconds(overlap, chunk)
    assert exc.value.code == code


def test_parameter_validation_accepts_policy_edges() -> None:
    assert _validate_chunk_seconds(MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS) == 30
    assert _validate_overlap_seconds(0, 30) == 0


def test_longform_path_rejects_null_byte() -> None:
    with pytest.raises(InputFileError):
        _validate_longform_path("bad\x00path.mp4")


@pytest.mark.parametrize("duration,code", [(0, "invalid_input"), (MAX_VIDEO_DURATION + 1, "duration_too_long")])
def test_longform_path_rejects_invalid_duration(monkeypatch, duration, code) -> None:
    monkeypatch.setattr(validation, "_validate_input_path", lambda path: path)
    monkeypatch.setattr(validation, "_get_video_duration", lambda path: duration)
    with pytest.raises(MCPVideoError) as exc:
        _validate_longform_path("source.mp4")
    assert exc.value.code == code


def test_longform_path_accepts_over_legacy_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(validation, "_validate_input_path", lambda path: path)
    monkeypatch.setattr(validation, "_get_video_duration", lambda path: 3_601)
    assert _validate_longform_path("source.mp4") == "source.mp4"
