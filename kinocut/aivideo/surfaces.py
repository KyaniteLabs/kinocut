"""One shared public boundary for Wave-2 inspection operations."""

from __future__ import annotations

import json
import hashlib
import logging
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from kinocut.aivideo.ingest import ingest_project_asset
from kinocut.aivideo.inspection.manifest import (
    ArtifactRef,
    InspectionPackage,
    persist_inspection_package,
)
from kinocut.aivideo.inspection.motion_strip import build_motion_strip
from kinocut.aivideo.inspection.providers import (
    VISUAL_CAPABILITIES,
    analyze_optional_visual_findings,
)
from kinocut.aivideo.inspection.samplers import (
    DeclaredRegion,
    extract_region_crops,
    extract_sampled_frames,
    sample_decoded_timestamps,
)
from kinocut.aivideo.inspection.temporal_checks import inspect_temporal_media
from kinocut.aivideo.preflight import PreflightReport, run_preflight
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.asset import AssetRecord, GenerationLineage, UsageRightsStatus
from kinocut.contracts.defect import DefectFinding
from kinocut.defaults import (
    DEFAULT_INSPECTION_PREVIEW_CRF,
    DEFAULT_INSPECTION_PREVIEW_MAX_SECONDS,
    DEFAULT_INSPECTION_PREVIEW_PRESET,
    DEFAULT_INSPECTION_PREVIEW_WIDTH,
)
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg_bytes
from kinocut.limits import (
    MAX_INSPECTION_DECLARED_REGIONS,
    MAX_INSPECTION_LINEAGE_JSON_BYTES,
)
from kinocut.projectstore import Project, layout, open_project, store
from kinocut.projectstore.artifacts import install_bytes

Operation = Literal["ingest", "preflight", "inspect_temporal"]
logger = logging.getLogger(__name__)


def _error(message: str, code: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _existing_project(project_dir: str) -> Project:
    root = Path(project_dir)
    store_root = root / ".kinocut"
    if not root.is_dir() or root.is_symlink() or not store_root.is_dir() or store_root.is_symlink():
        raise _error("inspection project does not exist", "inspection_project_missing")
    return open_project(root)


def _active_asset(project: Project, asset_id: str | None) -> AssetRecord:
    if asset_id is None:
        raise _error("inspection requires an asset id", "inspection_asset_required")
    records = [item for item in store.read_records(project, "asset_record") if isinstance(item, AssetRecord)]
    superseded = {item.supersedes for item in records if item.supersedes is not None}
    matches = [item for item in records if item.asset_id == asset_id and item.record_id not in superseded]
    if not matches:
        raise _error("inspection asset was not found", "inspection_asset_not_found")
    if len(matches) != 1:
        raise _error("inspection asset state is ambiguous", "inspection_asset_ambiguous")
    return matches[0]


def _media_path(project: Project, asset: AssetRecord) -> Path:
    target = store.safe_target(project, PurePosixPath(asset.original_location))
    if not target.is_file():
        raise MCPVideoError(
            "inspection original is missing",
            error_type="store_error",
            code="inspection_original_missing",
        )
    return target


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _asset_envelope(operation: Operation, asset: AssetRecord) -> dict[str, Any]:
    return {
        "success": True,
        "operation": operation,
        "asset_id": asset.asset_id,
        "asset": _json(asset),
    }


def _lineage(value: GenerationLineage | dict[str, Any] | None) -> GenerationLineage | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, default=lambda item: item.model_dump(mode="json"))
        if len(encoded.encode("utf-8")) > MAX_INSPECTION_LINEAGE_JSON_BYTES:
            raise ValueError("lineage exceeds limit")
        return GenerationLineage.model_validate(value)
    except Exception as exc:
        logger.warning("inspection lineage validation failed: %s", type(exc).__name__)
        raise _error("inspection lineage is invalid", "inspection_lineage_invalid") from exc


def _rights(value: UsageRightsStatus | str) -> UsageRightsStatus:
    try:
        return UsageRightsStatus(value)
    except (TypeError, ValueError) as exc:
        raise _error("inspection rights status is invalid", "inspection_rights_invalid") from exc


def _regions(
    value: list[dict[str, Any]] | tuple[DeclaredRegion, ...] | None,
) -> tuple[DeclaredRegion, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > MAX_INSPECTION_DECLARED_REGIONS:
        raise _error("inspection regions are invalid", "inspection_regions_invalid")
    try:
        return tuple(DeclaredRegion.model_validate(item) for item in value)
    except Exception as exc:
        raise _error("inspection regions are invalid", "inspection_regions_invalid") from exc


def _preview_args(media: Path, *, muted: bool, duration: float) -> list[str]:
    args = [
        "-i",
        str(media),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-t",
        f"{min(duration, DEFAULT_INSPECTION_PREVIEW_MAX_SECONDS):.6f}",
        "-vf",
        (f"scale=w='max(2,trunc(min({DEFAULT_INSPECTION_PREVIEW_WIDTH},iw)/2)*2)':h=-2"),
        "-c:v",
        "libx264",
        "-preset",
        DEFAULT_INSPECTION_PREVIEW_PRESET,
        "-crf",
        str(DEFAULT_INSPECTION_PREVIEW_CRF),
        "-pix_fmt",
        "yuv420p",
    ]
    args.extend(["-an"] if muted else ["-c:a", "aac"])
    return [*args, "-movflags", "+frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]


def _preview(project: Project, media: Path, *, muted: bool, duration: float) -> ArtifactRef:
    installed = install_bytes(
        project,
        _run_ffmpeg_bytes(_preview_args(media, muted=muted, duration=duration)),
        name="muted_preview.mp4" if muted else "preview.mp4",
    )
    return ArtifactRef(
        artifact_id=installed.artifact_id,
        kind="muted_preview" if muted else "preview",
        location=installed.location,
    )


def _preflight_asset(project: Project, asset: AssetRecord) -> AssetRecord:
    if asset.preflight_artifact_id is not None:
        _preflight_ref(project, asset)
        return asset
    try:
        return run_preflight(project, asset)
    except MCPVideoError as exc:
        if exc.code not in {"invalid_record", "preflight_asset_mismatch"}:
            raise
        with store._project_lock(project):
            current = _active_asset(project, asset.asset_id)
            _preflight_ref(project, current)
            return current


def _preflight_ref(project: Project, asset: AssetRecord) -> tuple[ArtifactRef, PreflightReport]:
    artifact_id = asset.preflight_artifact_id
    if artifact_id is None:
        raise MCPVideoError(
            "inspection preflight artifact is missing",
            error_type="store_error",
            code="inspection_preflight_missing",
        )
    relative = layout.artifact_relative_path(artifact_id, "preflight.json")
    target = store.safe_target(project, relative)
    try:
        content = target.read_bytes()
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        if expected != artifact_id:
            raise ValueError("preflight artifact digest mismatch")
        report = PreflightReport.model_validate_json(content)
    except Exception as exc:
        logger.warning("inspection preflight artifact invalid: %s", type(exc).__name__)
        raise MCPVideoError(
            "inspection preflight artifact is invalid",
            error_type="store_error",
            code="inspection_preflight_invalid",
        ) from exc
    return (
        ArtifactRef(
            artifact_id=artifact_id,
            kind="technical_metadata",
            location=str(relative),
        ),
        report,
    )


def _measurement_artifact(project: Project, result: Any) -> ArtifactRef:
    payload = json.dumps(
        {
            "decoded_timestamps": result.decoded_timestamps,
            "opening_closing_difference": result.opening_closing_difference,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    installed = install_bytes(project, payload, name="frame_differences.json")
    return ArtifactRef(
        artifact_id=installed.artifact_id,
        kind="frame_difference_measurements",
        location=installed.location,
    )


def _persist_findings(project: Project, findings: tuple[DefectFinding, ...]) -> tuple[str, ...]:
    with store._project_lock(project):
        existing = {
            item.record_id for item in store.read_records(project, "defect_finding") if isinstance(item, DefectFinding)
        }
        ids: list[str] = []
        for finding in findings:
            record_id = finding.record_id or canonical_record_id(finding)
            if record_id not in existing:
                record_id = store.append_record_locked(project, finding).record_id
            if record_id is None:
                raise MCPVideoError(
                    "inspection finding identity is missing",
                    error_type="store_error",
                    code="inspection_finding_invalid",
                )
            existing.add(record_id)
            ids.append(record_id)
    return tuple(ids)


def _inspect(
    project: Project,
    asset: AssetRecord,
    declared_regions: tuple[DeclaredRegion, ...],
) -> dict[str, Any]:
    asset = _preflight_asset(project, asset)
    media = _media_path(project, asset)
    technical, _validated_preflight = _preflight_ref(project, asset)
    samples = sample_decoded_timestamps(str(media))
    frames = extract_sampled_frames(project, str(media), samples)
    region_crops = extract_region_crops(project, str(media), samples, declared_regions) if declared_regions else ()
    strip = build_motion_strip(project, frames)
    temporal = inspect_temporal_media(str(media), target_id=asset.asset_id, project_id=asset.project_id)
    finding_ids = _persist_findings(project, temporal.findings)
    measurements = _measurement_artifact(project, temporal)
    preview = _preview(project, media, muted=False, duration=temporal.playable_end)
    muted_preview = _preview(project, media, muted=True, duration=temporal.playable_end)
    base = InspectionPackage(
        source_asset_id=asset.asset_id,
        technical_metadata=technical,
        preview=preview,
        muted_preview=muted_preview,
        motion_strip=strip,
        sampled_frames=frames,
        region_crops=region_crops,
        frame_difference_measurements=(measurements,),
        findings=finding_ids,
    )
    analyses = tuple(
        analyze_optional_visual_findings(
            base,
            playable_end=temporal.playable_end,
            capability_id=capability,
            provider_id=None,
            project_id=asset.project_id,
            created_by="tool:inspection_surface",
        )
        for capability in VISUAL_CAPABILITIES
    )
    package = base.model_copy(update={"capabilities": tuple(item.capability for item in analyses)})
    manifest = persist_inspection_package(project, package)
    result = _asset_envelope("inspect_temporal", asset)
    result.update(
        {
            "playable_end": temporal.playable_end,
            "inspection_package": _json(package),
            "inspection_manifest": _json(manifest),
            "temporal_findings": list(finding_ids),
            "provider_analyses": [_json(item) for item in analyses],
        }
    )
    return result


def run_inspection_operation(
    operation: Operation,
    project_dir: str,
    *,
    source_path: str | None = None,
    asset_id: str | None = None,
    lineage: GenerationLineage | dict[str, Any] | None = None,
    usage_rights_status: UsageRightsStatus | str = UsageRightsStatus.UNKNOWN,
    usage_rights_evidence_ref: str | None = None,
    declared_regions: list[dict[str, Any]] | tuple[DeclaredRegion, ...] | None = None,
) -> dict[str, Any]:
    """Execute one public operation through the authoritative project store."""

    if operation == "ingest":
        if source_path is None:
            raise _error("ingest requires a source path", "inspection_source_required")
        validated_lineage = _lineage(lineage)
        validated_rights = _rights(usage_rights_status)
        project = open_project(project_dir)
        asset = ingest_project_asset(
            project,
            source_path,
            lineage=validated_lineage,
            usage_rights_status=validated_rights,
            usage_rights_evidence_ref=usage_rights_evidence_ref,
        )
        return _asset_envelope(operation, asset)
    project = _existing_project(project_dir)
    asset = _active_asset(project, asset_id)
    if operation == "preflight":
        return _asset_envelope(operation, _preflight_asset(project, asset))
    if operation == "inspect_temporal":
        return _inspect(project, asset, _regions(declared_regions))
    raise _error("inspection operation is unknown", "inspection_operation_unknown")
