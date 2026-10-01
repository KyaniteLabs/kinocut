"""Python client adapter for local time and cost-unit estimates."""

from __future__ import annotations

from typing import Any


class ClientEstimatesMixin:
    """Expose the same local heuristic as MCP and CLI estimation."""

    def estimate_operation(self, operation: str, duration_seconds: float, complexity: float = 1.0) -> dict[str, Any]:
        """Estimate local wall time and dimensionless units, without rendering or billing."""
        from ..te import estimate_operation

        return estimate_operation(operation, duration_seconds=duration_seconds, complexity=complexity)
