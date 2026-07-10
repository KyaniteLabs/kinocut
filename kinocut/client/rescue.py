"""Python client methods for the dedicated rescue pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class ClientRescueMixin:
    """Plan, render, and inspect policy-bound local video rescues."""

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
