"""Kinocut Python client methods for the local Revideo bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..defaults import DEFAULT_REVIDEO_INSTALL_TIMEOUT, DEFAULT_REVIDEO_RENDER_TIMEOUT
from ..revideo_models import RevideoRenderResult


class ClientRevideoMixin:
    """Guarded Revideo project and render operations."""

    def revideo_materialize(
        self,
        dest: str | Path,
        job: dict[str, Any],
        scene_source: str | Path | None = None,
    ) -> dict[str, Any]:
        from ..revideo_engine import materialize_project

        project = materialize_project(dest, job, scene_source=scene_source)
        return {"success": True, "project_dir": str(project)}

    def revideo_install(
        self,
        project_dir: str | Path,
        timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT,
    ) -> dict[str, Any]:
        from ..revideo_engine import install_deps

        install_deps(project_dir, timeout=timeout)
        return {"success": True, "project_dir": str(project_dir)}

    def revideo_render(
        self,
        project_dir: str | Path,
        output_path: str,
        timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
    ) -> RevideoRenderResult:
        from ..revideo_engine import render

        return render(project_dir, output_path, timeout=timeout)

    def revideo_render_job(
        self,
        job: dict[str, Any],
        output_path: str,
        work_dir: str | Path | None = None,
        scene_source: str | Path | None = None,
        install_timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT,
        render_timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
    ) -> RevideoRenderResult:
        from ..revideo_engine import render_job

        return render_job(
            job,
            output_path,
            work_dir=work_dir,
            scene_source=scene_source,
            install_timeout=install_timeout,
            render_timeout=render_timeout,
        )
