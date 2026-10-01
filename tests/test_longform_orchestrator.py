from __future__ import annotations

from copy import deepcopy

import pytest

from kinocut.ai_engine import transcribe as legacy
from kinocut.ai_engine import transcribe_longform as facade
from kinocut.ai_engine._longform_models import LongformChunk, LongformTranscribePlan
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_AI_TRANSCRIBE_DURATION


def _plan(*, path: str = "source.mp4", duration: float = 60) -> LongformTranscribePlan:
    return LongformTranscribePlan(
        video_path=path,
        duration=duration,
        chunk_seconds=40,
        overlap_seconds=5,
        chunks=(
            LongformChunk(index=0, start=0, end=40, duration=40),
            LongformChunk(index=1, start=35, end=duration, duration=duration - 35),
        ),
    )


def _stub_validation(monkeypatch, duration: float = 60) -> None:
    monkeypatch.setattr(facade, "_validate_whisper_model", lambda model: model)
    monkeypatch.setattr(facade, "_validate_longform_path", lambda path: path)
    monkeypatch.setattr(facade, "_get_video_duration", lambda path: duration)


def _chunk_results() -> list[dict]:
    return [
        {
            "language": "en",
            "segments": [
                {
                    "text": "alpha beta",
                    "start": 0,
                    "end": 36,
                    "words": [
                        {"word": "alpha", "start": 0, "end": 1, "probability": 0.9},
                        {"word": "beta", "start": 35.5, "end": 36, "probability": 0.8},
                    ],
                }
            ],
        },
        {
            "language": "en",
            "segments": [
                {
                    "text": "beta gamma",
                    "start": 0.5,
                    "end": 2,
                    "words": [
                        {"word": "beta", "start": 0.5, "end": 1},
                        {"word": "gamma", "start": 0.8, "end": 1.5},
                    ],
                }
            ],
        },
    ]


def test_transcribe_longform_merges_dedups_and_preserves_positive_width(monkeypatch) -> None:
    _stub_validation(monkeypatch)
    results = _chunk_results()
    original = deepcopy(results)
    monkeypatch.setattr(facade, "_transcribe_chunk", lambda video, chunk, **kwargs: results[chunk.index])
    result = facade.transcribe_longform("source.mp4", model="base", plan=_plan())
    assert result.transcript == "alpha beta gamma"
    assert result.language == "en"
    assert result.chunk_count == 2
    assert [word.word for word in result.words] == ["alpha", "beta", "gamma"]
    assert [word.start for word in result.words] == sorted(word.start for word in result.words)
    assert [segment.start for segment in result.segments] == sorted(segment.start for segment in result.segments)
    assert result.words[-1].start == result.words[-2].end
    assert result.words[-1].end == 36.5
    assert len(result.timing_adjustments) == 1
    assert result.timing_adjustments[0].original_start == 35.8
    assert result.timing_adjustments[0].trimmed_start == 36
    assert isinstance(result.words, tuple)
    assert results == original


def test_transcribe_longform_uses_planner_when_plan_absent(monkeypatch) -> None:
    _stub_validation(monkeypatch)
    plan = _plan()
    monkeypatch.setattr(facade, "plan_longform_transcription", lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        facade,
        "_transcribe_chunk",
        lambda *args, **kwargs: {"language": "en", "segments": []},
    )
    result = facade.transcribe_longform("source.mp4")
    assert result.plan is plan
    assert result.transcript == ""


def test_transcribe_longform_falls_back_to_segment_text(monkeypatch) -> None:
    _stub_validation(monkeypatch)
    monkeypatch.setattr(
        facade,
        "_transcribe_chunk",
        lambda *args, **kwargs: {
            "language": "en",
            "segments": [{"text": "spoken phrase", "start": 0, "end": 1, "words": []}],
        },
    )
    result = facade.transcribe_longform("source.mp4", plan=_plan())
    assert result.transcript == "spoken phrase spoken phrase"
    assert result.words == ()


def test_transcribe_longform_rejects_bad_model_before_planning(monkeypatch) -> None:
    def reject(model):
        raise MCPVideoError("bad model", error_type="validation_error", code="invalid_parameter")

    monkeypatch.setattr(facade, "_validate_whisper_model", reject)
    monkeypatch.setattr(
        facade,
        "plan_longform_transcription",
        lambda *args, **kwargs: pytest.fail("planning must not run"),
    )
    with pytest.raises(MCPVideoError) as exc:
        facade.transcribe_longform("source.mp4", model="invalid")
    assert exc.value.code == "invalid_parameter"


def test_replay_rejects_empty_plan(monkeypatch) -> None:
    _stub_validation(monkeypatch)
    empty = LongformTranscribePlan(
        video_path="source.mp4",
        duration=60,
        chunk_seconds=40,
        overlap_seconds=5,
        chunks=(),
    )
    with pytest.raises(MCPVideoError) as exc:
        facade.transcribe_longform("source.mp4", plan=empty)
    assert exc.value.code == "invalid_plan"


@pytest.mark.parametrize(
    "video,plan,duration",
    [
        ("other.mp4", _plan(), 60),
        ("source.mp4", _plan(), 61),
        (
            "source.mp4",
            LongformTranscribePlan(
                video_path="source.mp4",
                duration=60,
                chunk_seconds=40,
                overlap_seconds=5,
                chunks=(
                    LongformChunk(index=0, start=0, end=30, duration=30),
                    LongformChunk(index=1, start=40, end=60, duration=20),
                ),
            ),
            60,
        ),
    ],
)
def test_replay_plan_must_match_complete_source(monkeypatch, video, plan, duration) -> None:
    _stub_validation(monkeypatch, duration)
    with pytest.raises(MCPVideoError) as exc:
        facade.transcribe_longform(video, plan=plan)
    assert exc.value.code == "invalid_plan"


def test_legacy_transcribe_still_rejects_over_3600_seconds(monkeypatch) -> None:
    monkeypatch.setattr(legacy, "_get_video_duration", lambda path: MAX_AI_TRANSCRIBE_DURATION + 1)
    with pytest.raises(MCPVideoError) as exc:
        legacy._validate_transcribe_duration("source.mp4")
    assert exc.value.code == "duration_too_long"
