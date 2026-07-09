"""Workflow-engine MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp
from .workflow import plan_workflow, validate_workflow_spec


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
