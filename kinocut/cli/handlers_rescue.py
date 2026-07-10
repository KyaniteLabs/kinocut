"""CLI handlers for the dedicated rescue pipeline."""

from __future__ import annotations

from typing import Any

from .rescue_formatting import format_rescue_inspect, format_rescue_plan, format_rescue_render
from .runner import CommandRunner, _out


def handle_rescue_commands(args: Any, *, use_json: bool) -> bool:
    """Handle rescue plan, render, and inspect commands."""
    runner = CommandRunner(args, use_json)

    def _rescue_plan(a, use_json_output):
        from ..rescue import plan_rescue

        result = plan_rescue(
            a.source,
            a.output_dir,
            save_plan=a.save_plan,
            policy_id=a.policy,
        )
        _out(result, use_json_output, format_rescue_plan)

    runner.register("rescue-plan", _rescue_plan)

    def _rescue_render(a, use_json_output):
        from ..rescue import render_rescue

        result = render_rescue(
            a.plan,
            approved_repair_ids=a.approve,
            save_receipt=a.save_receipt,
            resume_receipt=a.resume,
            cancel_file=a.cancel_file,
            keep_intermediates=a.keep_intermediates,
        )
        _out(result, use_json_output, format_rescue_render)

    runner.register("rescue-render", _rescue_render)

    def _rescue_inspect(a, use_json_output):
        from ..rescue import inspect_rescue

        result = inspect_rescue(a.receipt)
        _out(result, use_json_output, format_rescue_inspect)

    runner.register("rescue-inspect", _rescue_inspect)

    return runner.dispatch()
