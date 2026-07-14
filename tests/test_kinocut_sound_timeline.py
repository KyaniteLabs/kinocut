"""RED-first tests for the ``kinocut_sound`` timeline contract.

The timeline is the authoritative duration source for an episode: every cue has
a strictly positive duration, cue ids are bounded, cue kinds are closed, cues
are ordered and non-overlapping, and the timeline total defines the required
output duration including declared tail. A shortest-stream mix is structurally
prohibited.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.timeline import Cue, CueKind, Timeline


def _cue(cue_id: str = "cue_001", start: float = 0.0, duration: float = 1.5, **kw) -> Cue:
    payload = {
        "cue_id": cue_id,
        "start_seconds": start,
        "duration_seconds": duration,
        "kind": CueKind.LINE,
        "source_ref": "lines/line_001.json",
    }
    payload.update(kw)
    return Cue(**payload)


def test_cue_kinds_are_closed():
    assert {k.value for k in CueKind} == {
        "line",
        "silence",
        "foley",
        "bed",
        "chapter_marker",
    }


def test_cue_requires_strictly_positive_duration_and_nonneg_start():
    _cue()
    for bad_duration in (0.0, -0.1):
        with pytest.raises(ValidationError):
            _cue(duration=bad_duration)
    for bad_start in (-0.001,):
        with pytest.raises(ValidationError):
            _cue(start=bad_start)


def test_cue_rejects_unbounded_ids_and_unsafe_sources():
    for bad_id in ("with space", "../traversal", "1lead", ""):
        with pytest.raises(ValidationError):
            _cue(cue_id=bad_id)
    for bad_ref in ("/abs/path", "~/home", "https://host/x"):
        with pytest.raises(ValidationError):
            _cue(source_ref=bad_ref)


def test_cue_rejects_overlapping_absolute_window_via_out_point():
    with pytest.raises(ValidationError):
        _cue(in_point_seconds=1.0, out_point_seconds=0.5)


def test_timeline_total_is_authoritative_and_includes_tail():
    timeline = Timeline(
        cues=(
            _cue(cue_id="a", start=0.0, duration=2.0),
            _cue(cue_id="b", start=2.0, duration=3.0),
        ),
        tail_seconds=1.0,
    )
    assert timeline.total_seconds == 6.0
    assert timeline.authoritative_duration_seconds == 6.0


def test_timeline_rejects_overlapping_or_unsorted_cues():
    with pytest.raises(ValidationError):
        Timeline(
            cues=(
                _cue(cue_id="a", start=0.0, duration=2.0),
                _cue(cue_id="b", start=1.0, duration=1.0),  # overlap
            ),
        )
    with pytest.raises(ValidationError):
        Timeline(
            cues=(
                _cue(cue_id="a", start=2.0, duration=1.0),
                _cue(cue_id="b", start=0.0, duration=1.0),  # unsorted
            ),
        )


def test_timeline_rejects_duplicate_cue_ids():
    with pytest.raises(ValidationError):
        Timeline(
            cues=(
                _cue(cue_id="dup", start=0.0, duration=1.0),
                _cue(cue_id="dup", start=1.0, duration=1.0),
            ),
        )


def test_timeline_rejects_zero_cues_when_required():
    with pytest.raises(ValidationError):
        Timeline(cues=(), require_at_least_one_cue=True)
    Timeline(cues=(), require_at_least_one_cue=False)


def test_timeline_prohibits_shortest_stream_mix_by_rejecting_gaps_above_tolerance():
    # An unexplained gap larger than the configured tolerance is a shortest-stream
    # attempt and is rejected. A small gap within tolerance is allowed.
    Timeline(
        cues=(
            _cue(cue_id="a", start=0.0, duration=1.0),
            _cue(cue_id="b", start=1.05, duration=1.0),  # 50 ms gap, within 100 ms tol
        ),
        gap_tolerance_seconds=0.1,
    )
    with pytest.raises(ValidationError):
        Timeline(
            cues=(
                _cue(cue_id="a", start=0.0, duration=1.0),
                _cue(cue_id="b", start=1.5, duration=1.0),  # 500 ms gap > 100 ms tol
            ),
            gap_tolerance_seconds=0.1,
        )
