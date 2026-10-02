"""CLI delegation to the existing strict human motion-review validator."""

from __future__ import annotations

from typing import Any

from ..json_artifacts import load_json_artifact
from ..limits import MAX_CLI_JSON_ARTIFACT_BYTES
from .common import _parse_json_arg
from .runner import CommandRunner, _out


def _record(args: Any, use_json: bool) -> None:
    from ..aivideo.inspection.motion_acceptance import record_motion_acceptance

    report = (
        load_json_artifact(args.report_file, max_bytes=MAX_CLI_JSON_ARTIFACT_BYTES, error_code="invalid_json")
        if args.report_file is not None
        else _parse_json_arg(args.report_json, "report-json", use_json)
    )
    receipt = record_motion_acceptance(
        report,
        input_path=args.input_path,
        reviewer_id=args.reviewer_id,
        source_sha256=args.source_sha256,
        report_sha256=args.report_sha256,
        watched_intervals=_parse_json_arg(args.watched_intervals_json, "watched-intervals-json", use_json),
        dispositions=_parse_json_arg(args.dispositions_json, "dispositions-json", use_json),
        verdict=args.verdict,
    )
    _out(receipt, use_json, json_transform=lambda value: {"receipt": value})


def handle_motion_acceptance_commands(args: Any, *, use_json: bool) -> bool:
    runner = CommandRunner(args, use_json)
    runner.register("record-motion-acceptance", _record)
    return runner.dispatch()
