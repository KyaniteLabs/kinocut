"""Python client adapters for release-artifact policy operations."""

from __future__ import annotations

from typing import Any


def _run(operation: str, **kwargs: Any) -> dict[str, Any]:
    from ..aivideo.release_surfaces import run_release_operation

    return run_release_operation(operation, **kwargs)


class ClientReleaseMixin:
    """Review, publish-gate, learning, cost, recipe, capability, benchmark operations."""

    def review_package(
        self,
        project_dir: str,
        candidate_artifact: str,
        blocking_findings: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return _run(
            "review_package",
            project_dir=project_dir,
            candidate_artifact=candidate_artifact,
            blocking_findings=blocking_findings,
        )

    def publish_gate(
        self,
        project_dir: str,
        candidate_artifact: str,
        blocking_findings: tuple[str, ...],
    ) -> dict[str, Any]:
        return _run(
            "publish_gate",
            project_dir=project_dir,
            candidate_artifact=candidate_artifact,
            blocking_findings=blocking_findings,
        )

    def review_decision(self, project_dir: str, decision: dict[str, Any]) -> dict[str, Any]:
        return _run("review_decision", project_dir=project_dir, decision=decision)

    def learning_report(self, project_dir: str) -> dict[str, Any]:
        return _run("learning_report", project_dir=project_dir)

    def cost_ledger(self, project_dir: str) -> dict[str, Any]:
        return _run("cost_ledger", project_dir=project_dir)

    def recipe_capture(self, project_dir: str, recipe: dict[str, Any]) -> dict[str, Any]:
        return _run("recipe_capture", project_dir=project_dir, recipe=recipe)

    def capabilities(self) -> dict[str, Any]:
        return _run("capabilities")

    def benchmark_run(self) -> dict[str, Any]:
        return _run("benchmark_run")
