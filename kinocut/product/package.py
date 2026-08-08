from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import shutil
from contextlib import contextmanager
from collections.abc import Iterable

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_artifact_path, _validate_input_path
from .captions import CaptionArtifact
from .models import CandidateMoment
from .package_models import (
    PackageAsset,
    PackageConfig,
    PackageLineage,
    PackagedClipResult,
    PerformanceIdentifier,
    ShortsPackageManifest,
    ThumbnailSpec,
    canonical_manifest_bytes,
)


__all__ = ["package_approved_clip"]


_HEX_RE = re.compile(r"^[0-9a-f]{16}$")


def _package_id(candidate: CandidateMoment) -> str:

    seed = candidate.dedup_key
    if not _HEX_RE.match(seed):
        raise MCPVideoError(
            "candidate dedup_key is not a 16-hex digest; cannot derive package id",
            error_type="validation_error",
            code="invalid_dedup_key",
        )
    return f"pkg_{seed}"


def _stage_copy(source_path: str, directory: str) -> tuple[str, str]:
    descriptor, staged_path = tempfile.mkstemp(dir=directory)
    digest = hashlib.sha256()
    target = os.fdopen(descriptor, "wb")
    with target, open(source_path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            target.write(chunk)
            digest.update(chunk)
    return staged_path, digest.hexdigest()


def _stage_bytes(payload: bytes, directory: str) -> str:
    descriptor, staged_path = tempfile.mkstemp(dir=directory)
    with os.fdopen(descriptor, "wb") as target:
        target.write(payload)
    return staged_path


@contextmanager
def _staging_area(directory: str):
    stage_dir = tempfile.mkdtemp(dir=directory)
    try:
        yield stage_dir
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def _validate_package_inputs(
    config: PackageConfig | None,
    candidate: CandidateMoment,
    caption_artifact: CaptionArtifact,
    thumbnail: ThumbnailSpec,
    lineage: PackageLineage | None,
    performance: PerformanceIdentifier | None,
) -> PackageConfig:
    cfg = config or PackageConfig()
    if not isinstance(cfg, PackageConfig):
        cfg = PackageConfig.model_validate(cfg)

    if not isinstance(candidate, CandidateMoment):
        raise MCPVideoError(
            "candidate must be a strict CandidateMoment",
            error_type="validation_error",
            code="invalid_candidate",
        )
    if not isinstance(caption_artifact, CaptionArtifact):
        raise MCPVideoError(
            "caption_artifact must be a strict CaptionArtifact",
            error_type="validation_error",
            code="invalid_caption_artifact",
        )
    if not isinstance(thumbnail, ThumbnailSpec):
        raise MCPVideoError(
            "thumbnail must be a strict ThumbnailSpec",
            error_type="validation_error",
            code="invalid_thumbnail",
        )
    if lineage is not None and not isinstance(lineage, PackageLineage):
        raise MCPVideoError(
            "lineage must be a strict PackageLineage",
            error_type="validation_error",
            code="invalid_lineage",
        )
    if performance is not None and not isinstance(performance, PerformanceIdentifier):
        raise MCPVideoError(
            "performance must be a strict PerformanceIdentifier",
            error_type="validation_error",
            code="invalid_performance",
        )
    return cfg


def _resolve_output_paths(
    package_dir: str,
    vertical_video_path: str,
    thumbnail_image_path: str,
    candidate: CandidateMoment,
    cfg: PackageConfig,
) -> tuple[str, str, str, str, str, tuple[str, ...]]:
    safe_dir = os.path.realpath(os.path.expanduser(_validate_artifact_path(package_dir)))
    safe_video = _validate_input_path(vertical_video_path)
    safe_thumbnail = _validate_input_path(thumbnail_image_path)
    package_id = _package_id(candidate)
    safe_basename = re.sub(r"[^A-Za-z0-9._-]", "_", cfg.manifest_basename)[:64]
    manifest_filename = f"{package_id}__{safe_basename}.json"
    video_suffix = os.path.splitext(safe_video)[1].lower() or ".mp4"
    thumbnail_suffix = os.path.splitext(safe_thumbnail)[1].lower() or ".jpg"
    video_path = os.path.join(safe_dir, f"vertical{video_suffix}")
    thumbnail_path = os.path.join(safe_dir, f"thumbnail{thumbnail_suffix}")
    srt_path = os.path.join(safe_dir, "captions.srt")
    metadata_path = os.path.join(safe_dir, "metadata.json")
    manifest_path = os.path.join(safe_dir, manifest_filename)
    output_paths = (video_path, srt_path, thumbnail_path, metadata_path, manifest_path)
    return safe_dir, safe_video, safe_thumbnail, package_id, manifest_filename, output_paths


def _assert_safe_output(output_paths: tuple[str, ...], cfg: PackageConfig) -> None:
    if any(os.path.islink(path) for path in output_paths):
        raise MCPVideoError(
            "package output path resolves through a symlink",
            error_type="validation_error",
            code="unsafe_path",
        )
    conflicts = tuple(path for path in output_paths if os.path.lexists(path))
    if conflicts and not cfg.overwrite_package:
        raise MCPVideoError(
            f"package assets already exist: {conflicts!r}",
            error_type="validation_error",
            code="package_write_conflict",
        )


def _verify_video_checksum(expected: str | None, actual: str) -> None:
    if expected is not None and expected != actual:
        raise MCPVideoError(
            "vertical video checksum does not match the approved render",
            error_type="validation_error",
            code="source_checksum_mismatch",
        )


def _build_metadata_bytes(candidate: CandidateMoment, video_sha256: str) -> bytes:
    metadata = {
        "candidate_id": candidate.candidate_id,
        "suggested_title": candidate.suggested_title,
        "suggested_hook": candidate.suggested_hook,
        "source_timestamps": [candidate.start, candidate.end],
        "vertical_video_sha256": video_sha256,
    }
    return (json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _resolve_lineage(
    lineage: PackageLineage | None, candidate_id: str, video_sha256: str
) -> PackageLineage:
    package_lineage = lineage or PackageLineage(candidate_id=candidate_id)
    return package_lineage.model_copy(update={"artifact_sha256": f"sha256:{video_sha256}"})


def _collect_review_warnings(
    candidate: CandidateMoment,
    caption_artifact: CaptionArtifact,
    extra_review_warnings: Iterable[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for value in (candidate.review_warning, *caption_artifact.warnings, *extra_review_warnings)
            if value
        )
    )


def _build_package_assets(
    staged_video: str,
    video_path: str,
    staged_srt: str,
    staged_thumbnail: str,
    thumbnail_path: str,
    staged_metadata: str,
    manifest_filename: str,
) -> tuple[PackageAsset, ...]:
    return (
        PackageAsset(
            role="vertical_video",
            relative_path=os.path.basename(video_path),
            bytes=os.path.getsize(staged_video),
        ),
        PackageAsset(
            role="editable_subtitles", relative_path="captions.srt", bytes=os.path.getsize(staged_srt)
        ),
        PackageAsset(
            role="representative_thumbnail",
            relative_path=os.path.basename(thumbnail_path),
            bytes=os.path.getsize(staged_thumbnail),
        ),
        PackageAsset(role="metadata", relative_path="metadata.json", bytes=os.path.getsize(staged_metadata)),
        PackageAsset(role="edit_manifest", relative_path=manifest_filename),
    )


def package_approved_clip(
    *,
    package_dir: str,
    vertical_video_path: str,
    expected_video_sha256: str | None = None,
    caption_artifact: CaptionArtifact,
    candidate: CandidateMoment,
    thumbnail: ThumbnailSpec,
    lineage: PackageLineage | None = None,
    performance: PerformanceIdentifier | None = None,
    extra_review_warnings: Iterable[str] = (),
    config: PackageConfig | None = None,
    generated_at: str | None = None,
) -> PackagedClipResult:
    cfg = _validate_package_inputs(config, candidate, caption_artifact, thumbnail, lineage, performance)
    (safe_dir, safe_video, safe_thumbnail, package_id, manifest_filename, output_paths) = _resolve_output_paths(
        package_dir, vertical_video_path, thumbnail.image_path, candidate, cfg
    )
    _assert_safe_output(output_paths, cfg)
    os.makedirs(safe_dir, exist_ok=True)
    video_path, srt_path, thumbnail_path, metadata_path, manifest_path = output_paths
    with _staging_area(safe_dir) as stage_dir:
        staged_video, video_sha256 = _stage_copy(safe_video, stage_dir)
        _verify_video_checksum(expected_video_sha256, video_sha256)
        staged_thumbnail, _ = _stage_copy(safe_thumbnail, stage_dir)
        staged_srt = _stage_bytes((caption_artifact.srt_body.rstrip() + "\n").encode(), stage_dir)
        staged_metadata = _stage_bytes(_build_metadata_bytes(candidate, video_sha256), stage_dir)
        package_lineage = _resolve_lineage(lineage, candidate.candidate_id, video_sha256)
        warnings = _collect_review_warnings(candidate, caption_artifact, extra_review_warnings)
        assets = _build_package_assets(
            staged_video, video_path, staged_srt, staged_thumbnail, thumbnail_path, staged_metadata, manifest_filename
        )
        manifest = ShortsPackageManifest(
            package_id=package_id,
            package_root=safe_dir,
            generated_at=generated_at,
            candidate=candidate,
            caption_artifact=caption_artifact,
            suggested_title=candidate.suggested_title,
            short_description=candidate.suggested_hook,
            source_timestamps=(candidate.start, candidate.end),
            thumbnail=thumbnail.model_copy(update={"image_path": thumbnail_path}),
            lineage=package_lineage,
            assets=assets,
            review_warnings=warnings,
            performance=performance,
        )
        staged_manifest = _stage_bytes(canonical_manifest_bytes(manifest) + b"\n", stage_dir)
        for staged_path, output_path in (
            (staged_video, video_path),
            (staged_srt, srt_path),
            (staged_thumbnail, thumbnail_path),
            (staged_metadata, metadata_path),
            (staged_manifest, manifest_path),
        ):
            os.replace(staged_path, output_path)

    return PackagedClipResult(
        package_root=safe_dir,
        manifest_path=manifest_path,
        asset_paths=output_paths,
        manifest=manifest,
    )
