"""Content repurposing MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .ffmpeg_helpers import _validate_input_path
from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_repurpose_plan(
    input_path: str,
    output_dir: str | None = None,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Create a dry-run local repurposing manifest for platform-ready assets."""
    input_path = _validate_input_path(input_path)
    from .engine_repurpose import repurpose_plan

    return _result(repurpose_plan(input_path, output_dir=output_dir, platforms=platforms))


@mcp.tool()
@_safe_tool
def video_repurpose(
    input_path: str,
    output_dir: str | None = None,
    platforms: list[str] | None = None,
    include_release_checkpoint: bool = True,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Render a local content repurposing package with manifest and review artifacts."""
    input_path = _validate_input_path(input_path)
    from .engine_repurpose import repurpose

    return _result(
        repurpose(
            input_path,
            output_dir=output_dir,
            platforms=platforms,
            include_release_checkpoint=include_release_checkpoint,
            min_score=min_score,
        )
    )
