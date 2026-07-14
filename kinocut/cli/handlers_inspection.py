"""CLI adapters for project-backed inspection."""

from __future__ import annotations

from typing import Any

from .common import _parse_json_arg
from .runner import CommandRunner, _out


def handle_inspection_commands(args: Any, *, use_json: bool) -> bool:
    runner = CommandRunner(args, use_json)

    def _run(operation: str, a: Any, output_json: bool) -> None:
        from ..aivideo.surfaces import run_inspection_operation

        if operation == "ingest":
            lineage = (
                _parse_json_arg(a.lineage_json, "lineage-json", output_json) if a.lineage_json is not None else None
            )
            kwargs = {
                "source_path": a.source_path,
                "lineage": lineage,
                "usage_rights_status": a.usage_rights_status,
                "usage_rights_evidence_ref": a.usage_rights_evidence_ref,
            }
        else:
            regions = (
                _parse_json_arg(a.regions_json, "regions-json", output_json)
                if operation == "inspect_temporal" and a.regions_json is not None
                else None
            )
            kwargs = {"asset_id": a.asset_id}
            if operation == "inspect_temporal":
                kwargs["declared_regions"] = regions
        _out(run_inspection_operation(operation, a.project_dir, **kwargs), output_json)

    runner.register("video-ingest", lambda a, out: _run("ingest", a, out))
    runner.register("video-preflight", lambda a, out: _run("preflight", a, out))
    runner.register("video-inspect-temporal", lambda a, out: _run("inspect_temporal", a, out))
    return runner.dispatch()
