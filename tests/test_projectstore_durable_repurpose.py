from __future__ import annotations

import json
from pathlib import Path

from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import MomentSelectionRecord
from kinocut.projectstore import (
    append_record,
    append_revision,
    cancel_render_job,
    create_edit_project,
    get_render_job,
    open_project,
    read_records,
    render_job_status,
    resume_render_job,
)
from kinocut.projectstore import render_jobs, render_runner
from kinocut.projectstore.repurpose import durable_repurpose


def test_durable_repurpose_creates_revision_job_and_n_lineage_bound_clips(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture media")
    project_dir = tmp_path / "project"

    result = durable_repurpose(
        str(source),
        str(project_dir),
        platforms=["youtube", "youtube-shorts"],
        start=False,
    )

    assert result["status"] == "queued"
    assert len(result["clips"]) == 2
    assert {clip["platform"] for clip in result["clips"]} == {"youtube", "youtube-shorts"}
    assert all(clip["job_id"] == result["job_id"] for clip in result["clips"])
    assert all(clip["revision_id"] == result["revision_id"] for clip in result["clips"])
    assert str(tmp_path) not in json.dumps(result)

    project = open_project(project_dir)
    job = get_render_job(project, result["job_id"])
    spec = json.loads(render_jobs.job_spec_path(project, job.job_id).read_text())
    assert [step["op"] for step in spec["steps"]] == ["resize", "resize"]
    assert [spec["outputs"][key]["path"] for key in sorted(spec["outputs"])] == [
        ".kinocut/repurpose/youtube.mp4",
        ".kinocut/repurpose/youtube-shorts.mp4",
    ]
    assert (render_jobs.job_spec_path(project, job.job_id).parent / "sources/src0.mp4").is_file()

    cancel_render_job(project, job.job_id)
    reopened = open_project(project_dir)
    assert resume_render_job(reopened, job.job_id).status.value == "queued"
    render_jobs.mark_running(reopened, job.job_id, 424242)

    receipt = {
        "success": True,
        "status": "completed",
        "sources": [{"id": "src0", "source_hash": result["source_digest"]}],
        "outputs": [
            {"id": "out0", "output_hash": "sha256:" + "a" * 64},
            {"id": "out1", "output_hash": "sha256:" + "b" * 64},
        ],
        "versions": {"kinocut": "1.12.0", "ffmpeg": "fixture"},
        "steps": [
            {"id": "resize_out0", "status": "completed", "output_hash": "sha256:" + "a" * 64},
            {"id": "resize_out1", "status": "completed", "output_hash": "sha256:" + "b" * 64},
        ],
    }
    monkeypatch.setattr(render_runner, "video_workflow_render", lambda **kwargs: receipt)

    assert render_runner.run_job(reopened, job.job_id) == "succeeded"
    persisted = json.loads(render_jobs.job_receipt_path(reopened, job.job_id).read_text())
    assert persisted["lineage"]["edit_project_id"] == result["edit_project_id"]
    assert persisted["lineage"]["revision_id"] == result["revision_id"]
    assert persisted["lineage"]["job_id"] == result["job_id"]
    assert render_job_status(reopened, job.job_id)["status"] == "succeeded"


def test_public_repurpose_submits_durable_job_without_legacy_direct_render(tmp_path: Path):
    from kinocut.server_tools_repurpose import video_repurpose

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture media")
    result = video_repurpose(
        str(source),
        output_dir=str(tmp_path / "project"),
        platforms=["tiktok"],
        start_job=False,
    )

    assert result["success"] is True
    assert result["operation"] == "repurpose"
    assert result["status"] == "queued"
    assert result["clips"][0]["platform"] == "tiktok"


def test_durable_repurpose_binds_explicit_reviewed_moment_selection(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture media")
    project_dir = tmp_path / "project"
    project = open_project(project_dir)
    selection_project = create_edit_project(project)
    selection_revision = append_revision(project, selection_project.edit_project_id, operation_ids=())
    selection = append_record(
        project,
        validate_record(
            MomentSelectionRecord,
            {
                "project_id": project.project_id,
                "created_by": "human:review",
                "edit_project_id": selection_project.edit_project_id,
                "revision_id": selection_revision.record_id,
                "index_digest": "sha256:" + "1" * 64,
                "selected_span_ids": ("span:approved",),
                "selection_example_ids": ("approved-learning",),
                "query_text": "approved moment",
            },
        ),
    )

    result = durable_repurpose(
        str(source),
        str(project_dir),
        platforms=["tiktok"],
        start=False,
        moment_selection_record_id=selection.record_id,
    )

    bindings = read_records(open_project(project_dir), "repurpose_selection_binding")
    assert result["selection_binding_record_id"] == bindings[0].record_id
    assert bindings[0].revision_id == result["revision_id"]
    assert bindings[0].moment_selection_record_id == selection.record_id
