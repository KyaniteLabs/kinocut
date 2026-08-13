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
    start_job: bool = True,
    moment_selection_record_id: str | None = None,
) -> dict[str, Any]:
    """Submit one durable projectstore repurpose job for platform clips.

    ``min_score`` is accepted for signature parity with sync ``repurpose``
    and is **not applied**. Durable jobs do not run ``assert_quality``.
    Use CLI/Client ``repurpose`` (default 80) for the fail-closed ship seam.
    """
    input_path = _validate_input_path(input_path)
    from .paths import _auto_output_dir
    from .projectstore.repurpose import durable_repurpose

    project_dir = output_dir or _auto_output_dir(input_path, "repurpose-project")
    # Durable path: include_release_checkpoint / min_score are unused (Wave 2 OUT).
    _ = include_release_checkpoint, min_score
    return _result(
        durable_repurpose(
            input_path,
            project_dir,
            platforms=platforms,
            start=start_job,
            moment_selection_record_id=moment_selection_record_id,
        )
    )
