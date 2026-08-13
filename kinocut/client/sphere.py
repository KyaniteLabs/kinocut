"""Python client adapters for 360 assembly."""

from __future__ import annotations

from typing import Any


class ClientSphereMixin:
    """Propose, review, and render 360 dual-cam assemblies."""

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
