"""mcp-video Python client — agent workflow-engine methods."""

from __future__ import annotations

from typing import Any


class ClientWorkflowMixin:
    """Agent workflow-engine operations mixin."""

    def workflow_validate(self, spec: str | dict) -> dict[str, Any]:
        """Validate a workflow job-spec without rendering any media.

        Args:
            spec: Path to a workflow job-spec JSON file, or the spec as a dict.

        Returns:
            A structured validation verdict (``{"valid": True, ...}``).

        Raises:
            MCPVideoError: on any structural violation (fail-closed).
        """
        from ..workflow import validate_workflow_spec

        if isinstance(spec, dict):
            import json
            import os
            import tempfile

            with tempfile.TemporaryDirectory(prefix="mcp_video_workflow_") as tmpdir:
                spec_path = os.path.join(tmpdir, "workflow.json")
                with open(spec_path, "w", encoding="utf-8") as handle:
                    json.dump(spec, handle)
                return validate_workflow_spec(spec_path)
        return validate_workflow_spec(spec)

    def workflow_plan(self, spec: str | dict, save_plan: str | None = None) -> dict[str, Any]:
        """Produce a no-render plan artifact for a workflow job-spec.

        Validates the spec first (fail-closed) and returns the dry-run plan:
        ordered op graph, per-source probe results + hashes where the file
        exists, output intents, variant summary, versions, and warnings. No
        media is rendered; only the optional ``save_plan`` JSON is written.

        Args:
            spec: Path to a workflow job-spec JSON file, or the spec as a dict.
            save_plan: Optional path to write the plan artifact as JSON.

        Returns:
            The plan artifact (``{"receipt_kind": "workflow_plan", ...}``).

        Raises:
            MCPVideoError: on any structural violation (fail-closed).
        """
        from ..workflow import plan_workflow

        if isinstance(spec, dict):
            import json
            import os
            import tempfile

            with tempfile.TemporaryDirectory(prefix="mcp_video_workflow_") as tmpdir:
                spec_path = os.path.join(tmpdir, "workflow.json")
                with open(spec_path, "w", encoding="utf-8") as handle:
                    json.dump(spec, handle)
                return plan_workflow(spec_path, save_plan)
        return plan_workflow(spec, save_plan)

    def workflow_render(
        self, spec: str | dict, resume_receipt: str | None = None, save_receipt: str | None = None
    ) -> dict[str, Any]:
        """Execute a workflow job-spec sequentially and return the receipt.

        Validates the spec first (fail-closed), runs each allowlisted op in spec
        order via the backing engine, hashing every consumed input and produced
        output, and returns a workflow receipt (``receipt_kind: "workflow"``).
        Intermediates are written to a per-run ``@work`` directory (cleaned on
        success, kept on failure). Only the optional ``save_receipt`` JSON is
        written outside the workspace's declared paths.

        Pass ``resume_receipt`` (a prior render receipt from a failed job whose
        intermediates were kept) to RESUME: the current spec_hash must equal the
        receipt's (else fail-closed), completed steps whose recorded input/output
        hashes still match are skipped, and the first step failing any check plus
        everything after it re-runs.

        Args:
            spec: Path to a workflow job-spec JSON file, or the spec as a dict.
            resume_receipt: Optional path to a prior render receipt to resume from.
            save_receipt: Optional path to write the workflow receipt as JSON.

        Returns:
            The workflow receipt (``{"receipt_kind": "workflow", ...}``).

        Raises:
            MCPVideoError: on any structural violation or failing step (fail-closed).
        """
        from ..workflow import render_workflow

        if isinstance(spec, dict):
            import json
            import os
            import tempfile

            with tempfile.TemporaryDirectory(prefix="mcp_video_workflow_") as tmpdir:
                spec_path = os.path.join(tmpdir, "workflow.json")
                with open(spec_path, "w", encoding="utf-8") as handle:
                    json.dump(spec, handle)
                return render_workflow(spec_path, resume_receipt, save_receipt)
        return render_workflow(spec, resume_receipt, save_receipt)

    def workflow_inspect(self, receipt: str) -> dict[str, Any]:
        """Summarize any project receipt with a read-only integrity check.

        Reads a workflow render receipt, a dry-run ``workflow_plan`` artifact, or a
        ``layer_plan`` receipt (legacy v1 without ``receipt_kind`` or v2) and
        returns a normalized inspection: kind (inferred from the ``tool`` field
        when ``receipt_kind`` is absent), schema_version, tool, versions, a status
        summary, a hash presence/integrity report (which recorded hashes still
        match on-disk files now), outputs, warnings, cleanup state, plus
        human-review pointers and known limitations. Nothing is rendered.

        Args:
            receipt: Path to the receipt JSON file to inspect.

        Returns:
            The normalized inspection dict.

        Raises:
            MCPVideoError: on a malformed/unreadable receipt (``invalid_workflow_receipt``).
        """
        from ..workflow import inspect_receipt

        return inspect_receipt(receipt)
