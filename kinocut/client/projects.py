"""Inspect project assets, evaluate AI video, and gate releases."""

from __future__ import annotations

from typing import Any


def _run_aivideo(operation: str, **kwargs: Any) -> dict[str, Any]:
    from ..aivideo.wave3_surfaces import run_wave3_operation

    return run_wave3_operation(operation, **kwargs)


def _run_release(operation: str, **kwargs: Any) -> dict[str, Any]:
    from ..aivideo.release_surfaces import run_release_operation

    return run_release_operation(operation, **kwargs)


class ClientProjectsMixin:
    """Inspect project assets, evaluate AI video, and gate releases."""

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

    def verdict(self, project_dir: str, verdict: dict[str, Any]) -> dict[str, Any]:
        return _run_aivideo("verdict", project_dir=project_dir, verdict=verdict)

    def acceptance_eval(
        self,
        project_dir: str,
        acceptance_spec_id: str,
        verdict_ids: list[str],
    ) -> dict[str, Any]:
        return _run_aivideo(
            "acceptance_eval",
            project_dir=project_dir,
            acceptance_spec_id=acceptance_spec_id,
            verdict_ids=verdict_ids,
        )

    def body_swap(
        self,
        project_dir: str,
        video_source: str,
        audio_source: str,
        output_path: str,
        *,
        duration_policy: str | None = None,
        authorization_decision_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return _run_aivideo(
            "body_swap",
            project_dir=project_dir,
            video_source=video_source,
            audio_source=audio_source,
            output_path=output_path,
            duration_policy=duration_policy,
            authorization_decision_ids=authorization_decision_ids or [],
        )

    def salvage(
        self,
        project_dir: str,
        source_asset_id: str,
        recipe: str,
        policy: dict[str, Any],
        acceptance_spec_id: str,
        *,
        authorization_decision_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return _run_aivideo(
            "salvage",
            project_dir=project_dir,
            source_asset_id=source_asset_id,
            recipe=recipe,
            policy=policy,
            acceptance_spec_id=acceptance_spec_id,
            authorization_decision_ids=authorization_decision_ids or [],
        )

    def review_package(
        self,
        project_dir: str,
        candidate_artifact: str,
        blocking_findings: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return _run_release(
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
        return _run_release(
            "publish_gate",
            project_dir=project_dir,
            candidate_artifact=candidate_artifact,
            blocking_findings=blocking_findings,
        )

    def review_decision(self, project_dir: str, decision: dict[str, Any]) -> dict[str, Any]:
        return _run_release("review_decision", project_dir=project_dir, decision=decision)

    def learning_report(self, project_dir: str) -> dict[str, Any]:
        return _run_release("learning_report", project_dir=project_dir)

    def cost_ledger(self, project_dir: str) -> dict[str, Any]:
        return _run_release("cost_ledger", project_dir=project_dir)

    def recipe_capture(self, project_dir: str, recipe: dict[str, Any]) -> dict[str, Any]:
        return _run_release("recipe_capture", project_dir=project_dir, recipe=recipe)

    def capabilities(self) -> dict[str, Any]:
        return _run_release("capabilities")

    def benchmark_run(self) -> dict[str, Any]:
        return _run_release("benchmark_run")
