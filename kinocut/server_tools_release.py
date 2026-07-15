"""MCP adapters for release-artifact policy operations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp


def _run(operation: str, **kwargs: Any) -> dict[str, Any]:
    from .aivideo.release_surfaces import run_release_operation

    return _result(run_release_operation(operation, **kwargs))


@mcp.tool()
@_safe_tool
def video_review_package(
    project_dir: str,
    candidate_artifact: str,
    blocking_findings: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble a review package and publish-gate verdict for a candidate artifact."""

    return _run(
        "review_package",
        project_dir=project_dir,
        candidate_artifact=candidate_artifact,
        blocking_findings=tuple(blocking_findings or ()),
    )


@mcp.tool()
@_safe_tool
def video_publish_gate(
    project_dir: str,
    candidate_artifact: str,
    blocking_findings: list[str],
) -> dict[str, Any]:
    """Evaluate the fail-closed publish gate; any blocking finding blocks publishing."""

    return _run(
        "publish_gate",
        project_dir=project_dir,
        candidate_artifact=candidate_artifact,
        blocking_findings=tuple(blocking_findings),
    )


@mcp.tool()
@_safe_tool
def video_review_decision(project_dir: str, decision: dict[str, Any]) -> dict[str, Any]:
    """Record a human review decision (writer); corrections supersede by record id."""

    return _run("review_decision", project_dir=project_dir, decision=decision)


@mcp.tool()
@_safe_tool
def video_learning_report(project_dir: str) -> dict[str, Any]:
    """Project a learning report (verdicts, defects, costs, recipes) from records."""

    return _run("learning_report", project_dir=project_dir)


@mcp.tool()
@_safe_tool
def video_cost_ledger(project_dir: str) -> dict[str, Any]:
    """Sum known USD cost events by category for the project."""

    return _run("cost_ledger", project_dir=project_dir)


@mcp.tool()
@_safe_tool
def video_recipe_capture(project_dir: str, recipe: dict[str, Any]) -> dict[str, Any]:
    """Capture a workflow recipe (writer); idempotent by canonical digest."""

    return _run("recipe_capture", project_dir=project_dir, recipe=recipe)


@mcp.tool()
@_safe_tool
def video_capabilities() -> dict[str, Any]:
    """Probe host capabilities (ffmpeg, whisper, c2pa) and return a capability report."""

    return _run("capabilities")


@mcp.tool()
@_safe_tool
def video_benchmark_run() -> dict[str, Any]:
    """Run the AI-video benchmark corpus against host capabilities."""

    return _run("benchmark_run")
