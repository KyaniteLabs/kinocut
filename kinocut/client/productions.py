"""Review and render saved shorts, sphere assemblies, and Revideo projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..defaults import DEFAULT_REVIDEO_INSTALL_TIMEOUT, DEFAULT_REVIDEO_RENDER_TIMEOUT
from ..revideo_models import RevideoRenderResult


class ClientProductionsMixin:
    """Review and render saved shorts, sphere assemblies, and Revideo projects."""

    def shorts_plan_show(self, plan_path_or_dir: str) -> dict[str, Any]:
        """Load a saved shorts plan and return proposals without re-ingesting source."""
        from ..product.shorts_plan import load_shorts_plan

        plan = load_shorts_plan(plan_path_or_dir)
        return {
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

    def shorts_review(
        self,
        plan_path_or_dir: str,
        *,
        candidate_id: str,
        decision: str | dict[str, Any],
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """Append one human review decision to a saved shorts plan."""
        from ..product.shorts_review import review_shorts_plan

        return review_shorts_plan(
            plan_path_or_dir,
            candidate_id=candidate_id,
            decision=decision,
            evidence_ref=evidence_ref,
        ).model_dump(mode="json")

    def shorts_render(
        self,
        plan_path_or_dir: str,
        *,
        candidate_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Render approved platform drafts from a saved plan."""
        from ..product.shorts_render import render_approved_candidate

        return render_approved_candidate(
            plan_path_or_dir,
            candidate_id=candidate_id,
            output_path=output_path,
        )

    def shorts_package(
        self,
        plan_path_or_dir: str,
        *,
        candidate_id: str,
        package_root: str | None = None,
        overwrite: bool = False,
        allow_fail: bool = False,
    ) -> dict[str, Any]:
        """Package approved platform renders from a saved plan. Never posts."""
        from ..product.shorts_package import package_approved_candidate

        return package_approved_candidate(
            plan_path_or_dir,
            candidate_id=candidate_id,
            package_root=package_root,
            overwrite=overwrite,
            allow_fail=allow_fail,
        )

    def propose_360_assembly(self, source: str, **kwargs: Any) -> dict[str, Any]:
        from ..te.sphere_assembly import propose_360_assembly

        return propose_360_assembly(source, **kwargs)

    def storyboard_360_assembly(self, plan: dict[str, Any], output_dir: str) -> dict[str, Any]:
        from ..te.sphere_storyboard import storyboard_sphere_plan

        return storyboard_sphere_plan(plan, output_dir)

    def decide_360_assembly(self, plan: dict[str, Any], decision: str, **kwargs: Any) -> dict[str, Any]:
        from ..te.sphere_plan import decide_sphere_plan

        return decide_sphere_plan(plan, decision, **kwargs)

    def render_360_assembly(self, plan: dict[str, Any], output_path: str, **kwargs: Any) -> dict[str, Any]:
        from ..te.sphere_render import render_sphere_plan

        return render_sphere_plan(plan, output_path, **kwargs)

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
