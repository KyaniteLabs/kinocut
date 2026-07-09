"""Workflow-engine MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp
from .workflow import plan_workflow, render_workflow, validate_workflow_spec


@mcp.tool()
@_safe_tool
def video_workflow_validate(spec_path: str) -> dict[str, Any]:
    """Validate an agent workflow job-spec without rendering any media.

    Runs the fail-closed structural validator over the JSON job-spec at
    ``spec_path``: op allowlist (probe|trim|resize|convert|merge|add_text),
    symbolic ``@ref`` resolution (@sources.<id>, @work/<name>, @outputs.<id>),
    backward-reference-only ordering (a step may reference @work outputs from
    strictly-earlier steps only), per-op param introspection, and
    workspace-confined path safety (absolute paths and ../ / symlink escapes
    fail closed).

    Returns a structured verdict (``{"valid": true, ...}``) on success. On any
    structural violation it fails closed with a specific error ``code``
    (``invalid_workflow_spec``, ``unknown_workflow_ref``,
    ``unsupported_workflow_op``, ``unsafe_workflow_source``,
    ``invalid_workflow_params``).

    Args:
        spec_path: Absolute path to the workflow job-spec JSON file.
    """
    return _result(validate_workflow_spec(spec_path))


@mcp.tool()
@_safe_tool
def video_workflow_plan(spec_path: str, save_plan: str | None = None) -> dict[str, Any]:
    """Produce a no-render plan for an agent workflow job-spec.

    Validates the spec first (fail-closed) and then builds a dry-run plan
    artifact WITHOUT rendering any media: the ordered operation graph, per-source
    ffprobe results (duration/resolution/codec) and sha256 content hashes where
    the source file exists, declared output intents, a variant-expansion summary,
    tool + FFmpeg versions, and warnings for runtime concerns that are not
    structural errors (e.g. a source file that does not exist yet). The only file
    written is the optional plan JSON at ``save_plan``; paths inside the artifact
    are workspace-relative.

    Returns the plan artifact on success. On a structurally invalid spec it fails
    closed with a specific error ``code`` (same codes as ``video_workflow_validate``).

    Args:
        spec_path: Absolute path to the workflow job-spec JSON file.
        save_plan: Optional path to write the plan artifact as JSON.
    """
    return _result(plan_workflow(spec_path, save_plan))


@mcp.tool()
@_safe_tool
def video_workflow_render(spec_path: str, save_receipt: str | None = None) -> dict[str, Any]:
    """Execute an agent workflow job-spec and return a provenance receipt.

    Validates the spec first (fail-closed), then runs each allowlisted op
    (probe|trim|resize|convert|merge|add_text) SEQUENTIALLY in spec order via the
    backing engine functions. Intermediates are written to a per-run ``@work``
    directory unique to this invocation and cleaned on success (kept on failure);
    final media lands at the declared ``@outputs`` paths.

    Returns a workflow receipt (``receipt_kind: "workflow"``) capturing tool +
    FFmpeg versions, the spec hash, per-source probes/hashes, per-step status with
    real sha256 hashes of every consumed input and produced output, the cleanup
    manifest, and the determinism-scope caveat. On the first failing step it fails
    closed: the failure is recorded on the receipt (still written to
    ``save_receipt`` when given) and surfaced as a structured error.

    Args:
        spec_path: Absolute path to the workflow job-spec JSON file.
        save_receipt: Optional path to write the workflow receipt as JSON.
    """
    return _result(render_workflow(spec_path, save_receipt))
