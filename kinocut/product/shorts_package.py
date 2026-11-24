"""Review-gated packaging of approved shorts renders.

Packages each platform draft only after a current approve decision. Reads
render receipts from the plan; never posts or opens network connections.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import stat
from contextlib import closing
from pathlib import Path
from typing import Any

from ..atomic_publication import _Directory, _rename_exclusive
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_artifact_path
from .captions import CaptionArtifact
from .package import package_approved_clip
from .package_models import PackageLineage, ThumbnailSpec, canonical_manifest_bytes
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
            cause=f"render digests for {', '.join(stale)} predate the current approved revision.",
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
    result = package_approved_clip(
        package_dir=str(stage / record.platform),
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
    root = base / record.platform
    manifest_path = Path(result.manifest_path)
    video = next(asset.relative_path for asset in result.manifest.assets if asset.role == "vertical_video")
    gate = _gate_package_media(str(Path(result.package_root, video)))
    if "video" in gate:
        gate = {**gate, "video": str(root / video)}
    thumbnail = result.manifest.thumbnail
    manifest = result.manifest.model_copy(
        update={
            "package_root": str(root),
            "thumbnail": thumbnail.model_copy(update={"image_path": str(root / Path(thumbnail.image_path).name)}),
        }
    )
    manifest_path.write_bytes(canonical_manifest_bytes(manifest) + b"\n")
    return {
        "platform": record.platform,
        "package_root": str(root),
        "manifest_path": str(root / manifest_path.name),
        "asset_paths": [str(root / Path(path).name) for path in result.asset_paths],
        "external_posting": False,
        "quality": gate,
    }


_PackageSnapshot = tuple[tuple[int, int], dict[str, tuple[int, int]], dict[tuple[str, str], tuple[int, int]]]


def _snapshot_replaceable(base: Path, stage: Path, overwrite: bool) -> _PackageSnapshot | None:
    """Verify and snapshot a dedicated package directory before replacement."""
    if not os.path.lexists(base):
        return None
    base_stat = os.stat(base, follow_symlinks=False)
    if stat.S_ISLNK(base_stat.st_mode) or not stat.S_ISDIR(base_stat.st_mode):
        raise _package_error(
            "Package destination is not a directory.",
            code="unsafe_path",
            cause="The destination is a symlink or a non-directory entry.",
            recovery="Choose a new package_root under the plan output directory.",
        )
    platforms: dict[str, tuple[int, int]] = {}
    inodes: dict[tuple[str, str], tuple[int, int]] = {}
    if overwrite:
        valid = True
        for platform in base.iterdir():
            pstat = os.stat(platform, follow_symlinks=False)
            stage_plat = stage / platform.name
            if stat.S_ISLNK(pstat.st_mode) or not stat.S_ISDIR(pstat.st_mode) or not stage_plat.is_dir():
                valid = False
                break
            platforms[platform.name] = (pstat.st_dev, pstat.st_ino)
            allowed = {asset.name for asset in stage_plat.iterdir()}
            for asset in platform.iterdir():
                astat = os.stat(asset, follow_symlinks=False)
                if stat.S_ISLNK(astat.st_mode) or not stat.S_ISREG(astat.st_mode) or asset.name not in allowed:
                    valid = False
                    break
                inodes[(platform.name, asset.name)] = (astat.st_dev, astat.st_ino)
            if not valid:
                break
        if valid:
            return (base_stat.st_dev, base_stat.st_ino), platforms, inodes
    raise _package_error(
        "Package destination already exists.",
        code="package_write_conflict",
        cause="Overwrite consent is missing or the destination contains unrelated entries.",
        recovery="Choose a new dedicated package_root or authorize replacement of the existing package.",
    )


def _preserve_displaced(displaced: Path, base: Path) -> None:
    preserved = base.parent / f".{base.name}.preserved_{secrets.token_hex(6)}"
    with contextlib.suppress(OSError):
        if os.path.lexists(displaced):
            os.rename(displaced, preserved)
    raise _package_error(
        "Package destination changed concurrently during replacement; prior contents were preserved.",
        code="package_write_conflict",
        cause="Destination directory identity or contents changed between inspection and replacement.",
        recovery="Inspect the preserved sibling directory and re-run packaging on a clean package_root.",
    )


def _matches_snapshot(displaced: Path, snapshot: _PackageSnapshot) -> bool:
    expected_dir, expected_platforms, expected_files = snapshot
    actual_stat = os.stat(displaced, follow_symlinks=False)
    if (actual_stat.st_dev, actual_stat.st_ino) != expected_dir or not stat.S_ISDIR(actual_stat.st_mode):
        return False
    seen_platforms: set[str] = set()
    seen_files: set[tuple[str, str]] = set()
    for platform in displaced.iterdir():
        pstat = os.stat(platform, follow_symlinks=False)
        if (
            stat.S_ISLNK(pstat.st_mode)
            or not stat.S_ISDIR(pstat.st_mode)
            or expected_platforms.get(platform.name) != (pstat.st_dev, pstat.st_ino)
        ):
            return False
        seen_platforms.add(platform.name)
        for asset in platform.iterdir():
            astat = os.stat(asset, follow_symlinks=False)
            key = (platform.name, asset.name)
            if (
                stat.S_ISLNK(astat.st_mode)
                or not stat.S_ISREG(astat.st_mode)
                or expected_files.get(key) != (astat.st_dev, astat.st_ino)
            ):
                return False
            seen_files.add(key)
    return seen_platforms == set(expected_platforms) and seen_files == set(expected_files)


def _restore_quarantined(moved: list[tuple[Path, Path]], moved_dirs: list[tuple[Path, Path]], trash: Path) -> None:
    for src, dst in reversed(moved_dirs):
        with contextlib.suppress(OSError):
            if os.path.lexists(dst) and not os.path.lexists(src):
                os.rename(dst, src)
    for src, dst in reversed(moved):
        with contextlib.suppress(OSError):
            if os.path.lexists(dst) and not os.path.lexists(src):
                src.parent.mkdir(parents=True, exist_ok=True)
                os.rename(dst, src)
    with contextlib.suppress(OSError):
        trash.rmdir()


def _quarantine_verified_entries(
    displaced: Path, trash: Path, snapshot: _PackageSnapshot, moved: list[tuple[Path, Path]]
) -> None:
    """Move expected files into private 0o700 quarantine and re-verify inodes before any unlink."""
    expected_dir, expected_platforms, expected_files = snapshot
    if not _matches_snapshot(displaced, snapshot):
        raise OSError("snapshot mismatch")
    dstat = os.stat(displaced, follow_symlinks=False)
    if (dstat.st_dev, dstat.st_ino) != expected_dir or not stat.S_ISDIR(dstat.st_mode):
        raise OSError("displaced root identity changed")
    for idx, ((plat_name, asset_name), expected_id) in enumerate(expected_files.items()):
        src = displaced / plat_name / asset_name
        dst = trash / f"{idx}_{asset_name}"
        pstat = os.stat(displaced / plat_name, follow_symlinks=False)
        if stat.S_ISLNK(pstat.st_mode) or (pstat.st_dev, pstat.st_ino) != expected_platforms.get(plat_name):
            raise OSError("platform dir identity changed")
        os.rename(src, dst)
        moved.append((src, dst))
        qstat = os.stat(dst, follow_symlinks=False)
        if (
            stat.S_ISLNK(qstat.st_mode)
            or not stat.S_ISREG(qstat.st_mode)
            or (qstat.st_dev, qstat.st_ino) != expected_id
        ):
            raise OSError("quarantined file identity mismatch")


def _remove_verified_displaced(displaced: Path, base: Path, snapshot: _PackageSnapshot) -> None:
    """Quarantine and verify every inode before unlinking; restore intact tree on any race."""
    _, expected_platforms, _ = snapshot
    trash = base.parent / f".{base.name}.trash_{secrets.token_hex(6)}"
    os.mkdir(trash, mode=0o700)
    moved: list[tuple[Path, Path]] = []
    moved_dirs: list[tuple[Path, Path]] = []
    try:
        _quarantine_verified_entries(displaced, trash, snapshot, moved)
        for plat_name in expected_platforms:
            src_dir = displaced / plat_name
            dst_dir = trash / f"dir_{plat_name}"
            if any(src_dir.iterdir()):
                raise OSError("platform directory not empty")
            os.rename(src_dir, dst_dir)
            moved_dirs.append((src_dir, dst_dir))
            if any(dst_dir.iterdir()):
                raise OSError("quarantined platform directory not empty")
        displaced.rmdir()
    except OSError:
        _restore_quarantined(moved, moved_dirs, trash)
        _preserve_displaced(displaced, base)
    for _, qpath in moved:
        qpath.unlink()
    for _, qdir in moved_dirs:
        qdir.rmdir()
    trash.rmdir()


def _publish_package_tree(
    anchor: _Directory, stage: Path, base: Path, overwrite: bool, *, exchanged: list[bool] | None = None
) -> None:
    """Publish staged package dir; marks ``exchanged[0] = True`` the instant stage leaves caller ownership."""
    try:
        anchor.check()
        snapshot = _snapshot_replaceable(base, stage, overwrite)
        anchor.check()
        if snapshot is None:
            _rename_exclusive(anchor, stage.name, base.name, exchange=False)
            if exchanged is not None:
                exchanged[0] = True
            return
        if os.name == "nt":
            displaced = base.parent / f".{base.name}.displaced_{secrets.token_hex(6)}"
            os.rename(base, displaced)
            try:
                os.rename(stage, base)
                if exchanged is not None:
                    exchanged[0] = True
            except BaseException:
                with contextlib.suppress(OSError):
                    if not os.path.lexists(base) and os.path.lexists(displaced):
                        os.rename(displaced, base)
                raise
            _remove_verified_displaced(displaced, base, snapshot)
            return
        _rename_exclusive(anchor, stage.name, base.name, exchange=True)
        if exchanged is not None:
            exchanged[0] = True
        _remove_verified_displaced(stage, base, snapshot)
    except OSError as exc:
        raise _package_error(
            "Could not atomically publish the package directory.",
            code="package_write_conflict" if isinstance(exc, FileExistsError) else "shorts_package_publish_failed",
            cause=own_reason(exception_kind(exc)),
            recovery="Choose a new package_root on a filesystem that supports atomic directory publication.",
        ) from exc


def _stage_packages(
    base: Path, records: tuple[RenderRecord, ...], candidate: CandidateMoment, job_id: str, overwrite: bool
) -> list[dict[str, Any]]:
    with closing(_Directory(str(base.parent))) as anchor:
        stage = base.parent / f".kinocut_package_{secrets.token_hex(8)}"
        os.mkdir(stage, mode=0o700)
        exchanged = [False]
        try:
            emitted = [
                _package_platform(record, candidate=candidate, base=base, stage=stage, review_decision_ref=job_id)
                for record in records
            ]
            _publish_package_tree(anchor, stage, base, overwrite, exchanged=exchanged)
        finally:
            if not exchanged[0] and stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
    return emitted


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
            cause=f"candidate {candidate.candidate_id!r} has no RenderRecord entries.",
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
            cause=f"{requested!r} is outside {plan.output_dir!r}.",
            recovery="Pass a dedicated package_root under the plan output directory.",
        )
    _validate_artifact_path(str(base))
    emitted = _stage_packages(base, records, candidate, plan.job_id, overwrite)
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
