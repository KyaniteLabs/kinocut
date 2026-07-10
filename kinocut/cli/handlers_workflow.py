"""CLI handlers for workflow-engine commands."""

from __future__ import annotations

from typing import Any

from .formatting import (
    _format_workflow_inspect,
    _format_workflow_plan,
    _format_workflow_render,
    _format_workflow_validation,
)
from .runner import CommandRunner, _out


def handle_workflow_commands(args: Any, *, use_json: bool) -> bool:
    """Handle workflow-engine CLI commands."""
    runner = CommandRunner(args, use_json)

    def _workflow_validate(a, j):
        from ..workflow import validate_workflow_spec

        result = validate_workflow_spec(a.spec)
        _out(result, j, _format_workflow_validation)

    runner.register("workflow-validate", _workflow_validate)

    def _workflow_plan(a, j):
        from ..workflow import plan_workflow

        result = plan_workflow(a.spec, a.save_plan, a.variant)
        _out(result, j, _format_workflow_plan)

    runner.register("workflow-plan", _workflow_plan)

    def _workflow_render(a, j):
        from ..workflow import render_workflow

        result = render_workflow(
            a.spec,
            a.resume,
            a.save_receipt,
            keep_intermediates=a.keep_intermediates,
            variant=a.variant,
            all_variants=a.all_variants,
            save_receipt_dir=a.save_receipt_dir,
        )
        _out(result, j, _format_workflow_render)

    runner.register("workflow-render", _workflow_render)

    def _workflow_inspect(a, j):
        from ..workflow import inspect_receipt

        result = inspect_receipt(a.receipt)
        _out(result, j, _format_workflow_inspect)

    runner.register("workflow-inspect", _workflow_inspect)

    return runner.dispatch()
