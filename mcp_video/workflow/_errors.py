"""Fail-closed error codes and helper for the agent workflow engine.

Every structural workflow validation failure raises an ``MCPVideoError`` with
one of these specific ``code`` values plus a ``suggested_action`` so an agent
can act on the failure without parsing prose.
"""

from __future__ import annotations

from typing import Any

from ..errors import MCPVideoError

INVALID_WORKFLOW_SPEC = "invalid_workflow_spec"
UNKNOWN_WORKFLOW_REF = "unknown_workflow_ref"
UNSUPPORTED_WORKFLOW_OP = "unsupported_workflow_op"
UNSAFE_WORKFLOW_SOURCE = "unsafe_workflow_source"
INVALID_WORKFLOW_PARAMS = "invalid_workflow_params"
INVALID_WORKFLOW_RECEIPT = "invalid_workflow_receipt"
RESUME_SPEC_MISMATCH = "resume_spec_mismatch"
INVALID_WORKFLOW_VARIANT = "invalid_workflow_variant"
RESUME_VARIANT_MISMATCH = "resume_variant_mismatch"
WORKFLOW_STEP_FAILED = "workflow_step_failed"

_DEFAULT_ACTIONS = {
    INVALID_WORKFLOW_SPEC: "Fix the workflow spec structure to match the documented job-spec schema and retry.",
    UNKNOWN_WORKFLOW_REF: (
        "Reference only declared @sources.<id> ids and @work/<name> outputs produced by strictly-earlier steps."
    ),
    UNSUPPORTED_WORKFLOW_OP: (
        "Use an allowlisted op: probe, trim, resize, convert, merge, add_text, composite_layers."
    ),
    UNSAFE_WORKFLOW_SOURCE: (
        "Use a relative path that stays inside the spec's workspace directory (no absolute paths or ../ escapes)."
    ),
    INVALID_WORKFLOW_PARAMS: "Remove params the target engine does not accept; see the op's engine signature.",
    INVALID_WORKFLOW_RECEIPT: (
        "Point at a receipt this project emitted (workflow render/plan or layer_plan); the file must be readable JSON."
    ),
    RESUME_SPEC_MISMATCH: (
        "Resume only against a receipt whose spec_hash matches the current spec; a changed spec is a different job "
        "(re-run without --resume to start fresh)."
    ),
    INVALID_WORKFLOW_VARIANT: (
        "Reference a declared variant id and use a supported override key "
        "(steps.<id>.params[.<name>], steps.<id>.output, outputs.<id>.path)."
    ),
    RESUME_VARIANT_MISMATCH: (
        "Resume only against a receipt for the SAME variant; render each variant into its own receipt "
        "and resume that variant's receipt."
    ),
    WORKFLOW_STEP_FAILED: (
        "A workflow step's engine raised an unexpected error; inspect the step's recorded error, fix the "
        "step inputs/params, and re-run (kept intermediates allow --resume)."
    ),
}


def workflow_error(
    message: str,
    code: str,
    *,
    suggested_action: dict[str, Any] | None = None,
    description: str | None = None,
) -> MCPVideoError:
    """Build a fail-closed ``MCPVideoError`` for a workflow validation failure."""
    if suggested_action is None:
        suggested_action = {
            "auto_fix": False,
            "description": description or _DEFAULT_ACTIONS.get(code, "Correct the workflow spec and retry."),
        }
    return MCPVideoError(
        message,
        error_type="validation_error",
        code=code,
        suggested_action=suggested_action,
    )
