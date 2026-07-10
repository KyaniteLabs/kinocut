from __future__ import annotations

import pytest

from mcp_video.semantic.edl import EditOperation
from mcp_video.semantic.generators import (
    generate_false_start_edl,
    generate_filler_edl,
    generate_pacing_edl,
    generate_reorder_edl,
    generate_retake_edl,
    generate_silence_edl,
    generate_trim_edl,
)
from mcp_video.semantic.models import AnalyzerProvenance, SemanticTimeline, ShotSpan, SilenceSpan, SourceMedia, WordSpan


def _timeline() -> SemanticTimeline:
    source = SourceMedia.create(content_sha256="sha256:" + "5" * 64, duration_seconds=8)
    provenance = AnalyzerProvenance(
        analyzer_id="fixture.disfluency",
        analyzer_version="1",
        model_id="fixture",
        model_sha256="sha256:" + "6" * 64,
        determinism_scope="fixture",
    )
    words = (
        WordSpan.create(
            source=source,
            start_seconds=0.2,
            end_seconds=0.3,
            confidence=0.98,
            provenance=provenance,
            text="um",
            disfluency="filler",
        ),
        WordSpan.create(
            source=source,
            start_seconds=0.4,
            end_seconds=0.5,
            confidence=0.4,
            provenance=provenance,
            text="uh",
            text_status="uncertain",
            disfluency="filler",
            uncertainty=("low signal",),
        ),
        WordSpan.create(
            source=source,
            start_seconds=2,
            end_seconds=2.4,
            confidence=0.95,
            provenance=provenance,
            text="I mean",
            disfluency="false_start",
        ),
        WordSpan.create(
            source=source,
            start_seconds=4,
            end_seconds=4.4,
            confidence=0.96,
            provenance=provenance,
            text="first",
            retake_group_id="intro",
            take_id="take_1",
            selected_take=False,
        ),
        WordSpan.create(
            source=source,
            start_seconds=5,
            end_seconds=5.4,
            confidence=0.97,
            provenance=provenance,
            text="second",
            retake_group_id="intro",
            take_id="take_2",
            selected_take=True,
        ),
    )
    shots = (
        ShotSpan.create(source=source, start_seconds=0, end_seconds=4, confidence=1, provenance=provenance, ordinal=0),
        ShotSpan.create(source=source, start_seconds=4, end_seconds=8, confidence=1, provenance=provenance, ordinal=1),
    )
    silence = SilenceSpan.create(
        source=source,
        start_seconds=0.8,
        end_seconds=1.8,
        confidence=0.99,
        provenance=provenance,
        mean_dbfs=-55,
    )
    return SemanticTimeline.create(source=source, words=words, shots=shots, silences=(silence,))


def test_silence_filler_false_start_and_retake_generators_preserve_uncertainty() -> None:
    timeline = _timeline()

    silence = generate_silence_edl(timeline, max_silence_seconds=0.4)
    fillers = generate_filler_edl(timeline, min_confidence=0.8)
    false_starts = generate_false_start_edl(timeline, min_confidence=0.8)
    retakes = generate_retake_edl(timeline, min_confidence=0.8)

    assert len(silence.edits) == 1
    assert silence.edits[0].source_end_seconds - silence.edits[0].source_start_seconds == pytest.approx(0.6)
    assert [edit.target_span_id for edit in fillers.edits] == [timeline.words[0].span_id]
    assert [edit.target_span_id for edit in false_starts.edits] == [timeline.words[2].span_id]
    assert [edit.target_span_id for edit in retakes.edits] == [timeline.words[3].span_id]
    assert all(
        edit.operation == EditOperation.DELETE
        for edit in (*silence.edits, *fillers.edits, *false_starts.edits, *retakes.edits)
    )


def test_pacing_trim_and_reorder_are_deterministic_explicit_edls() -> None:
    timeline = _timeline()

    pacing = generate_pacing_edl(timeline, max_silence_seconds=0.5, remove_fillers=True, min_confidence=0.8)
    trim = generate_trim_edl(timeline, keep_start_seconds=1, keep_end_seconds=7)
    reorder = generate_reorder_edl(timeline, ordered_span_ids=(timeline.shots[1].span_id, timeline.shots[0].span_id))

    assert len(pacing.edits) == 2
    assert [(edit.source_start_seconds, edit.source_end_seconds) for edit in trim.edits] == [(0.0, 1.0), (7.0, 8.0)]
    assert [edit.destination_index for edit in reorder.edits] == [0, 1]
    assert (
        generate_pacing_edl(
            timeline,
            max_silence_seconds=0.5,
            remove_fillers=True,
            min_confidence=0.8,
        ).edl_sha256
        == pacing.edl_sha256
    )
