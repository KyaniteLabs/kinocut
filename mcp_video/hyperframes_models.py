"""Pydantic result models for Hyperframes integration tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CompositionInfo(BaseModel):
    """A single composition found in a Hyperframes project."""

    id: str
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    duration_in_frames: int = 150
    default_props: dict[str, Any] = Field(default_factory=dict)


class CompositionsResult(BaseModel):
    """Result of listing compositions in a Hyperframes project."""

    success: bool = True
    compositions: list[CompositionInfo] = Field(default_factory=list)
    project_path: str


class HyperframesRenderResult(BaseModel):
    """Result of rendering a Hyperframes composition to video."""

    success: bool = True
    output_path: str
    duration: float | None = None
    resolution: str | None = None
    codec: str = "h264"
    size_mb: float | None = None
    render_time: float | None = None


class HyperframesPreviewResult(BaseModel):
    """Result of launching Hyperframes preview studio."""

    success: bool = True
    url: str
    port: int
    project_path: str
    pid: int | None = None


class HyperframesStillResult(BaseModel):
    """Result of rendering a single frame from a Hyperframes composition."""

    success: bool = True
    output_path: str
    frame: int = 0
    resolution: str | None = None


class HyperframesSnapshotResult(BaseModel):
    """Result of capturing one or more Hyperframes snapshot frames."""

    success: bool = True
    frame_paths: list[str] = Field(default_factory=list)
    output_dir: str
    frames: int | None = None
    at: list[float] = Field(default_factory=list)


class HyperframesJsonResult(BaseModel):
    """Generic JSON-capable result for Hyperframes utility commands."""

    success: bool = True
    command: str
    data: dict[str, Any] | list[Any] | str = Field(default_factory=dict)
    stdout: str = ""

    @property
    def items(self) -> list[Any]:
        """Convenience alias for catalog-like list responses."""
        return self.data if isinstance(self.data, list) else []


class HyperframesProjectResult(BaseModel):
    """Result of creating a new Hyperframes project."""

    success: bool = True
    project_path: str
    template: str | None = None
    files: list[str] = Field(default_factory=list)


class HyperframesBlockResult(BaseModel):
    """Result of adding a block from the Hyperframes catalog."""

    success: bool = True
    project_path: str
    block_name: str
    files_added: list[str] = Field(default_factory=list)


class HyperframesValidationResult(BaseModel):
    """Result of validating a Hyperframes project."""

    success: bool = True
    valid: bool
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    project_path: str


class HyperframesPipelineResult(BaseModel):
    """Result of render + post-process pipeline."""

    success: bool = True
    hyperframes_output: str
    final_output: str
    operations: list[str] = Field(default_factory=list)
