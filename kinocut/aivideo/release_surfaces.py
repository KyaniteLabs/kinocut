"""Governed dispatch for release-artifact policy operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .wave3_surfaces import _error, _existing_project


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _run_review_package(
    project_dir: str, candidate_artifact: str, blocking_findings: tuple[str, ...]
) -> dict[str, Any]:
    from .review import review_package

    project = _existing_project(project_dir)
    package = review_package(project, candidate_artifact, blocking_findings=blocking_findings)
    return {"success": True, "operation": "review_package", "review_package": _dump(package)}


def _run_publish_gate(
    project_dir: str, candidate_artifact: str, blocking_findings: tuple[str, ...]
) -> dict[str, Any]:
    from .review import evaluate_publish_gate

    project = _existing_project(project_dir)
    result = evaluate_publish_gate(project, candidate_artifact, blocking_findings=blocking_findings)
    return {"success": True, "operation": "publish_gate", "publish_gate": _dump(result)}


def _run_review_decision(project_dir: str, decision: dict[str, Any]) -> dict[str, Any]:
    from ..contracts.review import ReviewDecision
    from .review import record_review_decision

    project = _existing_project(project_dir)
    payload = dict(decision)
    payload.setdefault("project_id", project.project_id)
    # publishability requires created_by to start with 'human'
    payload.setdefault("created_by", "human:review")
    contract = ReviewDecision.model_validate(payload)
    stored = record_review_decision(project, contract)
    return {"success": True, "operation": "review_decision", "review_decision": _dump(stored)}


def _run_learning_report(project_dir: str) -> dict[str, Any]:
    from .learning.report import project_learning_report

    project = _existing_project(project_dir)
    report = project_learning_report(project)
    return {"success": True, "operation": "learning_report", "learning_report": _dump(report)}


def _run_cost_ledger(project_dir: str) -> dict[str, Any]:
    from .learning.cost import cost_totals

    project = _existing_project(project_dir)
    totals = cost_totals(project)
    return {"success": True, "operation": "cost_ledger", "cost_totals": _dump(totals)}


def _run_recipe_capture(project_dir: str, recipe: dict[str, Any]) -> dict[str, Any]:
    from ..contracts.learning import WorkflowRecipe
    from .learning.recipes import record_workflow_recipe

    project = _existing_project(project_dir)
    payload = dict(recipe)
    payload.setdefault("project_id", project.project_id)
    payload.setdefault("created_by", "human:recipe")
    contract = WorkflowRecipe.model_validate(payload)
    stored = record_workflow_recipe(project, contract)  # idempotent by canonical digest
    return {"success": True, "operation": "recipe_capture", "workflow_recipe": _dump(stored)}


def _run_capabilities() -> dict[str, Any]:
    from ..capability_report import capability_report

    reports = capability_report(None)  # list[CapabilityReport] — probes current host
    return {"success": True, "operation": "capabilities", "capabilities": [_dump(r) for r in reports]}


def _run_benchmark_run() -> dict[str, Any]:
    from .benchmark import run_aivideo_benchmark

    receipt = run_aivideo_benchmark(None)
    return {"success": True, "operation": "benchmark_run", "benchmark": _dump(receipt)}


_RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "review_package": _run_review_package,
    "publish_gate": _run_publish_gate,
    "review_decision": _run_review_decision,
    "learning_report": _run_learning_report,
    "cost_ledger": _run_cost_ledger,
    "recipe_capture": _run_recipe_capture,
    "capabilities": _run_capabilities,
    "benchmark_run": _run_benchmark_run,
}


def run_release_operation(operation: str, **kwargs: Any) -> dict[str, Any]:
    """Run one release-artifact policy operation against canonical project records."""

    runner = _RUNNERS.get(operation)
    if runner is None:
        raise _error("Release operation is invalid", "release_operation_invalid")
    return runner(**kwargs)
