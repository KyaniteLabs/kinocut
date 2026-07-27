"""Durable one-command repurpose route over projectstore render jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kinocut.engine_repurpose import PLATFORM_PRESETS, _select_platforms
from kinocut.ffmpeg_helpers import _validate_input_path
from kinocut.projectstore import store
from kinocut.projectstore.cas import ingest_blob
from kinocut.projectstore.compat import (
    compile_repurpose_slice,
    materialize_workflow_sources,
    synthesize_workflow_spec,
)
from kinocut.projectstore.edit_projects import create_edit_project
from kinocut.projectstore.render_jobs import start_render_job, submit_render_job


def _media_type(path: str) -> str:
    suffix = Path(path).suffix.casefold()
    return {
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(suffix, "video/mp4")


def _operations(source_digest: str, platforms: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "reframe",
            "source": source_digest,
            "width": PLATFORM_PRESETS[platform]["width"],
            "height": PLATFORM_PRESETS[platform]["height"],
        }
        for platform in platforms
    ]


def _install_spec(project: store.Project, spec: dict[str, Any], platforms: list[str]) -> Path:
    for index, platform in enumerate(platforms):
        spec["outputs"][f"out{index}"]["path"] = f".kinocut/repurpose/{platform}.mp4"
    path = project.root / "repurpose_spec.json"
    encoded = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with store._mapped_os_errors():
        store._write_atomically(path, lambda output: output.write(encoded), binary=True)
    return path


def durable_repurpose(
    input_path: str,
    project_dir: str,
    *,
    platforms: list[str] | None = None,
    start: bool = True,
) -> dict[str, Any]:
    """Create one revision and async render job for N platform clips."""

    source_path = _validate_input_path(input_path)
    selected = _select_platforms(platforms)
    project = store.open_project(project_dir)
    source = ingest_blob(project, source_path, media_type=_media_type(source_path))
    edit = create_edit_project(project, created_by="tool:repurpose")
    operations = _operations(source.digest, selected)
    revision = compile_repurpose_slice(project, edit.edit_project_id, operations)
    synthesis = synthesize_workflow_spec(
        project,
        edit.edit_project_id,
        operations,
        base_revision_id=revision.record_id,
    )
    spec_path = _install_spec(project, synthesis.spec, selected)
    job = submit_render_job(
        project,
        edit_project_id=edit.edit_project_id,
        revision_id=revision.record_id,
        spec_path=str(spec_path),
        created_by="tool:repurpose",
    )
    materialize_workflow_sources(project, job.job_id, synthesis)
    status = start_render_job(project, job.job_id) if start else job
    clips = [
        {
            "platform": platform,
            "output": f".kinocut/repurpose/{platform}.mp4",
            "job_id": job.job_id,
            "revision_id": revision.record_id,
            "receipt_ref": f".kinocut/jobs/{job.job_id.removeprefix('job:')}/receipt.json",
        }
        for platform in selected
    ]
    return {
        "success": True,
        "operation": "repurpose",
        "project_id": project.project_id,
        "edit_project_id": edit.edit_project_id,
        "revision_id": revision.record_id,
        "job_id": job.job_id,
        "status": status.status.value,
        "source_digest": source.digest,
        "clips": clips,
    }


__all__ = ["durable_repurpose"]
