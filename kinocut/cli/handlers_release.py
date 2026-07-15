"""CLI adapters for release-artifact policy operations."""

from __future__ import annotations

from typing import Any

from .common import _parse_json_arg
from .runner import CommandRunner, _out


def _run(operation: str, args: Any, use_json: bool) -> None:
    from ..aivideo.release_surfaces import run_release_operation

    if operation in ("review_package", "publish_gate"):
        kwargs = {
            "project_dir": args.project_dir,
            "candidate_artifact": args.candidate_artifact,
            "blocking_findings": tuple(args.blocking_finding or ()),
        }
    elif operation == "review_decision":
        kwargs = {
            "project_dir": args.project_dir,
            "decision": _parse_json_arg(args.decision_json, "decision-json", use_json),
        }
    elif operation in ("learning_report", "cost_ledger"):
        kwargs = {"project_dir": args.project_dir}
    elif operation == "recipe_capture":
        kwargs = {
            "project_dir": args.project_dir,
            "recipe": _parse_json_arg(args.recipe_json, "recipe-json", use_json),
        }
    elif operation == "capabilities":
        kwargs = {}
    else:  # benchmark_run
        kwargs = {}
    _out(run_release_operation(operation, **kwargs), use_json)


def handle_release_commands(args: Any, *, use_json: bool) -> bool:
    runner = CommandRunner(args, use_json)
    runner.register("video-review-package", lambda a, out: _run("review_package", a, out))
    runner.register("video-publish-gate", lambda a, out: _run("publish_gate", a, out))
    runner.register("video-review-decision", lambda a, out: _run("review_decision", a, out))
    runner.register("video-learning-report", lambda a, out: _run("learning_report", a, out))
    runner.register("video-cost-ledger", lambda a, out: _run("cost_ledger", a, out))
    runner.register("video-recipe-capture", lambda a, out: _run("recipe_capture", a, out))
    runner.register("video-capabilities", lambda a, out: _run("capabilities", a, out))
    runner.register("video-benchmark-run", lambda a, out: _run("benchmark_run", a, out))
    return runner.dispatch()
