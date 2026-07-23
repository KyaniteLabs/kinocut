from __future__ import annotations

from typing import Any

import pytest

from kinocut.ai_engine._longform_models import LongformTranscribePlan
from kinocut.ai_engine._longform_planning import (
    _build_plan,
    _scene_anchors,
    plan_longform_transcription,
)
from kinocut.errors import MCPVideoError
from kinocut.limits import (
    LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNKS,
    MAX_VIDEO_DURATION,
    MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
)

_PLANNING = "kinocut.ai_engine._longform_planning"


def _stub_probe(monkeypatch, duration: float) -> None:
    monkeypatch.setattr(f"{_PLANNING}._get_video_duration", lambda _path: float(duration))
    monkeypatch.setattr(f"{_PLANNING}._validate_longform_path", lambda video: video)


def _stub_scene(monkeypatch, anchors: list[float] | None) -> None:
    if anchors is None:

        def _boom(*_a: Any, **_kw: Any) -> list[float]:
            raise RuntimeError("scene detector unavailable")

        monkeypatch.setattr(f"{_PLANNING}.ai_scene_detect", _boom)
        return
    monkeypatch.setattr(f"{_PLANNING}._scene_anchors", lambda *_a, **_kw: list(anchors))


@pytest.mark.parametrize(
    "duration,chunk_seconds,overlap_seconds",
    [
        (MAX_VIDEO_DURATION, MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS, LONGFORM_TRANSCRIBE_OVERLAP_SECONDS),
        (3600.0, 600, 10),
        (9000.0, 1200, 15),
    ],
)
def test_plan_caps_at_max_video_duration(monkeypatch, duration, chunk_seconds, overlap_seconds) -> None:
    _stub_probe(monkeypatch, duration)
    _stub_scene(monkeypatch, [])
    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
        scene_aware=False,
    )
    assert isinstance(plan, LongformTranscribePlan)
    assert plan.duration == float(duration)
    assert plan.chunks[0].start == 0.0
    assert plan.chunks[-1].end == float(duration)
    assert plan.chunks


@pytest.mark.parametrize(
    "duration,chunk_seconds,overlap_seconds",
    [(3600.0, 600, 10), (7200.0, 1500, 15), (1200.0, 600, 30), (1800.0, 800, 25)],
)
def test_plan_covers_full_duration_with_overlap_no_gaps(monkeypatch, duration, chunk_seconds, overlap_seconds) -> None:
    _stub_probe(monkeypatch, duration)
    _stub_scene(monkeypatch, [])
    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
        scene_aware=False,
    )
    prev_end = 0.0
    for chunk in plan.chunks:
        assert chunk.end > chunk.start
        assert chunk.duration <= chunk_seconds + 1e-9
        if prev_end > 0:
            assert chunk.start <= prev_end, "gap between chunks"
            assert prev_end - chunk.start <= float(overlap_seconds) + 1e-9
        prev_end = chunk.end
    assert prev_end == pytest.approx(float(duration))


def test_plan_chunk_count_within_bound(monkeypatch) -> None:
    _stub_probe(monkeypatch, float(MAX_VIDEO_DURATION))
    _stub_scene(monkeypatch, [])
    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=300,
        overlap_seconds=15,
        scene_aware=False,
    )
    assert 1 <= len(plan.chunks) <= MAX_LONGFORM_TRANSCRIBE_CHUNKS


@pytest.mark.parametrize(
    "duration,chunk_seconds,overlap_seconds",
    [(4500.0, 900, 15), (1800.0, 600, 10), (3000.0, 1200, 30)],
)
def test_plan_is_deterministic_and_json_stable(monkeypatch, duration, chunk_seconds, overlap_seconds) -> None:
    _stub_probe(monkeypatch, duration)
    _stub_scene(monkeypatch, [])
    kwargs = dict(chunk_seconds=chunk_seconds, overlap_seconds=overlap_seconds, scene_aware=False)
    first = plan_longform_transcription("/tmp/_any.mp4", **kwargs)
    second = plan_longform_transcription("/tmp/_any.mp4", **kwargs)
    assert first.model_dump() == second.model_dump()
    assert LongformTranscribePlan.model_validate_json(first.model_dump_json()) == first


def test_fixed_fallback_when_no_scene_anchors(monkeypatch) -> None:
    _stub_probe(monkeypatch, 1800.0)
    _stub_scene(monkeypatch, [])
    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=10,
        scene_aware=True,
    )
    assert all(c.anchor == "fixed" for c in plan.chunks)
    assert plan.chunks[0].start == 0.0
    assert plan.chunks[-1].end == 1800.0


def test_scene_anchors_preserved_without_gaps(monkeypatch) -> None:
    """Anchors relabel chunks but never relocate them past the next step."""
    _stub_probe(monkeypatch, 2400.0)
    _stub_scene(monkeypatch, [400.0, 1200.0])
    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=10,
        scene_aware=True,
    )
    assert any(c.anchor == "scene" for c in plan.chunks)
    assert plan.chunks[0].start == 0.0
    assert plan.chunks[-1].end == 2400.0
    for prev, cur in zip(plan.chunks, plan.chunks[1:], strict=False):
        assert cur.start <= prev.end
    for chunk in plan.chunks:
        assert chunk.duration <= 600 + 1e-9


def test_scene_anchors_filter_to_body(monkeypatch) -> None:
    """Out-of-range anchors are dropped; only body anchors participate."""
    monkeypatch.setattr(f"{_PLANNING}._get_video_duration", lambda _p: 1000.0)
    monkeypatch.setattr(f"{_PLANNING}._validate_longform_path", lambda v: v)
    monkeypatch.setattr(
        f"{_PLANNING}.ai_scene_detect",
        lambda *_a, **_kw: [
            {"timestamp": 1.0},
            {"timestamp": 10.0},
            {"timestamp": 500.0},
            {"timestamp": 900.0},
            {"timestamp": None},
        ],
    )
    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=200,
        scene_aware=True,
    )
    assert plan.chunks[0].start == 0.0
    assert plan.chunks[-1].end == 1000.0


def test_scene_detector_exceptions_degrade_to_fixed(monkeypatch) -> None:
    """Scene seam blowing up must yield a fixed-only plan (no leak)."""
    _stub_probe(monkeypatch, 1800.0)
    _stub_scene(monkeypatch, None)
    plan = plan_longform_transcription(
        "/tmp/_any.mp4",
        chunk_seconds=600,
        overlap_seconds=10,
        scene_aware=True,
    )
    assert all(c.anchor == "fixed" for c in plan.chunks)
    assert plan.chunks[0].start == 0.0
    assert plan.chunks[-1].end == 1800.0


def test_scene_boundary_rejects_overlap_that_would_stall_cursor() -> None:
    with pytest.raises(MCPVideoError) as exc:
        _build_plan(
            "/tmp/_any.mp4",
            duration=1200.0,
            chunk_seconds=600,
            overlap_seconds=300,
            anchors=[300.0],
        )

    assert exc.value.code == "invalid_overlap"
    assert "reduce overlap_seconds or disable scene-aware planning" in str(exc.value)


def test_build_plan_rejects_too_many_chunks() -> None:
    with pytest.raises(MCPVideoError) as exc:
        _build_plan(
            "/tmp/_any.mp4",
            duration=float(MAX_VIDEO_DURATION),
            chunk_seconds=MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
            overlap_seconds=1,
            anchors=None,
        )
    assert exc.value.code == "too_many_chunks"


def test_scene_anchors_returns_empty_when_detector_fails(monkeypatch) -> None:
    def _boom(*_a: Any, **_kw: Any) -> list[float]:
        raise RuntimeError("ffmpeg missing")

    monkeypatch.setattr(f"{_PLANNING}.ai_scene_detect", _boom)
    assert _scene_anchors("/tmp/x.mp4", 1800.0, 600, 10) == []
