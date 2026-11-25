"""Review-gated packaging of approved shorts renders.

Packages each platform draft only after a current approve decision. Reads
render receipts from the plan; never posts or opens network connections.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..publication import anchored_tree
from .captions import CaptionArtifact
from .package import package_approved_clip
from .package_models import PackageLineage, ThumbnailSpec
from .shorts_plan import RenderRecord, ShortsPlan, ShortsPlanStatus, load_shorts_plan, save_shorts_plan
from .shorts_render import expected_render_digests
from .shorts_review import CandidateMoment, resolve_approved_candidate
from ..validation_errors import exception_kind, likely_cause, own_reason

__all__ = ["package_approved_candidate"]


def _package_error(problem: str, *, code: str, cause: str, recovery: str) -> MCPVideoError:
    return MCPVideoError(
        f"Problem: {problem} Likely cause: {likely_cause(cause)} Recovery: {recovery}",
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
            cause=own_reason(exception_kind(exc)),
            recovery="Re-run render_approved_candidate for this candidate, then package again.",
        ) from exc
    if not body.strip():
        raise _package_error(
            "Editable captions from the render stage are empty.",
            code="shorts_package_caption_empty",
            cause=own_reason("file has no caption text."),
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


def _gate_package_media(path: str) -> dict[str, Any]:
    """Gate the exact copied render that will be published."""
    from ..defaults import DEFAULT_QUALITY_GATE_SCORE
    from ..quality_guardrails import assert_quality

    return assert_quality(path, min_score=DEFAULT_QUALITY_GATE_SCORE)


def _require_renders_of_the_approved_cut(
    plan: ShortsPlan, candidate: CandidateMoment, records: tuple[RenderRecord, ...]
) -> None:
    """A render made for an earlier revision must never ship under the current approval."""
    expected = expected_render_digests(plan, candidate)
    stale = tuple(record.platform for record in records if record.render_digest != expected.get(record.platform))
    if stale:
        raise _package_error(
            "Platform renders do not match the approved cut.",
            code="shorts_package_render_stale",
            cause=own_reason(f"render digests for {', '.join(stale)} predate the current approved revision."),
            recovery="Re-run render_approved_candidate(...) for the approved cut, then package again.",
        )


def _package_platform(
    record: RenderRecord,
    *,
    candidate: CandidateMoment,
    base: Path,
    stage: Path,
    review_decision_ref: str,
) -> dict[str, Any]:
    """Assemble and gate one private platform package."""
    root = base / record.platform
    result = package_approved_clip(
        package_dir=str(stage / record.platform),
        logical_output_root=str(root),
        vertical_video_path=record.output_path,
        expected_video_sha256=record.output_sha256,
        caption_artifact=_caption_from_srt(record.editable_subtitles),
        candidate=candidate,
        thumbnail=ThumbnailSpec(image_path=record.thumbnail_path, timestamp=candidate.start),
        lineage=PackageLineage(
            candidate_id=candidate.candidate_id,
            review_decision_ref=review_decision_ref,
            generation_lineage_ref=record.render_digest,
        ),
    )
    manifest_path = Path(result.manifest_path)
    video = next(asset.relative_path for asset in result.manifest.assets if asset.role == "vertical_video")
    gate = _gate_package_media(str(Path(result.package_root, video)))
    if "video" in gate:
        gate = {**gate, "video": str(root / video)}
    return {
        "platform": record.platform,
        "package_root": str(root),
        "manifest_path": str(root / manifest_path.name),
        "asset_paths": [str(root / Path(path).name) for path in result.asset_paths],
        "external_posting": False,
        "quality": gate,
    }


def package_approved_candidate(
    plan_path_or_dir: str,
    *,
    candidate_id: str,
    package_root: str | None = None,
    overwrite: bool = False,
    allow_fail: bool = False,
) -> dict[str, Any]:
    """Package every platform draft after QC. Legacy ``allow_fail`` cannot bypass QC."""
    plan = load_shorts_plan(plan_path_or_dir)
    candidate = resolve_approved_candidate(plan, candidate_id)
    records = _renders_for(plan, candidate.candidate_id)
    if not records:
        raise _package_error(
            "No platform renders exist for this approved candidate.",
            code="shorts_package_render_required",
            cause=own_reason("the approved candidate has no RenderRecord entries."),
            recovery="Call render_approved_candidate(...) first, then package.",
        )

    requested = package_root or os.path.join(plan.output_dir, candidate.candidate_id, "packages")

    _require_renders_of_the_approved_cut(plan, candidate, records)
    requested_path = Path(requested).expanduser().absolute()
    base = requested_path.parent.resolve() / requested_path.name
    output_root = Path(plan.output_dir).expanduser().resolve()
    if base == output_root or not base.is_relative_to(output_root) or base.name == "..":
        raise _package_error(
            "Package root escapes plan.output_dir.",
            code="unsafe_path",
            cause=own_reason("the requested package_root resolves outside plan.output_dir."),
            recovery="Pass a dedicated package_root under the plan output directory.",
        )
    with anchored_tree(base, overwrite=overwrite) as stage:
        emitted = [
            _package_platform(record, candidate=candidate, base=base, stage=stage, review_decision_ref=plan.job_id)
            for record in records
        ]
    manifests = dict.fromkeys((*plan.package_manifests, *(item["manifest_path"] for item in emitted)))

    revised = plan.model_copy(
        update={
            "package_manifests": tuple(manifests),
            "status": ShortsPlanStatus.PACKAGED,
        }
    )
    save_shorts_plan(revised)
    return {
        "job_id": plan.job_id,
        "candidate_id": candidate.candidate_id,
        "status": ShortsPlanStatus.PACKAGED,
        "packages": emitted,
        "external_posting": False,
    }
