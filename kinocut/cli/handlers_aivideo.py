"""CLI adapters for governed Wave 3 AI-video operations."""

from __future__ import annotations

from typing import Any

from .common import _parse_json_arg
from .runner import CommandRunner, _out


def _run(operation: str, args: Any, use_json: bool) -> None:
    from ..aivideo.wave3_surfaces import run_wave3_operation

    if operation == "verdict":
        kwargs = {
            "project_dir": args.project_dir,
            "verdict": _parse_json_arg(args.verdict_json, "verdict-json", use_json),
        }
    elif operation == "acceptance_eval":
        kwargs = {
            "project_dir": args.project_dir,
            "acceptance_spec_id": args.acceptance_spec_id,
            "verdict_ids": args.verdict_id,
        }
    elif operation == "body_swap":
        kwargs = {
            "project_dir": args.project_dir,
            "video_source": args.video_source,
            "audio_source": args.audio_source,
            "output_path": args.output_path,
            "duration_policy": args.duration_policy,
            "authorization_decision_ids": args.authorization_decision_id,
        }
    else:
        kwargs = {
            "project_dir": args.project_dir,
            "source_asset_id": args.source_asset_id,
            "recipe": args.recipe,
            "policy": _parse_json_arg(args.policy_json, "policy-json", use_json),
            "acceptance_spec_id": args.acceptance_spec_id,
            "authorization_decision_ids": args.authorization_decision_id,
        }
    _out(run_wave3_operation(operation, **kwargs), use_json)


def handle_aivideo_commands(args: Any, *, use_json: bool) -> bool:
    runner = CommandRunner(args, use_json)
    runner.register("video-verdict", lambda a, out: _run("verdict", a, out))
    runner.register("video-acceptance-eval", lambda a, out: _run("acceptance_eval", a, out))
    runner.register("video-body-swap", lambda a, out: _run("body_swap", a, out))
    runner.register("video-salvage", lambda a, out: _run("salvage", a, out))
    return runner.dispatch()
