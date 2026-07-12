"""MCP adapters for governed Wave 3 AI-video operations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp


def _run(operation: str, **kwargs: Any) -> dict[str, Any]:
    from .aivideo.wave3_surfaces import run_wave3_operation

    return _result(run_wave3_operation(operation, **kwargs))


@mcp.tool()
@_safe_tool
def video_verdict(project_dir: str, verdict: dict[str, Any]) -> dict[str, Any]:
    """Persist exact-asset analysis; approvals require active human evidence."""

    return _run("verdict", project_dir=project_dir, verdict=verdict)


@mcp.tool()
@_safe_tool
def video_acceptance_eval(
    project_dir: str,
    acceptance_spec_id: str,
    verdict_ids: list[str],
) -> dict[str, Any]:
    """Evaluate exact-spec verdict and defect evidence without approving anything."""

    return _run(
        "acceptance_eval",
        project_dir=project_dir,
        acceptance_spec_id=acceptance_spec_id,
        verdict_ids=verdict_ids,
    )


@mcp.tool()
@_safe_tool
def video_body_swap(
    project_dir: str,
    video_source: str,
    audio_source: str,
    output_path: str,
    duration_policy: str | None = None,
    authorization_decision_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Replace video while preserving approved audio with explicit duration policy."""

    return _run(
        "body_swap",
        project_dir=project_dir,
        video_source=video_source,
        audio_source=audio_source,
        output_path=output_path,
        duration_policy=duration_policy,
        authorization_decision_ids=authorization_decision_ids or [],
    )


@mcp.tool()
@_safe_tool
def video_salvage(
    project_dir: str,
    source_asset_id: str,
    recipe: str,
    policy: dict[str, Any],
    acceptance_spec_id: str,
    authorization_decision_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create one lineage-bound salvage derivative and a fresh review slot."""

    return _run(
        "salvage",
        project_dir=project_dir,
        source_asset_id=source_asset_id,
        recipe=recipe,
        policy=policy,
        acceptance_spec_id=acceptance_spec_id,
        authorization_decision_ids=authorization_decision_ids or [],
    )
