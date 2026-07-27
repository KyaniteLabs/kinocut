"""Local Whisper/VAD detection, explicit review, and durable typed cut application."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    apply_disfluency_cut_plan,
    compile_disfluency_cut_plan,
    create_edit_project,
    ingest_blob,
    open_project,
    read_records,
)
from kinocut.semantic.disfluency import build_local_disfluency_timeline, generate_disfluency_edl
from kinocut.semantic.models import AnalyzerProvenance, SourceMedia

_MODEL_HASH = "sha256:" + "d" * 64


def _provenance() -> AnalyzerProvenance:
    return AnalyzerProvenance(
        analyzer_id="whisper-silero-disfluency",
        analyzer_version="1",
        model_id="whisper-base+silero-vad",
        model_sha256=_MODEL_HASH,
        determinism_scope="fixed local model bytes and thresholds",
        local_execution=True,
        network_used=False,
    )


def _analysis(source_digest: str):
    source = SourceMedia.create(content_sha256=source_digest, duration_seconds=4.0)
    words = (
        {"word": "um", "start": 0.20, "end": 0.40, "probability": 0.98},
        {"word": "we", "start": 0.50, "end": 0.70, "probability": 0.97},
        {"word": "need", "start": 0.70, "end": 0.90, "probability": 0.96},
        {"word": "we", "start": 1.00, "end": 1.20, "probability": 0.98},
        {"word": "need", "start": 1.20, "end": 1.40, "probability": 0.97},
        {"word": "ship", "start": 1.50, "end": 1.80, "probability": 0.99},
        {"word": "uh", "start": 2.10, "end": 2.30, "probability": 0.20},
    )
    vad = (
        {"start": 0.10, "end": 1.90, "confidence": 0.99},
        {"start": 2.00, "end": 2.40, "confidence": 0.95},
    )
    return build_local_disfluency_timeline(
        source=source,
        whisper_words=words,
        vad_speech=vad,
        provenance=_provenance(),
    )


def test_local_analysis_detects_filler_restart_and_preserves_uncertainty(tmp_path: Path) -> None:
    media = tmp_path / "source.bin"
    media.write_bytes(b"auditable media fixture")
    project = open_project(tmp_path / "project")
    digest = ingest_blob(project, media, media_type="video/mp4").digest

    timeline = _analysis(digest)
    edl = generate_disfluency_edl(timeline)

    assert [word.disfluency for word in timeline.words[:5]] == [
        "filler",
        "false_start",
        "false_start",
        "none",
        "none",
    ]
    assert timeline.words[-1].text_status == "uncertain"
    assert timeline.words[-1].disfluency == "none"
    assert len(edl.edits) == 3
    assert timeline.silences


def test_review_does_not_mutate_and_explicit_selection_appends_one_revision(tmp_path: Path) -> None:
    media = tmp_path / "source.bin"
    media.write_bytes(b"durable media fixture")
    project = open_project(tmp_path / "project")
    digest = ingest_blob(project, media, media_type="video/mp4").digest
    edit_project = create_edit_project(project)
    timeline = _analysis(digest)
    edl = generate_disfluency_edl(timeline)
    before = len(read_records(project, "edit_revision"))

    plan = compile_disfluency_cut_plan(
        timeline=timeline,
        edl=edl,
        selected_edit_ids=tuple(edit.edit_id for edit in edl.edits),
        source_digest=digest,
    )

    assert len(read_records(project, "edit_revision")) == before
    revision = apply_disfluency_cut_plan(project, edit_project.edit_project_id, plan)
    assert revision.operation_ids == (plan.operation_id,)
    assert len(read_records(project, "edit_revision")) == before + 1
    assert plan.keep_segments == ((0.0, 0.2), (0.4, 0.5), (0.9, 4.0))


def test_unknown_review_selection_fails_without_revision(tmp_path: Path) -> None:
    project = open_project(tmp_path / "project")
    timeline = _analysis("sha256:" + "a" * 64)
    edl = generate_disfluency_edl(timeline)

    with pytest.raises(MCPVideoError):
        compile_disfluency_cut_plan(
            timeline=timeline,
            edl=edl,
            selected_edit_ids=("edit:" + "0" * 64,),
            source_digest="sha256:" + "a" * 64,
        )

    assert read_records(project, "edit_revision") == []
