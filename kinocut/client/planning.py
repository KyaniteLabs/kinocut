"""Plan and inspect edits, from initial estimates through rescue."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..postrescue import call_post_rescue

Request = Mapping[str, Any]


class ClientPlanningMixin:
    """Plan and inspect edits, from initial estimates through rescue."""

    def estimate_operation(self, operation: str, duration_seconds: float, complexity: float = 1.0) -> dict[str, Any]:
        """Estimate local wall time and dimensionless units, without rendering or billing."""
        from ..te import estimate_operation

        return estimate_operation(operation, duration_seconds=duration_seconds, complexity=complexity)

    def search_tools(self, query: str) -> dict[str, Any]:
        """Search registered MCP tools by keyword.

        Args:
            query: Search term — e.g. "blur", "resize", "subtitle", "audio", "trim".

        Returns:
            Dict with matching tools, their descriptions, and required parameters.
        """
        from ..server_tools_basic import search_tools as _search_tools

        return _search_tools(query)

    def rescue_plan(
        self,
        source: str,
        output_dir: str,
        save_plan: str | None = None,
        policy: str = "local_content_preserving",
    ) -> dict[str, Any]:
        """Analyze ``source`` and return a policy-classified rescue plan."""
        from ..rescue import plan_rescue

        return plan_rescue(source, output_dir, save_plan=save_plan, policy_id=policy)

    def rescue_render(
        self,
        plan: str,
        approved_repair_ids: Sequence[str] | None = None,
        save_receipt: str | None = None,
        resume_receipt: str | None = None,
        cancel_file: str | None = None,
        keep_intermediates: bool = False,
    ) -> dict[str, Any]:
        """Render approved safe repairs from a reviewed rescue plan."""
        from ..rescue import render_rescue

        return render_rescue(
            plan,
            approved_repair_ids=approved_repair_ids,
            save_receipt=save_receipt,
            resume_receipt=resume_receipt,
            cancel_file=cancel_file,
            keep_intermediates=keep_intermediates,
        )

    def rescue_inspect(self, receipt: str) -> dict[str, Any]:
        """Inspect a rescue plan or receipt without modifying artifacts."""
        from ..rescue import inspect_rescue

        return inspect_rescue(receipt)

    @staticmethod
    def _post_rescue(function: Callable[[Request], dict[str, Any]], request: Request) -> dict[str, Any]:
        return call_post_rescue(function, request)

    def semantic_timeline(self, request: Request) -> dict[str, Any]:
        from ..postrescue import semantic_timeline

        return self._post_rescue(semantic_timeline, request)

    def semantic_query(self, request: Request) -> dict[str, Any]:
        from ..postrescue import semantic_query

        return self._post_rescue(semantic_query, request)

    def timeline_edit_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import timeline_edit_plan

        return self._post_rescue(timeline_edit_plan, request)

    def visual_transform_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import visual_transform_plan

        return self._post_rescue(visual_transform_plan, request)

    def restoration_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import restoration_plan

        return self._post_rescue(restoration_plan, request)

    def composition_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import composition_plan

        return self._post_rescue(composition_plan, request)

    def creative_autopilot_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import creative_autopilot_plan

        return self._post_rescue(creative_autopilot_plan, request)

    def remote_egress_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import remote_egress_plan

        return self._post_rescue(remote_egress_plan, request)
