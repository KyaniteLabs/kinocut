"""MCP adapters for saved-plan shorts review, render, and package stages."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def shorts_plan_show(plan_path_or_dir: str) -> dict[str, Any]:
    """Load a saved shorts plan and return source-free proposals for review."""
    from .product.shorts_plan import load_shorts_plan

    plan = load_shorts_plan(plan_path_or_dir)
    return _result(
        {
            "job_id": plan.job_id,
            "status": plan.status,
            "platforms": list(plan.platforms),
            "proposals": [item.model_dump(mode="json") for item in plan.proposals],
            "decisions": [item.model_dump(mode="json") for item in plan.decisions],
            "renders": [item.model_dump(mode="json") for item in plan.renders],
            "package_manifests": list(plan.package_manifests),
            "external_posting": False,
            "source_path": plan.intake.source_path,
        }
    )


@mcp.tool()
@_safe_tool
def shorts_review(
    plan_path_or_dir: str,
    candidate_id: str,
    decision: str | dict[str, Any],
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Append one human review decision to a saved shorts plan (source-free)."""
    from .product.shorts_review import review_shorts_plan

    plan = review_shorts_plan(
        plan_path_or_dir,
        candidate_id=candidate_id,
        decision=decision,
        evidence_ref=evidence_ref,
    )
    return _result(plan.model_dump(mode="json"))


@mcp.tool()
@_safe_tool
def shorts_render(
    plan_path_or_dir: str,
    candidate_id: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Render platform drafts for an approved candidate from a saved plan."""
    from .product.shorts_render import render_approved_candidate

    return _result(
        render_approved_candidate(
            plan_path_or_dir,
            candidate_id=candidate_id,
            output_path=output_path,
        )
    )


@mcp.tool()
@_safe_tool
def shorts_package(
    plan_path_or_dir: str,
    candidate_id: str,
    package_root: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Package approved platform renders from a saved plan. Never posts."""
    from .product.shorts_package import package_approved_candidate

    return _result(
        package_approved_candidate(
            plan_path_or_dir,
            candidate_id=candidate_id,
            package_root=package_root,
            overwrite=overwrite,
        )
    )
