"""Stable, fail-closed errors for the dedicated rescue pipeline."""

from __future__ import annotations

from ..errors import MCPVideoError

INVALID_RESCUE_INPUT = "invalid_rescue_input"
INVALID_RESCUE_PLAN = "invalid_rescue_plan"
INVALID_RESCUE_RECEIPT = "invalid_rescue_receipt"
RESCUE_SOURCE_MISMATCH = "rescue_source_mismatch"
RESCUE_PLAN_MISMATCH = "rescue_plan_mismatch"
RESCUE_POLICY_VIOLATION = "rescue_policy_violation"
RESCUE_APPROVAL_INVALID = "rescue_approval_invalid"
RESCUE_DEPENDENCY_MISMATCH = "rescue_dependency_mismatch"
RESCUE_INTERMEDIATE_MISMATCH = "rescue_intermediate_mismatch"
RESCUE_CANCELLED = "rescue_cancelled"
RESCUE_VERIFICATION_FAILED = "rescue_verification_failed"
UNSAFE_RESCUE_OUTPUT = "unsafe_rescue_output"

_DEFAULT_ACTIONS = {
    INVALID_RESCUE_INPUT: "Use one readable local media file with a video stream and retry planning.",
    INVALID_RESCUE_PLAN: "Use an unmodified rescue plan emitted by video_rescue_plan.",
    INVALID_RESCUE_RECEIPT: "Use a readable rescue plan or render receipt emitted by MCP Video.",
    RESCUE_SOURCE_MISMATCH: "Restore the exact planned source or create a new rescue plan for the changed file.",
    RESCUE_PLAN_MISMATCH: "Use the original unmodified plan or run video_rescue_plan again.",
    RESCUE_POLICY_VIOLATION: "Remove the blocked action and use only operations allowed by the plan policy.",
    RESCUE_APPROVAL_INVALID: "Approve only safe_repair ids present in this exact rescue plan.",
    RESCUE_DEPENDENCY_MISMATCH: "Restore the planned local executor versions or create a new plan.",
    RESCUE_INTERMEDIATE_MISMATCH: "Discard the altered intermediate and start a fresh render from the plan.",
    RESCUE_CANCELLED: "Resume with the recorded receipt or start a fresh render when ready.",
    RESCUE_VERIFICATION_FAILED: "Inspect the quarantined receipt and correct the failed verification checks.",
    UNSAFE_RESCUE_OUTPUT: "Choose an output path confined to the rescue workspace that does not overwrite the source.",
}


def rescue_error(message: str, code: str, description: str | None = None) -> MCPVideoError:
    """Build a structured rescue validation error with a stable code."""

    return MCPVideoError(
        message,
        error_type="validation_error",
        code=code,
        suggested_action={
            "auto_fix": False,
            "description": description or _DEFAULT_ACTIONS[code],
        },
    )
