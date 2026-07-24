"""Review-gated packaging of approved shorts renders.

Packages each platform draft only after a current approve decision. Reads
render receipts from the plan; never posts or opens network connections.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from .captions import CaptionArtifact
from .package import package_approved_clip
from .package_models import PackageConfig, PackageLineage, ThumbnailSpec
from .shorts_plan import RenderRecord, ShortsPlan, load_shorts_plan, save_shorts_plan
from .shorts_review import resolve_approved_candidate

__all__ = ["package_approved_candidate"]


def _package_error(problem: str, *, code: str, cause: str, recovery: str) -> MCPVideoError:
    return MCPVideoError(
        f"Problem: {problem} Likely cause: {cause} Recovery: {recovery}",
        error_type="validation_error",
        code=code,
        suggested_action={"auto_fix": False, "description": recovery},
    )


def _caption_from_srt(path: str) -> CaptionArtifact:
    try:
        body = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise _package_error(
            "Editable captions from the render stage could not be read.",
            code="shorts_package_caption_missing",
            cause=str(exc),
            recovery="Re-run render_approved_candidate for this candidate, then package again.",
        ) from exc
    if not body.strip():
        raise _package_error(
            "Editable captions from the render stage are empty.",
            code="shorts_package_caption_empty",
            cause=f"file {path!r} has no caption text.",
            recovery="Re-run render_approved_candidate so captions.srt is regenerated.",
        )
    if not body.endswith("\n"):
        body = body + "\n"
    return CaptionArtifact(
        cues=(),
        srt_body=body,
        warnings=(),
        low_confidence_token_count=0,
        omitted_token_count=0,
    )


def _renders_for(plan: ShortsPlan, candidate_id: str) -> tuple[RenderRecord, ...]:
    return tuple(record for record in plan.renders if record.candidate_id == candidate_id)


def package_approved_candidate(
    plan_path_or_dir: str,
    *,
    candidate_id: str,
    package_root: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Package every platform draft for an approved candidate and persist the plan."""
    plan = load_shorts_plan(plan_path_or_dir)
    candidate = resolve_approved_candidate(plan, candidate_id)
    records = _renders_for(plan, candidate.candidate_id)
    if not records:
        raise _package_error(
            "No platform renders exist for this approved candidate.",
            code="shorts_package_render_required",
            cause=f"candidate {candidate.candidate_id!r} has no RenderRecord entries.",
            recovery="Call render_approved_candidate(...) first, then package.",
        )

    base = os.path.realpath(
        package_root or os.path.join(plan.output_dir, candidate.candidate_id, "packages")
    )
    os.makedirs(base, exist_ok=True)
    config = PackageConfig(overwrite_package=overwrite)
    emitted: list[dict[str, Any]] = []
    manifests: list[str] = list(plan.package_manifests)

    for record in records:
        package_dir = os.path.join(base, record.platform)
        result = package_approved_clip(
            package_dir=package_dir,
            vertical_video_path=record.output_path,
            caption_artifact=_caption_from_srt(record.editable_subtitles),
            candidate=candidate,
            thumbnail=ThumbnailSpec(image_path=record.thumbnail_path, timestamp=candidate.start),
            lineage=PackageLineage(
                candidate_id=candidate.candidate_id,
                review_decision_ref=plan.job_id,
                generation_lineage_ref=record.render_digest,
            ),
            config=config,
        )
        if result.manifest_path not in manifests:
            manifests.append(result.manifest_path)
        emitted.append(
            {
                "platform": record.platform,
                "package_root": result.package_root,
                "manifest_path": result.manifest_path,
                "asset_paths": list(result.asset_paths),
                "external_posting": False,
            }
        )

    revised = plan.model_copy(
        update={
            "package_manifests": tuple(manifests),
            "status": "packaged",
        }
    )
    save_shorts_plan(revised)
    return {
        "job_id": plan.job_id,
        "candidate_id": candidate.candidate_id,
        "status": "packaged",
        "packages": emitted,
        "external_posting": False,
    }
