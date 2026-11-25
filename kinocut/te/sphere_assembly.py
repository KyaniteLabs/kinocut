"""Facade: propose / storyboard / approve / render a 360 assembly."""

from __future__ import annotations

import re
from collections.abc import Callable
import os
from typing import Any

from kinocut.contracts.review import ProposalStatus
from kinocut.errors import MCPVideoError
from kinocut.te.sphere_director import ENV_DIRECTOR, DirectorFn, apply_director, detect_sphere_director
from kinocut.te.sphere_plan import (
    decide_sphere_plan,
    propose_sphere_plan,
    require_approved,
    sphere_plan_digest,
    validate_sphere_plan,
)
from kinocut.te.sphere_render import render_sphere_plan
from kinocut.te.sphere_storyboard import storyboard_sphere_plan


_SPHERE_GOAL = re.compile(
    r"360|equirect|spherical|insta360|insta\s*360|\b(?:x[2-5]|theta)\b|gopro\s+max|osmo\s*360",
    re.IGNORECASE,
)


def is_sphere_goal(goal: str) -> bool:
    """True when a natural-language goal should emit a 360 assembly plan."""
    lower = (goal or "").lower()
    if _SPHERE_GOAL.search(lower):
        return True
    if re.search(r"\bdesk\b", lower) and any(token in lower for token in ("screen", "split", "pip", "code")):
        return True
    return bool(
        re.search(r"\btable\b", lower) and any(token in lower for token in ("tarot", "card", "switch", "split"))
    )


def infer_sphere_preset(goal: str) -> str:
    lower = (goal or "").lower()
    if "table" in lower or "tarot" in lower or "card" in lower:
        return "table"
    if "desk" in lower or "screen" in lower or "code" in lower:
        return "desk"
    return "front_back"


def infer_sphere_layout(goal: str) -> str | None:
    lower = (goal or "").lower()
    for layout in ("split", "switch", "pip", "single"):
        if layout in lower:
            return layout
    return None


def infer_sphere_aspect(goal: str) -> str:
    lower = (goal or "").lower()
    if "9:16" in lower or "vertical" in lower or "short" in lower or "reel" in lower:
        return "9:16"
    return "16:9"


def propose_360_assembly(
    source: str,
    *,
    goal: str | None = None,
    preset: str | None = None,
    layout: str | None = None,
    aspect: str | None = None,
    writer_kind: str = "heuristic",
    director: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    allow_cloud: bool = False,
    propose: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    storyboard_dir: str | None = None,
) -> dict[str, Any]:
    """Probe + plan (+ optional director and storyboard). Never renders."""
    chosen_preset = preset or infer_sphere_preset(goal or "")
    chosen_layout = layout or infer_sphere_layout(goal or "")
    chosen_aspect = aspect or infer_sphere_aspect(goal or "")
    if writer_kind == "single":
        plan = propose_sphere_plan(
            source, preset=chosen_preset, layout=chosen_layout, aspect=chosen_aspect, writer_kind="single"
        )
    elif director or propose or os.environ.get(ENV_DIRECTOR, "").strip():
        plan = apply_director(
            source,
            preset=chosen_preset,
            layout=chosen_layout,
            aspect=chosen_aspect,
            director=director,
            model=model,
            base_url=base_url,
            allow_cloud=allow_cloud,
            propose=propose,
        )
    else:
        plan = propose_sphere_plan(
            source, preset=chosen_preset, layout=chosen_layout, aspect=chosen_aspect, writer_kind=writer_kind
        )
    if storyboard_dir:
        plan = storyboard_sphere_plan(plan, storyboard_dir)
    if goal:
        plan["goal"] = goal
    return plan


def approve_and_render(
    plan: dict[str, Any],
    output_path: str,
    *,
    decision: str = "approve",
    layout: str | None = None,
    allow_fail: bool = False,
    work_dir: str | None = None,
) -> dict[str, Any]:
    validated_in = validate_sphere_plan(plan)
    if "approval" in validated_in:
        prior_approval = validated_in.get("approval")
        if not isinstance(prior_approval, dict) or prior_approval.get("plan_sha256") != sphere_plan_digest(
            validated_in
        ):
            raise MCPVideoError(
                "360 assembly plan approval digest is invalid or tampered; re-propose or clear stale approval.",
                error_type="validation_error",
                code="human_apply_required",
            )
    decided = decide_sphere_plan(validated_in, decision, layout=layout)
    if decided.get("status") != ProposalStatus.APPROVED:
        return decided
    verified = require_approved(decided)
    receipt = render_sphere_plan(verified, output_path, work_dir=work_dir, allow_fail=allow_fail)
    return {**verified, "sphere_render": receipt}


__all__ = [
    "DirectorFn",
    "approve_and_render",
    "detect_sphere_director",
    "infer_sphere_aspect",
    "infer_sphere_layout",
    "infer_sphere_preset",
    "is_sphere_goal",
    "propose_360_assembly",
    "validate_sphere_plan",
]
