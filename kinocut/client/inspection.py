"""Python client adapters for project-backed deterministic inspection."""

from __future__ import annotations

from typing import Any


class ClientInspectionMixin:
    """Ingest and inspect immutable project assets."""

    def ingest(
        self,
        project_dir: str,
        source_path: str,
        lineage: dict[str, Any] | None = None,
        usage_rights_status: str = "unknown",
        usage_rights_evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        from ..aivideo.surfaces import run_inspection_operation

        return run_inspection_operation(
            "ingest",
            project_dir,
            source_path=source_path,
            lineage=lineage,
            usage_rights_status=usage_rights_status,
            usage_rights_evidence_ref=usage_rights_evidence_ref,
        )

    def preflight(self, project_dir: str, asset_id: str) -> dict[str, Any]:
        from ..aivideo.surfaces import run_inspection_operation

        return run_inspection_operation("preflight", project_dir, asset_id=asset_id)

    def inspect_temporal(
        self,
        project_dir: str,
        asset_id: str,
        declared_regions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from ..aivideo.surfaces import run_inspection_operation

        return run_inspection_operation(
            "inspect_temporal",
            project_dir,
            asset_id=asset_id,
            declared_regions=declared_regions,
        )

    def record_motion_acceptance(
        self,
        report: dict[str, Any],
        *,
        input_path: str,
        reviewer_id: str,
        source_sha256: str,
        report_sha256: str,
        watched_intervals: list[dict[str, float]],
        dispositions: dict[str, str],
        verdict: str,
    ) -> dict[str, Any]:
        """Create an explicit source-bound whole-film human-review receipt."""
        from ..aivideo.inspection.motion_acceptance import record_motion_acceptance

        return record_motion_acceptance(
            report,
            input_path=input_path,
            reviewer_id=reviewer_id,
            source_sha256=source_sha256,
            report_sha256=report_sha256,
            watched_intervals=watched_intervals,
            dispositions=dispositions,
            verdict=verdict,
        )
