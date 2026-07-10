"""Dedicated rescue-pipeline MCP tool registrations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .rescue import inspect_rescue, plan_rescue, render_rescue
from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_rescue_plan(
    source: str,
    output_dir: str,
    save_plan: str | None = None,
    policy: str = "local_content_preserving",
) -> dict[str, Any]:
    """Analyze one local video and return a policy-classified rescue plan.

    Planning never changes the source or renders final media. It records
    findings, safe repair ids, recommendations, unavailable and blocked work,
    local capability evidence, previews, and an execution estimate.
    """
    return _result(plan_rescue(source, output_dir, save_plan=save_plan, policy_id=policy))


@mcp.tool()
@_safe_tool
def video_rescue_render(
    plan: str,
    approved_repair_ids: Sequence[str] | None = None,
    save_receipt: str | None = None,
    resume_receipt: str | None = None,
    cancel_file: str | None = None,
    keep_intermediates: bool = False,
) -> dict[str, Any]:
    """Render approved safe repairs from a reviewed rescue plan.

    Approval ids must name safe repairs in this exact immutable plan. The
    renderer fails closed on stale inputs, capabilities, policy, resume state,
    cancellation, or verification failure and never promotes failed output.
    """
    return _result(
        render_rescue(
            plan,
            approved_repair_ids=approved_repair_ids,
            save_receipt=save_receipt,
            resume_receipt=resume_receipt,
            cancel_file=cancel_file,
            keep_intermediates=keep_intermediates,
        )
    )


@mcp.tool()
@_safe_tool
def video_rescue_inspect(receipt: str) -> dict[str, Any]:
    """Inspect a rescue plan or receipt and re-check artifact integrity."""
    return _result(inspect_rescue(receipt))
