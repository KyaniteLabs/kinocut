"""Pydantic result models for the Revideo bridge."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RevideoRenderResult(BaseModel):
    """Receipt for one Revideo bridge render."""

    project_dir: str = Field(description="Materialized bridge project (workspace-relative when possible).")
    output_path: str
    output_sha256: str = Field(description="SHA-256 of the rendered file — determinism anchor.")
    job_sha256: str = Field(description="SHA-256 of the complete, bounded, exact on-disk src/job.json bytes.")
    width: int
    height: int
    fps: float
    frames: int
    duration_seconds: float
    render_seconds: float
