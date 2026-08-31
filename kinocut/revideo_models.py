"""Pydantic result models for the Revideo bridge and Sinter winners bundles."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RevideoRenderResult(BaseModel):
    """Receipt for one Revideo bridge render."""

    project_dir: str = Field(description="Materialized bridge project (workspace-relative when possible).")
    output_path: str
    output_sha256: str = Field(description="SHA-256 of the rendered file — determinism anchor.")
    width: int
    height: int
    fps: float
    frames: int
    duration_seconds: float
    render_seconds: float


class WinnersArtifactInfo(BaseModel):
    """One winner inside a verified Sinter winners bundle."""

    artifact_id: str
    event_id: str
    domain: str
    axes: str
    level: str
    payload_path: str = Field(description="Path relative to the bundle root.")
    payload_sha256: str
    payload_bytes: int


class WinnersBundleReceipt(BaseModel):
    """Fail-closed verification receipt for a winners-bundle envelope."""

    schema_version: str
    exported_at: str
    envelope_sha256: str
    artifacts: list[WinnersArtifactInfo]
    staged_dir: str | None = None
