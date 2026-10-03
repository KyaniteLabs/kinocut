"""CLI delegation to the existing strict human motion-review validator."""

from __future__ import annotations

from typing import Any

from ..json_artifacts import load_json_artifact
from ..limits import (
    MAX_MOTION_DISPOSITIONS_JSON_BYTES,
    MAX_MOTION_REPORT_JSON_BYTES,
    MAX_MOTION_WATCHED_INTERVALS_JSON_BYTES,
)
from .common import _parse_json_arg
from .runner import CommandRunner, _out


def _review_artifact(args: Any, name: str, max_bytes: int, use_json: bool) -> Any:
    path = getattr(args, name + "_file", None)
    if path is not None:
        return load_json_artifact(path, max_bytes=max_bytes, error_code="invalid_json")
    return _parse_json_arg(getattr(args, name + "_json"), name.replace("_", "-") + "-json", use_json)


def _record(args: Any, use_json: bool) -> None:
    from ..aivideo.inspection.motion_acceptance import record_motion_acceptance

    report = _review_artifact(args, "report", MAX_MOTION_REPORT_JSON_BYTES, use_json)
    receipt = record_motion_acceptance(
        report,
        input_path=args.input_path,
        reviewer_id=args.reviewer_id,
        source_sha256=args.source_sha256,
        report_sha256=args.report_sha256,
        watched_intervals=_review_artifact(
            args, "watched_intervals", MAX_MOTION_WATCHED_INTERVALS_JSON_BYTES, use_json
        ),
        dispositions=_review_artifact(args, "dispositions", MAX_MOTION_DISPOSITIONS_JSON_BYTES, use_json),
        verdict=args.verdict,
    )
    _out(receipt, use_json, json_transform=lambda value: {"receipt": value})


def handle_motion_acceptance_commands(args: Any, *, use_json: bool) -> bool:
    runner = CommandRunner(args, use_json)
    runner.register("record-motion-acceptance", _record)
    return runner.dispatch()
