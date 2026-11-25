"""Anchored publication and verified retirement of a dedicated artifact tree."""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path

from ..errors import MCPVideoError
from ..validation_errors import exception_kind, likely_cause, own_reason
from ._anchor import _Directory, _partial_output, _rename_exclusive, _same_inode, _unsafe
from ._policy import _validate_artifact_location


def _tree_error(problem: str, *, code: str, cause: str, recovery: str) -> MCPVideoError:
    return MCPVideoError(
        f"Problem: {problem} Likely cause: {likely_cause(cause)} Recovery: {recovery}",
        error_type="validation_error",
        code=code,
        suggested_action={"auto_fix": False, "description": recovery},
    )


_TreeSnapshot = tuple[tuple[int, int], dict[str, tuple[int, int]], dict[tuple[str, str], tuple[int, int]]]


def _snapshot_replaceable(base: Path, stage: Path, overwrite: bool) -> _TreeSnapshot | None:
    """Verify and snapshot a dedicated package directory before replacement."""
    if not os.path.lexists(base):
        return None
    base_stat = os.stat(base, follow_symlinks=False)
    if stat.S_ISLNK(base_stat.st_mode) or not stat.S_ISDIR(base_stat.st_mode):
        raise _tree_error(
            "Package destination is not a directory.",
            code="unsafe_path",
            cause=own_reason("The destination is a symlink or a non-directory entry."),
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
    raise _tree_error(
        "Package destination already exists.",
        code="package_write_conflict",
        cause=own_reason("Overwrite consent is missing or the destination contains unrelated entries."),
        recovery="Choose a new dedicated package_root or authorize replacement of the existing package.",
    )


def _preserve_displaced(displaced: Path, base: Path) -> None:
    preserved = base.parent / f".{base.name}.preserved_{secrets.token_hex(6)}"
    with contextlib.suppress(OSError):
        if os.path.lexists(displaced):
            os.rename(displaced, preserved)
    raise _tree_error(
        "Package destination changed concurrently during replacement; prior contents were preserved.",
        code="package_write_conflict",
        cause=own_reason("Destination directory identity or contents changed between inspection and replacement."),
        recovery="Inspect the preserved sibling directory and re-run packaging on a clean package_root.",
    )


def _matches_snapshot(displaced: Path, snapshot: _TreeSnapshot) -> bool:
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
    displaced: Path, trash: Path, snapshot: _TreeSnapshot, moved: list[tuple[Path, Path]]
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


def _remove_verified_displaced(displaced: Path, base: Path, snapshot: _TreeSnapshot) -> None:
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


def _check_stage(anchor: _Directory, stage: Path, identity: os.stat_result) -> None:
    anchor.check()
    current = os.stat(anchor.name(stage.name), follow_symlinks=False, **anchor.options())
    if not stat.S_ISDIR(current.st_mode) or not _same_inode(current, identity):
        raise _unsafe("Output staging tree changed during publication")


@contextlib.contextmanager
def anchored_tree(path: Path, *, overwrite: bool = False) -> Iterator[Path]:
    """Build a private sibling tree, then publish it in one native rename.

    Replacement requires a native exchange and consent. The prior tree may
    contain only subdirectories and regular files named in the staged tree.
    Concurrently changed contents are preserved rather than deleted.
    """
    if type(overwrite) is not bool:
        raise MCPVideoError(
            "overwrite must be an explicit boolean", error_type="validation_error", code="invalid_parameter"
        )
    _validate_artifact_location(str(path), "Package root")
    base = path.parent.resolve() / path.name
    with contextlib.closing(_Directory(str(base.parent))) as anchor:
        stage = base.parent / f".kinocut_package_{secrets.token_hex(8)}"
        name = anchor.name(stage.name)
        options = anchor.options()
        os.mkdir(name, mode=0o700, **options)
        identity = os.stat(name, follow_symlinks=False, **options)
        published = False
        try:
            _check_stage(anchor, stage, identity)
            yield stage
            _check_stage(anchor, stage, identity)
            snapshot = _snapshot_replaceable(base, stage, overwrite)
            _check_stage(anchor, stage, identity)
            try:
                if snapshot is not None and os.name == "nt":
                    displaced = base.parent / f".{base.name}.displaced_{secrets.token_hex(6)}"
                    os.rename(base, displaced)
                    try:
                        os.rename(stage, base)
                    except BaseException:
                        with contextlib.suppress(OSError):
                            if not os.path.lexists(base) and os.path.lexists(displaced):
                                os.rename(displaced, base)
                        raise
                    displaced_stage = displaced
                else:
                    _rename_exclusive(anchor, stage.name, base.name, exchange=snapshot is not None)
                    displaced_stage = stage
            except OSError as exc:
                raise _tree_error(
                    "Could not atomically publish the package directory.",
                    code="package_write_conflict"
                    if isinstance(exc, FileExistsError)
                    else "shorts_package_publish_failed",
                    cause=own_reason(exception_kind(exc)),
                    recovery="Choose a new package_root on a filesystem that supports atomic directory publication.",
                ) from exc
            published = True
            _verify_publication(anchor, displaced_stage, base, identity, snapshot)
        finally:
            if not published:
                with contextlib.suppress(OSError):
                    current = os.stat(name, follow_symlinks=False, **options)
                    if stat.S_ISDIR(current.st_mode) and _same_inode(current, identity):
                        shutil.rmtree(name, ignore_errors=True, **options)


def _verify_publication(
    anchor: _Directory, stage: Path, base: Path, identity: os.stat_result, snapshot: _TreeSnapshot | None
) -> None:
    try:
        _check_stage(anchor, base, identity)
    except (OSError, MCPVideoError) as exc:
        raise _partial_output("Published tree could not be verified; inspect the output before reuse") from exc
    if snapshot is not None:
        try:
            _remove_verified_displaced(stage, base, snapshot)
        except OSError as exc:
            raise _partial_output("New tree was published but prior tree cleanup failed; inspect the output") from exc
