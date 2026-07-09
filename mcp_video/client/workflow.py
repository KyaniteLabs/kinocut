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
