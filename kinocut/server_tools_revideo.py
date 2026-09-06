"""Public MCP registrations for the local Revideo bridge."""

from __future__ import annotations

from typing import Any

from .defaults import DEFAULT_REVIDEO_INSTALL_TIMEOUT, DEFAULT_REVIDEO_RENDER_TIMEOUT
from .server_app import _safe_tool, mcp


def _render_payload(result: Any) -> dict[str, Any]:
    return {"success": True, **result.model_dump(mode="json")}


@mcp.tool()
@_safe_tool
def revideo_materialize(dest: str, job: dict[str, Any], scene_source: str | None = None) -> dict[str, Any]:
    """Materialize Kinocut's pinned Revideo project for a validated job."""
    from .revideo_engine import materialize_project

    project = materialize_project(dest, job, scene_source=scene_source)
    return {"success": True, "project_dir": str(project)}


@mcp.tool()
@_safe_tool
def revideo_install(
    project_dir: str,
    timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT,
) -> dict[str, Any]:
    """Install the exact locked Revideo dependencies for a materialized project."""
    from .revideo_engine import install_deps

    install_deps(project_dir, timeout=timeout)
    return {"success": True, "project_dir": str(project_dir)}


@mcp.tool()
@_safe_tool
def revideo_render(
    project_dir: str,
    output_path: str,
    timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
) -> dict[str, Any]:
    """Render and atomically publish a verified local Revideo artifact."""
    from .revideo_engine import render

    return _render_payload(render(project_dir, output_path, timeout=timeout))


@mcp.tool()
@_safe_tool
def revideo_render_job(
    job: dict[str, Any],
    output_path: str,
    work_dir: str | None = None,
    scene_source: str | None = None,
    install_timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT,
    render_timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
) -> dict[str, Any]:
    """Materialize, install, render, and verify one local Revideo job."""
    from .revideo_engine import render_job

    return _render_payload(
        render_job(
            job,
            output_path,
            work_dir=work_dir,
            scene_source=scene_source,
            install_timeout=install_timeout,
            render_timeout=render_timeout,
        )
    )
