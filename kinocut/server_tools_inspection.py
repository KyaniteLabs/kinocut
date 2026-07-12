"""MCP adapters for content-addressed inspection operations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_ingest(
    project_dir: str,
    source_path: str,
    lineage: dict[str, Any] | None = None,
    usage_rights_status: str = "unknown",
    usage_rights_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Ingest immutable source bytes into an existing or new private project."""
    from .aivideo.surfaces import run_inspection_operation

    return _result(
        run_inspection_operation(
            "ingest",
            project_dir,
            source_path=source_path,
            lineage=lineage,
            usage_rights_status=usage_rights_status,
            usage_rights_evidence_ref=usage_rights_evidence_ref,
        )
    )


@mcp.tool()
@_safe_tool
def video_preflight(project_dir: str, asset_id: str) -> dict[str, Any]:
    """Run unified technical, loudness, color, and decode preflight."""
    from .aivideo.surfaces import run_inspection_operation

    return _result(run_inspection_operation("preflight", project_dir, asset_id=asset_id))


@mcp.tool()
@_safe_tool
def video_inspect_temporal(
    project_dir: str,
    asset_id: str,
    declared_regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build and persist the complete deterministic temporal evidence package."""
    from .aivideo.surfaces import run_inspection_operation

    return _result(
        run_inspection_operation(
            "inspect_temporal",
            project_dir,
            asset_id=asset_id,
            declared_regions=declared_regions,
        )
    )
