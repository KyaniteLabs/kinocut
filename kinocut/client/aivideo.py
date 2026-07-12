"""Python client adapters for governed Wave 3 AI-video operations."""

from __future__ import annotations

from typing import Any


def _run(operation: str, **kwargs: Any) -> dict[str, Any]:
    from ..aivideo.wave3_surfaces import run_wave3_operation

    return run_wave3_operation(operation, **kwargs)


class ClientAIVideoMixin:
    """Governed verdict, acceptance, body-swap, and salvage operations."""

    def verdict(self, project_dir: str, verdict: dict[str, Any]) -> dict[str, Any]:
        return _run("verdict", project_dir=project_dir, verdict=verdict)

    def acceptance_eval(
        self,
        project_dir: str,
        acceptance_spec_id: str,
        verdict_ids: list[str],
    ) -> dict[str, Any]:
        return _run(
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
        return _run(
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
        return _run(
            "salvage",
            project_dir=project_dir,
            source_asset_id=source_asset_id,
            recipe=recipe,
            policy=policy,
            acceptance_spec_id=acceptance_spec_id,
            authorization_decision_ids=authorization_decision_ids or [],
        )
