"""CLI handlers for saved-plan shorts stages."""

from __future__ import annotations

import json
from typing import Any

from .runner import CommandRunner, _out


def _parse_decision(raw: str) -> str | dict[str, Any]:
    text = raw.strip()
    if text.startswith("{"):
        return json.loads(text)
    return text


def handle_shorts_commands(args: Any, *, use_json: bool) -> bool:
    runner = CommandRunner(args, use_json)

    def _show(a, j):
        from ..product.shorts_plan import load_shorts_plan

        plan = load_shorts_plan(a.plan)
        _out(
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
            },
            j,
        )

    def _review(a, j):
        from ..product.shorts_review import review_shorts_plan

        plan = review_shorts_plan(
            a.plan,
            candidate_id=a.candidate_id,
            decision=_parse_decision(a.decision),
            evidence_ref=a.evidence_ref,
        )
        _out(plan.model_dump(mode="json"), j)

    def _render(a, j):
        from ..product.shorts_render import render_approved_candidate

        _out(
            render_approved_candidate(
                a.plan,
                candidate_id=a.candidate_id,
                output_path=a.output_path,
            ),
            j,
        )

    def _package(a, j):
        from ..product.shorts_package import package_approved_candidate

        _out(
            package_approved_candidate(
                a.plan,
                candidate_id=a.candidate_id,
                package_root=a.package_root,
                overwrite=a.overwrite,
            ),
            j,
        )

    runner.register("shorts-plan-show", _show)
    runner.register("shorts-review", _review)
    runner.register("shorts-render", _render)
    runner.register("shorts-package", _package)
    return runner.dispatch()
