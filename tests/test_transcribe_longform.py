"""Behavioral tests for the long-form transcription path.

Covers the Phase A1 contract for ``kinocut/ai_engine/transcribe_longform.py``:
- Planning media >3600s without creating a huge media fixture (use a stub).
- Monotonic merged timestamps across chunk boundaries.
- Overlap dedup of duplicated words.
- Full-duration coverage from chunk plan.
- Size cap on individual chunks.
- Deterministic output across replays.
- Legacy ``ai_transcribe`` >3600s rejection preserved.

These tests focus on the deterministic chunking, planning, and merger
behavior — they intentionally do **not** invoke Whisper.  Whisper-dependent
behavior is exercised via ``_transcribe_chunk`` mocks and isolated unit
fixtures, consistent with the project's "behavior, not implementation"
testing guidance.
"""

from __future__ import annotations

from itertools import pairwise
import os
import shutil
import subprocess
import sys
from typing import Any

import pytest


# Add parent directory to path so this test file is importable both via
# pytest collection and as a standalone script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from mcp_video.ai_engine.transcribe_longform import (
    LongformChunk,
    LongformSegment,
    LongformTranscribePlan,
    LongformTranscribeResult,
    LongformWord,
    _merge_chunk,
    _format_chunk_result,
    _segment_confidence,
    _validate_chunk_seconds,
    _validate_overlap_seconds,
    _word_probability,
    plan_longform_transcription,
    transcribe_longform,
)

from mcp_video.ai_engine.transcribe import (
    _validate_transcribe_duration,
)
from mcp_video.errors import MCPVideoError
from mcp_video.limits import (
    LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    MAX_AI_TRANSCRIBE_DURATION,
    MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNKS,
    MAX_VIDEO_DURATION,
    MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
)


def test_format_chunk_result_preserves_whisper_word_timings() -> None:
    result = _format_chunk_result(
        {
            "text": "hello world",
            "language": "en",
            "segments": [
                {
                    "id": 0,
                    "start": 1.0,
                    "end": 2.0,
                    "text": "hello world",
                    "avg_logprob": -0.25,
                    "words": [
                        {"word": "hello", "start": 1.0, "end": 1.4, "probability": 0.9},
                        {"word": "world", "start": 1.5, "end": 2.0, "probability": 0.8},
                    ],
                }
            ],
        }
    )
    assert result["segments"][0]["words"][1] == {
        "word": "world",
        "start": 1.5,
        "end": 2.0,
        "probability": 0.8,
    }


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def has_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


requires_ffmpeg = pytest.mark.skipif(not has_ffmpeg(), reason="FFmpeg not installed")
requires_ffprobe = pytest.mark.skipif(not has_ffprobe(), reason="FFprobe not installed")


def _make_probe_stub(monkeypatch, duration: float) -> None:
    """Replace ``_get_video_duration`` in both the transcribe and longform
    modules with a constant return — these tests do not need real media."""

    def _stub(_path: str, *, pass_fds: tuple[int, ...] = ()) -> float:
        return float(duration)

    monkeypatch.setattr(
        "mcp_video.ai_engine.transcribe_longform._get_video_duration",
        _stub,
    )
    monkeypatch.setattr(
        "mcp_video.ai_engine.transcribe._get_video_duration",
        _stub,
    )


def _make_input_path_stub(monkeypatch, real_path: str | None = None) -> None:
    """Replace ``_validate_input_path`` so the longform plan/merge tests don't
    need real files on disk."""

    def _stub(path: str) -> str:
        return path if real_path is None else real_path

    monkeypatch.setattr(
        "mcp_video.ai_engine.transcribe_longform._validate_input_path",
        _stub,
    )


def _stub_scene_anchors(monkeypatch, value: list[float] | None) -> None:
    """Replace ``_scene_anchors`` so planning is deterministic in tests."""

    if value is None:
        # Force a fixed plan even when scene_aware=True is requested.
        monkeypatch.setattr(
            "mcp_video.ai_engine.transcribe_longform._scene_anchors",
            lambda *_a, **_kw: [],
        )
    else:
        monkeypatch.setattr(
            "mcp_video.ai_engine.transcribe_longform._scene_anchors",
            lambda *_a, **_kw: list(value),
        )


def _stub_transcribe_chunk(monkeypatch, results: list[dict[str, Any]]) -> None:
    """Replace ``_transcribe_chunk`` so the merger can be exercised without
    Whisper.  ``results[i]`` is returned for ``plan.chunks[i]`` in order."""
    queue = list(results)
    state = {"i": 0}

    def _fake(video: str, chunk, **_kwargs) -> dict[str, Any]:
        idx = state["i"]
        state["i"] += 1
        if idx >= len(queue):
            return {"transcript": "", "segments": [], "language": "en"}
        return queue[idx]

    monkeypatch.setattr(
        "mcp_video.ai_engine.transcribe_longform._transcribe_chunk",
        _fake,
    )


# ---------------------------------------------------------------------------
# Plan-size / coverage / cap tests (no media fixture required)
# ---------------------------------------------------------------------------


def test_plan_caps_at_max_video_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Planning 14400s (4h) of media returns a valid plan without probe."""
    _make_probe_stub(monkeypatch, MAX_VIDEO_DURATION)
    _make_input_path_stub(monkeypatch)

    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
        overlap_seconds=LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
        scene_aware=False,
    )

    assert isinstance(plan, LongformTranscribePlan)
    assert plan.duration == float(MAX_VIDEO_DURATION)
    # 14400s / 1500s = 9.6 -> 10 chunks minimum at fixed 1500s window.
    assert len(plan.chunks) >= 10
    # Every chunk is a strict model.
    for chunk in plan.chunks:
        assert isinstance(chunk, LongformChunk)


def test_plan_covers_full_duration_without_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coverage rule: the union of chunks spans [0, duration] with overlap,
    not gaps."""
    duration = 3600.0
    _make_probe_stub(monkeypatch, duration)
    _make_input_path_stub(monkeypatch)
    _stub_scene_anchors(monkeypatch, [])

    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=10,
        scene_aware=False,
    )

    assert plan.chunks[0].start == 0.0
    assert plan.chunks[-1].end == duration
    # Each subsequent chunk starts at most ``overlap_seconds`` after the
    # previous chunk's *end* (i.e. there is no positive gap).
    for prev, cur in zip(plan.chunks, plan.chunks[1:], strict=False):
        assert cur.start <= prev.end, "gap between chunks"
        # Overlap tail is non-negative but never exceeds chunk_seconds.
        assert prev.end - cur.start >= 0
        assert prev.end - cur.start <= 10


def test_plan_respects_chunk_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """No individual chunk ever exceeds the cap, including the overlap tail."""
    duration = 7200.0  # 2h
    _make_probe_stub(monkeypatch, duration)
    _make_input_path_stub(monkeypatch)
    _stub_scene_anchors(monkeypatch, [])

    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
        overlap_seconds=LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
        scene_aware=False,
    )

    for chunk in plan.chunks:
        assert chunk.duration <= MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS, (
            f"chunk {chunk.index} duration {chunk.duration} exceeds cap"
        )


def test_plan_chunk_count_within_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """For the 4-hour cap the chunk count stays below MAX_LONGFORM_TRANSCRIBE_CHUNKS."""
    _make_probe_stub(monkeypatch, MAX_VIDEO_DURATION)
    _make_input_path_stub(monkeypatch)

    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=300,
        overlap_seconds=15,
        scene_aware=False,
    )
    # 14400 / (300-15) ≈ 50 chunks; well below 64.
    assert len(plan.chunks) <= MAX_LONGFORM_TRANSCRIBE_CHUNKS


def test_plan_rejects_too_large_chunk_seconds() -> None:
    """Validates the cap without needing a media file."""
    with pytest.raises(MCPVideoError) as exc:
        _validate_chunk_seconds(MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS + 1)
    assert exc.value.code == "chunk_too_large"


def test_plan_rejects_too_small_chunk_seconds() -> None:
    """Validates the floor without needing a media file."""
    with pytest.raises(MCPVideoError) as exc:
        _validate_chunk_seconds(MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS - 1)
    assert exc.value.code == "chunk_too_small"


def test_plan_rejects_overlap_equal_to_chunk_seconds() -> None:
    with pytest.raises(MCPVideoError) as exc:
        _validate_overlap_seconds(600, 600)
    assert exc.value.code == "invalid_overlap"


def test_plan_rejects_negative_overlap() -> None:
    with pytest.raises(MCPVideoError) as exc:
        _validate_overlap_seconds(-1, 600)
    assert exc.value.code == "invalid_parameter"


def test_plan_rejects_zero_or_negative_chunk_seconds() -> None:
    with pytest.raises(MCPVideoError) as exc:
        _validate_chunk_seconds(0)
    assert exc.value.code == "invalid_parameter"


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


def test_plan_is_deterministic_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two plans over the same input are byte-identical."""
    _make_probe_stub(monkeypatch, 4500.0)
    _make_input_path_stub(monkeypatch)
    _stub_scene_anchors(monkeypatch, [])

    a = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=900,
        overlap_seconds=15,
        scene_aware=False,
    )
    b = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=900,
        overlap_seconds=15,
        scene_aware=False,
    )
    assert a.model_dump() == b.model_dump()


def test_plan_is_json_serializable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict model round-trips through JSON so the orchestrator can persist."""
    import json

    _make_probe_stub(monkeypatch, 1500.0)
    _make_input_path_stub(monkeypatch)
    _stub_scene_anchors(monkeypatch, [])

    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=10,
        scene_aware=False,
    )
    raw = plan.model_dump_json()
    reloaded = LongformTranscribePlan.model_validate_json(raw)
    assert reloaded.model_dump() == plan.model_dump()
    # JSON itself must be parseable.
    json.loads(raw)


# ---------------------------------------------------------------------------
# Scene-aware chunking
# ---------------------------------------------------------------------------


def test_scene_aware_falls_back_to_fixed_when_no_anchors(monkeypatch: pytest.MonkeyPatch) -> None:
    """No scene cuts -> fixed plan (anchor="fixed")."""
    _make_probe_stub(monkeypatch, 1800.0)
    _make_input_path_stub(monkeypatch)
    _stub_scene_anchors(monkeypatch, [])

    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=10,
        scene_aware=True,
    )
    assert all(c.anchor == "fixed" for c in plan.chunks)


def test_scene_aware_uses_scene_anchors_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """With scene anchors present, the planner uses anchor-aware chunks."""
    _make_probe_stub(monkeypatch, 2400.0)
    _make_input_path_stub(monkeypatch)
    _stub_scene_anchors(monkeypatch, [400.0, 1200.0])

    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=10,
        scene_aware=True,
    )
    assert any(c.anchor == "scene" for c in plan.chunks)


# ---------------------------------------------------------------------------
# Merger tests (monotonic + dedup)
# ---------------------------------------------------------------------------


def _make_chunk(index: int, start: float, end: float) -> LongformChunk:
    return LongformChunk(
        index=index,
        start=start,
        end=end,
        duration=end - start,
        anchor="fixed",
    )


def test_merge_produces_monotonic_global_timestamps() -> None:
    """Merger remaps per-chunk local timestamps by chunk.start and yields a
    monotonically non-decreasing word timeline."""
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []

    chunk_a = _make_chunk(0, 0.0, 10.0)
    chunk_b = _make_chunk(1, 5.0, 15.0)  # overlap window [5, 10)

    fake_a = {
        "transcript": "alpha beta gamma",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.5,
                "end": 1.5,
                "text": "alpha beta",
                "tokens": [],
                "words": [
                    {"word": "alpha", "start": 0.5, "end": 1.0},
                    {"word": "beta", "start": 1.0, "end": 1.5},
                ],
            },
            {
                "id": 1,
                "start": 1.5,
                "end": 2.5,
                "text": "gamma",
                "tokens": [],
                "words": [
                    {"word": "gamma", "start": 1.5, "end": 2.5},
                ],
            },
        ],
    }
    fake_b = {
        "transcript": "beta gamma delta",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,  # local to chunk_b
                "end": 2.5,
                "text": "beta gamma delta",
                "tokens": [],
                "words": [
                    # The "beta" and "gamma" here are duplicates from chunk A's tail.
                    {"word": "beta", "start": 0.5, "end": 1.0},
                    {"word": "gamma", "start": 1.5, "end": 2.5},
                    {"word": "delta", "start": 4.0, "end": 4.5},
                ],
            },
        ],
    }
    _merge_chunk(words, segments, fake_a, chunk_a, overlap_seconds=5, prev_chunk_end=None)
    _merge_chunk(words, segments, fake_b, chunk_b, overlap_seconds=5, prev_chunk_end=chunk_a.end)

    # Monotonic enforcement: each subsequent word's start >= previous word's start.
    for prev, cur in pairwise(words):
        assert cur.start >= prev.start, f"non-monotonic: {cur.start} after {prev.start}"


def test_merge_dedups_overlap_tail_words() -> None:
    """Words observed in the overlap tail whose text matches a word the
    previous chunk emitted inside the same overlap window are dropped."""
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []

    chunk_a = _make_chunk(0, 0.0, 10.0)
    chunk_b = _make_chunk(1, 5.0, 15.0)

    # chunk A emits "world" inside its overlap tail [5, 10) so dedup can match it.
    fake_a = {
        "transcript": "hello world",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 10.0,
                "text": "hello world",
                "tokens": [],
                "words": [
                    {"word": "hello", "start": 0.0, "end": 1.0},
                    {"word": "world", "start": 8.0, "end": 9.0},
                ],
            }
        ],
    }
    # chunk B re-emits the same "world" inside the overlap region [5, 10).
    fake_b = {
        "transcript": "world again",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "world again",
                "tokens": [],
                "words": [
                    # local 3.0 -> global 8.0 (in overlap window [5, 10))
                    {"word": "world", "start": 3.0, "end": 4.0},
                    {"word": "again", "start": 4.5, "end": 5.0},
                ],
            }
        ],
    }

    _merge_chunk(words, segments, fake_a, chunk_a, overlap_seconds=5, prev_chunk_end=None)
    before = [w.word for w in words]
    _merge_chunk(words, segments, fake_b, chunk_b, overlap_seconds=5, prev_chunk_end=chunk_a.end)
    after = [w.word for w in words]

    assert before[-1] == "world"
    # The duplicate "world" should NOT have been appended in chunk B.
    assert after[len(before) :] == ["again"]


def test_merge_keeps_unique_overlap_tail_words() -> None:
    """Words in the overlap tail that don't match the previous chunk's last
    word are kept (overlap region is content-rich, not a pure duplicate)."""
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []

    chunk_a = _make_chunk(0, 0.0, 10.0)
    chunk_b = _make_chunk(1, 5.0, 15.0)

    fake_a = {
        "transcript": "alpha",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "alpha",
                "tokens": [],
                "words": [{"word": "alpha", "start": 0.0, "end": 1.0}],
            }
        ],
    }
    fake_b = {
        "transcript": "beta",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "beta",
                "tokens": [],
                "words": [{"word": "beta", "start": 0.5, "end": 1.0}],
            }
        ],
    }
    _merge_chunk(words, segments, fake_a, chunk_a, overlap_seconds=5, prev_chunk_end=None)
    _merge_chunk(words, segments, fake_b, chunk_b, overlap_seconds=5, prev_chunk_end=chunk_a.end)

    words_text = [w.word for w in words]
    assert "beta" in words_text
    assert words[-1].start == 0.5 + 5.0  # local 0.5 + chunk.start 5.0


def test_merge_handles_chunk_without_word_timestamps() -> None:
    """A chunk whose segments lack word timestamps still contributes a
    segment to the merged timeline."""
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []

    chunk = _make_chunk(0, 0.0, 5.0)
    fake = {
        "transcript": "no word timestamps",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "no word timestamps",
                "tokens": [],
            }
        ],
    }
    _merge_chunk(words, segments, fake, chunk, overlap_seconds=5, prev_chunk_end=None)
    assert segments
    assert segments[0].start == 0.0
    assert segments[0].end == 5.0
    assert words == []


# ---------------------------------------------------------------------------
# Orchestrator (transcribe_longform) end-to-end with mocked chunking
# ---------------------------------------------------------------------------


def test_transcribe_longform_merges_results_without_whisper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end orchestrator with per-chunk mocking produces a strict
    LongformTranscribeResult with merged words."""
    _make_probe_stub(monkeypatch, 1800.0)
    _make_input_path_stub(monkeypatch)
    _stub_scene_anchors(monkeypatch, [])

    chunk_results = [
        {
            "transcript": "alpha beta",
            "language": "en",
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 5.0,
                    "text": "alpha beta",
                    "tokens": [],
                    "words": [
                        {"word": "alpha", "start": 0.0, "end": 1.0},
                        {"word": "beta", "start": 1.0, "end": 2.0},
                    ],
                }
            ],
        },
        {
            "transcript": "gamma delta",
            "language": "en",
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 5.0,
                    "text": "gamma delta",
                    "tokens": [],
                    "words": [
                        {"word": "gamma", "start": 0.0, "end": 1.0},
                        {"word": "delta", "start": 1.0, "end": 2.0},
                    ],
                }
            ],
        },
    ]
    _stub_transcribe_chunk(monkeypatch, chunk_results)

    result = transcribe_longform(
        "/tmp/_any.mp4",
        model="base",
        chunk_seconds=600,
        overlap_seconds=0,
        scene_aware=False,
    )

    assert isinstance(result, LongformTranscribeResult)
    assert result.model == "base"
    assert result.language == "en"
    assert result.chunk_count == len(result.plan.chunks)
    assert len(result.words) == 4
    assert result.transcript.count("alpha") == 1
    assert result.transcript.count("gamma") == 1


def test_transcribe_longform_rejects_invalid_whisper_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad whisper model fails closed before any chunking happens."""
    _make_probe_stub(monkeypatch, 100.0)
    _make_input_path_stub(monkeypatch)

    with pytest.raises(MCPVideoError) as exc:
        transcribe_longform(
            "/tmp/_any.mp4",
            model="not-a-real-model",
            chunk_seconds=600,
            overlap_seconds=10,
            scene_aware=False,
        )
    assert exc.value.code == "invalid_parameter"


# ---------------------------------------------------------------------------
# Legacy ai_transcribe >3600s rejection must remain
# ---------------------------------------------------------------------------


def test_legacy_ai_transcribe_still_rejects_over_max_ai_transcribe_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Ordinary ai_transcribe rejects >MAX_AI_TRANSCRIBE_DURATION via
    _validate_transcribe_duration.  The longform path explicitly does not.

    Here we verify the legacy rejection survives: a stub probe that returns
    >MAX_AI_TRANSCRIBE_DURATION must trigger duration_too_long, and the
    longform plan must still succeed for the same probed duration.
    """
    over_legacy = float(MAX_AI_TRANSCRIBE_DURATION) + 1.0
    _make_probe_stub(monkeypatch, over_legacy)

    real_input = str(tmp_path / "stub.mp4")
    Path_ = _get_path_class()
    Path_(real_input).write_bytes(b"\x00")

    # 1) Legacy rejection: _validate_transcribe_duration fails closed.
    with pytest.raises(MCPVideoError) as exc:
        _validate_transcribe_duration(real_input)
    assert exc.value.code == "duration_too_long"

    # 2) Longform path: planning accepts the same probed duration, but
    # bypasses the legacy check.
    _make_input_path_stub(monkeypatch, real_input)
    _stub_scene_anchors(monkeypatch, [])

    plan = plan_longform_transcription(
        real_input,
        chunk_seconds=600,
        overlap_seconds=15,
        scene_aware=False,
    )
    assert plan.duration == over_legacy
    assert len(plan.chunks) >= 1


def _get_path_class():
    from pathlib import Path

    return Path


# ---------------------------------------------------------------------------
# Live (small, deterministic) end-to-end integration test using FFmpeg
# ---------------------------------------------------------------------------


@requires_ffmpeg
@requires_ffprobe
def test_longform_path_works_on_short_real_video(tmp_path) -> None:
    """Tiny FFmpeg-generated fixture (<=5s) is exercised through the actual
    ffmpeg/extract path.  We do NOT require whisper installed — the test
    exercises only the planner and audio-segment extractor by patching the
    whisper call inside _transcribe_chunk."""
    import shutil as _shutil

    if _shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")

    video_path = str(tmp_path / "stub.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=320x240:duration=3:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-shortest",
            video_path,
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if not os.path.isfile(video_path):
        pytest.skip("could not generate stub video")

    plan = plan_longform_transcription(
        video_path,
        chunk_seconds=600,
        overlap_seconds=15,
        scene_aware=False,
    )
    assert plan.duration > 0
    # A 3s clip fits in a single chunk.
    assert len(plan.chunks) == 1
    assert plan.chunks[0].start == 0.0


# ---------------------------------------------------------------------------
# Invalid plan guard
# ---------------------------------------------------------------------------


def test_transcribe_longform_rejects_empty_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the caller hands us an empty plan, refuse rather than silently no-op."""
    _make_probe_stub(monkeypatch, 60.0)
    _make_input_path_stub(monkeypatch)

    empty_plan = LongformTranscribePlan(
        video_path="/tmp/_any.mp4",
        duration=60.0,
        chunk_seconds=600,
        overlap_seconds=10,
        chunks=[],
    )
    with pytest.raises(MCPVideoError) as exc:
        transcribe_longform(
            "/tmp/_any.mp4",
            model="base",
            chunk_seconds=600,
            overlap_seconds=10,
            scene_aware=False,
            plan=empty_plan,
        )
    assert exc.value.code == "invalid_plan"


# ---------------------------------------------------------------------------
# Path validation guard
# ---------------------------------------------------------------------------


def test_longform_path_rejects_null_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same null-byte path rejection that ordinary ai_transcribe uses
    is honored by the longform plan path too."""
    _make_probe_stub(monkeypatch, 60.0)
    # Intentionally do NOT stub _validate_input_path here — it must raise
    # InputFileError before the longform duration probe runs.

    def _raising_probe(_path: str, *, pass_fds: tuple[int, ...] = ()) -> float:
        raise AssertionError("duration probe must not run for null-byte path")

    monkeypatch.setattr(
        "mcp_video.ai_engine.transcribe_longform._validate_input_path",
        _raising_probe,
    )

    with pytest.raises(MCPVideoError):
        plan_longform_transcription(
            "/tmp/bad\x00.mp4",
            chunk_seconds=600,
            overlap_seconds=10,
            scene_aware=False,
        )


# ---------------------------------------------------------------------------
# Confidence conversion (GLM A8)
# ---------------------------------------------------------------------------


def test_segment_confidence_translates_avg_logprob_via_exp() -> None:
    """``_segment_confidence`` must use ``exp(avg_logprob)``.

    Whisper emits non-positive log-likelihoods; the correct probability is
    ``exp(avg_logprob)``. The previous implementation used ``1 + avg_logprob``
    which produced nonsense values (e.g. ``avg_logprob=-0.5`` -> ``0.5``).
    """
    assert _segment_confidence({"avg_logprob": 0.0}) == 1.0
    import math as _math

    assert _segment_confidence({"avg_logprob": -0.5}) == _math.exp(-0.5)
    assert _segment_confidence({"avg_logprob": -1.0}) == _math.exp(-1.0)
    # No logprob at all -> ``None`` (NEVER 1.0; that would mask missing signal).
    assert _segment_confidence({}) is None
    assert _segment_confidence({"avg_logprob": None}) is None
    assert _segment_confidence({"avg_logprob": "not-a-number"}) is None


def test_word_probability_uses_exp_fallback_for_legacy_whisper() -> None:
    """``_word_probability`` must use the literal ``probability`` field first,
    fall back to ``exp(avg_logprob)`` when only the legacy log-likelihood is
    present, and return ``None`` when neither is available (NEVER 1.0)."""
    import math as _math

    assert _word_probability({"probability": 0.42}) == 0.42
    assert _word_probability({"avg_logprob": -0.5}) == _math.exp(-0.5)
    # Out-of-range probability is rejected; falls back to logprob.
    assert _word_probability({"probability": 1.7, "avg_logprob": -1.0}) == _math.exp(-1.0)
    # No signal at all -> ``None``.
    assert _word_probability({}) is None
    assert _word_probability({"probability": "oops"}) is None


def test_longform_segment_preserves_avg_logprob_from_whisper() -> None:
    """The merger must round-trip ``avg_logprob`` so the orchestrator can
    compute truthful confidence instead of defaulting to 1.0."""
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []

    chunk = _make_chunk(0, 0.0, 5.0)
    fake = {
        "transcript": "hello world",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "hello world",
                "avg_logprob": -0.5,
                "no_speech_prob": 0.01,
                "words": [
                    {"word": "hello", "start": 0.0, "end": 1.0, "probability": 0.9},
                    {"word": "world", "start": 1.5, "end": 2.5, "avg_logprob": -0.2},
                ],
            }
        ],
    }
    _merge_chunk(words, segments, fake, chunk, overlap_seconds=5, prev_chunk_end=None)

    assert segments
    assert segments[0].avg_logprob == -0.5
    assert segments[0].no_speech_prob == 0.01
    # Per-word probabilities are preserved through the merger.
    assert words[0].probability == 0.9
    import math as _math

    assert words[1].probability == _math.exp(-0.2)


def test_longform_segment_omits_avg_logprob_when_whisper_did_not_emit_one() -> None:
    """When the upstream Whisper segment lacks ``avg_logprob`` the strict
    segment's field must remain ``None`` (NEVER 1.0); downstream consumers
    then leave ``TranscriptSegment.confidence`` as ``None``."""
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []

    chunk = _make_chunk(0, 0.0, 5.0)
    fake = {
        "transcript": "silent",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "silent",
            }
        ],
    }
    _merge_chunk(words, segments, fake, chunk, overlap_seconds=5, prev_chunk_end=None)
    assert segments[0].avg_logprob is None
    assert segments[0].no_speech_prob is None


def test_merge_records_per_word_probability() -> None:
    """Per-word ``probability`` from Whisper must reach ``LongformWord``.

    A2 fix: the merger was dropping the per-token probability before this
    change; we now record it on ``LongformWord.probability`` so the
    orchestrator can thread it through to the caption grouper.
    """
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []
    chunk = _make_chunk(0, 0.0, 10.0)
    fake = {
        "transcript": "alpha beta",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "alpha beta",
                "words": [
                    {"word": "alpha", "start": 0.0, "end": 1.0, "probability": 0.7},
                    {"word": "beta", "start": 1.0, "end": 2.0, "probability": 0.3},
                ],
            }
        ],
    }
    _merge_chunk(words, segments, fake, chunk, overlap_seconds=5, prev_chunk_end=None)
    assert [w.probability for w in words] == [0.7, 0.3]


def test_merge_keeps_word_probability_none_when_unavailable() -> None:
    """Words without probability information must surface as ``None``,
    not ``1.0`` — the orchestrator relies on this for low-confidence flagging.
    """
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []
    chunk = _make_chunk(0, 0.0, 5.0)
    fake = {
        "transcript": "alpha",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "text": "alpha",
                "words": [{"word": "alpha", "start": 0.0, "end": 1.0}],
            }
        ],
    }
    _merge_chunk(words, segments, fake, chunk, overlap_seconds=5, prev_chunk_end=None)
    assert words
    assert words[0].probability is None


# ---------------------------------------------------------------------------
# GLM L1 — overlap monotonic snapping must preserve positive word width
# ---------------------------------------------------------------------------


def test_transcribe_longform_snap_preserves_positive_word_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When two consecutive words overlap (cur.start < prev.end) the monotonic
    snap must preserve a strictly-positive word width.

    Without the minimum-width floor the snap would set ``start = prev.end``
    and ``end = max(prev.end, cur.end)`` — producing a zero-width word when
    the slipped word's original ``end`` was already <= ``prev.end``. The
    orchestrator then leaks a zero-width ``LongformWord`` to downstream
    consumers who depend on ``end > start``.
    """
    _make_probe_stub(monkeypatch, 60.0)
    _make_input_path_stub(monkeypatch, "/tmp/_any.mp4")
    _stub_scene_anchors(monkeypatch, [])

    # Word "alpha" ends at 1.0; word "beta" starts at 0.5 with end 0.7
    # (entirely inside "alpha"). The snap must push "beta" to start at
    # exactly 1.0 and lift its end past that point by at least 1ms so the
    # final ``LongformWord`` keeps a strictly-positive width.
    chunk_results = [
        {
            "transcript": "alpha beta",
            "language": "en",
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "alpha",
                    "tokens": [],
                    "words": [{"word": "alpha", "start": 0.0, "end": 1.0}],
                },
                {
                    "id": 1,
                    "start": 0.5,
                    "end": 0.7,
                    "text": "beta",
                    "tokens": [],
                    "words": [{"word": "beta", "start": 0.5, "end": 0.7}],
                },
            ],
        }
    ]
    _stub_transcribe_chunk(monkeypatch, chunk_results)

    result = transcribe_longform(
        "/tmp/_any.mp4",
        model="base",
        chunk_seconds=600,
        overlap_seconds=0,
        scene_aware=False,
    )

    assert len(result.words) == 2
    alpha, beta = result.words
    assert alpha.end == 1.0
    # Monotonic snap forward; ``beta.start`` must not regress.
    assert beta.start >= alpha.end
    # The snapped ``beta`` must retain a strictly positive width.
    assert beta.end > beta.start, f"snapped word has zero or negative width: start={beta.start}, end={beta.end}"
    assert beta.end - beta.start >= 0.001 - 1e-9, f"snapped word width below 1ms floor: {beta.end - beta.start}s"
