"""Sinter winners-bundle envelope (liminal #999, option A — provisional v0.1).

Envelope layout::

    manifest.json
    payload/<artifact files>

``manifest.json``::

    {
      "schema_version": "sinter.winners/0.1",
      "exported_at": "2026-08-31T00:00:00Z",
      "artifacts": [
        {
          "artifact_id": "<sha256 hex>",
          "event_id": "<sha256 hex>",
          "domain": "glsl",
          "axes": "D=... A=... R=... N=...",
          "level": "S",
          "payload": {"path": "payload/<name>", "sha256": "<hex>", "bytes": 1234}
        }
      ],
      "envelope_sha256": "<sha256 of the manifest with this field removed,
                          canonical JSON (sorted keys, compact separators)>"
    }

Verification is fail-closed: every payload file must be listed exactly once,
every listed file must exist with a matching digest and size, the schema
version must be exactly the pinned one, and payload paths must stay inside
the bundle. Judge identity is deliberately absent pending the envelope-pin
answer on #999.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, NoReturn

from .defaults import DEFAULT_HASH_CHUNK_BYTES, REVIDEO_WINNERS_SCHEMA_VERSION
from .errors import ValidationError
from .revideo_models import WinnersArtifactInfo, WinnersBundleReceipt
from .validation import (
    WINNERS_ARTIFACT_OPTIONAL_FIELDS,
    WINNERS_ARTIFACT_REQUIRED_FIELDS,
    WINNERS_HEX64_CHARS,
    WINNERS_KNOWN_LICENSES,
    WINNERS_MANIFEST_REQUIRED_FIELDS,
    WINNERS_PAYLOAD_REQUIRED_FIELDS,
)


def _fail(detail: str) -> NoReturn:
    raise ValidationError("winners_bundle", detail)


def _canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    body = {k: v for k, v in manifest.items() if k != "envelope_sha256"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= WINNERS_HEX64_CHARS


def _reject_unexpected_fields(
    obj: dict[str, Any],
    declared: tuple[str, ...],
    label: str,
    optional: tuple[str, ...] = (),
) -> None:
    """Fail closed on undeclared fields: the pinned schema is exact."""
    unexpected = sorted(set(obj) - set(declared) - set(optional))
    if unexpected:
        _fail(f"{label} has unexpected fields: {unexpected}")


@dataclass(frozen=True)
class _PreparedArtifact:
    source: Path
    entry: dict[str, Any]


def _reject_leaf_symlink(path: Path, label: str) -> None:
    """Reject a symlink at a caller-selected path's leaf."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        _fail(f"could not inspect {label}: {exc}")
    if stat.S_ISLNK(mode):
        _fail(f"{label} must not be a symlink: {path}")


def _canonical_leaf(path: Path, label: str) -> Path:
    """Canonicalize caller-selected ancestors without following the leaf."""
    absolute = Path(os.path.abspath(path))
    try:
        anchored = absolute.parent.resolve(strict=False) / absolute.name
    except (OSError, RuntimeError) as exc:
        _fail(f"could not resolve parent of {label}: {exc}")
    _reject_leaf_symlink(anchored, label)
    return anchored


def _reject_symlink_below(anchor: Path, path: Path, label: str) -> None:
    """Reject escapes and symlinks below an already verified root."""
    try:
        relative = path.relative_to(anchor)
    except ValueError:
        _fail(f"{label} escapes its verified root")
    current = anchor
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            _fail(f"could not inspect {label}: {exc}")
        if stat.S_ISLNK(mode):
            _fail(f"{label} must not contain a symlink: {current}")


def _regular_file_identity(path: Path, label: str) -> tuple[str, int]:
    """Hash one stable regular file through a no-follow leaf descriptor."""
    _reject_leaf_symlink(path, label)
    try:
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            _fail(f"{label} must be a regular file")
    except OSError as exc:
        _fail(f"could not inspect {label}: {exc}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _fail(f"could not open {label}: {exc}")
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                _fail(f"{label} must be a regular file")
            for chunk in iter(lambda: handle.read(DEFAULT_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        _fail(f"could not read {label}: {exc}")
    markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, marker) != getattr(after, marker) for marker in markers):
        _fail(f"{label} changed while it was read")
    return digest.hexdigest(), after.st_size


def _read_regular_bytes(path: Path, label: str) -> bytes:
    """Read one regular file through a no-follow leaf descriptor."""
    _reject_leaf_symlink(path, label)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                _fail(f"{label} must be a regular file")
            content = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        _fail(f"could not read {label}: {exc}")
    markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, marker) != getattr(after, marker) for marker in markers):
        _fail(f"{label} changed while it was read")
    return content


def _copy_verified_payload(source: Path, destination: Path, expected_digest: str, expected_bytes: int) -> None:
    """Copy one payload and prove the staged bytes match the validated source."""
    _reject_leaf_symlink(source, "payload source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(source, source_flags)
        try:
            target_fd = os.open(destination, target_flags, 0o600)
        except OSError:
            os.close(source_fd)
            raise
        digest = hashlib.sha256()
        copied_bytes = 0
        with os.fdopen(source_fd, "rb") as reader, os.fdopen(target_fd, "wb") as writer:
            before = os.fstat(reader.fileno())
            if not stat.S_ISREG(before.st_mode):
                _fail("payload source must be a regular file")
            while chunk := reader.read(DEFAULT_HASH_CHUNK_BYTES):
                writer.write(chunk)
                digest.update(chunk)
                copied_bytes += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            after = os.fstat(reader.fileno())
    except OSError as exc:
        _fail(f"payload copy failed: {exc}")
    markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    stable = all(getattr(before, marker) == getattr(after, marker) for marker in markers)
    if not stable or digest.hexdigest() != expected_digest or copied_bytes != expected_bytes:
        _fail("copied payload does not match its validated source")


def _prepare_artifacts(artifacts: list[dict[str, Any]]) -> list[_PreparedArtifact]:
    """Validate and hash every artifact before a destination is touched."""
    if not isinstance(artifacts, list) or not artifacts:
        _fail("artifacts must be a non-empty list")
    prepared: list[_PreparedArtifact] = []
    used_names: set[str] = set()
    for index, spec in enumerate(artifacts):
        if not isinstance(spec, dict):
            _fail(f"artifacts[{index}] must be an object")
        raw_source = spec.get("payload_source")
        if not isinstance(raw_source, (str, os.PathLike)) or not str(raw_source):
            _fail(f"artifacts[{index}].payload_source must be a file path")
        try:
            source_value = raw_source if isinstance(raw_source, str) else os.fspath(raw_source)
            if not isinstance(source_value, str):
                _fail(f"artifacts[{index}].payload_source must be a text path")
            source = _canonical_leaf(Path(source_value), f"artifacts[{index}].payload_source")
        except (TypeError, ValueError, OSError) as exc:
            _fail(f"artifacts[{index}].payload_source is invalid: {exc}")
        name = source.name
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            _fail(f"artifacts[{index}].payload_source must have a safe filename")
        collision_key = name.casefold()
        if collision_key in used_names:
            _fail(f"duplicate payload filename: {name}")
        used_names.add(collision_key)
        digest, size = _regular_file_identity(source, f"artifacts[{index}].payload_source")
        entry = _entry_from_spec(spec, f"payload/{name}", digest, size)
        _validate_artifact(entry, index)
        prepared.append(_PreparedArtifact(source=source, entry=entry))
    return prepared


def _entry_from_spec(spec: dict[str, Any], payload_path: str, digest: str, size: int) -> dict[str, Any]:
    entry = {
        "artifact_id": spec.get("artifact_id"),
        "event_id": spec.get("event_id"),
        "domain": spec.get("domain"),
        "axes": spec.get("axes"),
        "level": spec.get("level"),
        "license": spec.get("license"),
        "payload": {"path": payload_path, "sha256": digest, "bytes": size},
    }
    if spec.get("judges") is not None:
        judges = spec.get("judges")
        entry["judges"] = list(judges) if isinstance(judges, (list, tuple)) else judges
    return entry


def _validate_destination(dest: Path, *, allow_nonempty: bool = False) -> None:
    """Require a missing or real directory without changing it."""
    _reject_leaf_symlink(dest, "destination")
    if not os.path.lexists(dest):
        return
    if not dest.is_dir():
        _fail(f"destination is not a directory: {dest}")
    try:
        if not allow_nonempty and any(dest.iterdir()):
            _fail(f"destination directory is not empty: {dest} — use a fresh directory")
    except OSError as exc:
        _fail(f"could not inspect destination: {exc}")


def _validate_bundle_destination(dest: Path) -> None:
    """Preserve the writer's existing-root contract while guarding payload/."""
    _validate_destination(dest, allow_nonempty=True)
    if not dest.exists():
        return
    payload = dest / "payload"
    _reject_symlink_below(dest, payload, "destination payload directory")
    if not os.path.lexists(payload):
        return
    if not payload.is_dir():
        _fail(f"destination payload path is not a directory: {payload}")
    try:
        if any(payload.iterdir()):
            _fail(f"destination payload/ directory is not empty: {payload} — use a fresh bundle directory")
    except OSError as exc:
        _fail(f"could not inspect destination payload directory: {exc}")


def _temporary_sibling(dest: Path) -> Path:
    parent = dest.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f".{dest.name}.kinocut-", dir=parent))
    except OSError as exc:
        _fail(f"could not create temporary destination: {exc}")


def _remove_temporary_tree(path: Path) -> None:
    try:
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    except OSError:
        pass


def _publish_directory(staged: Path, dest: Path) -> None:
    """Publish a complete sibling directory, preserving non-empty destinations."""
    _validate_destination(dest)
    removed_empty_dest = False
    try:
        if dest.exists():
            dest.rmdir()
            removed_empty_dest = True
        os.replace(staged, dest)
    except OSError as exc:
        if removed_empty_dest and not os.path.lexists(dest):
            with suppress(OSError):
                dest.mkdir()
        _fail(f"could not publish destination: {exc}")


def _replace_payload(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _preflight_merge_targets(dest: Path, relative_paths: list[Path]) -> None:
    _validate_destination(dest, allow_nonempty=True)
    for relative in relative_paths:
        target = dest / relative
        _reject_symlink_below(dest, target, f"staging destination {relative}")
        if os.path.lexists(target):
            try:
                mode = target.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                _fail(f"could not inspect staging destination {relative}: {exc}")
            if not stat.S_ISREG(mode):
                _fail(f"staging destination must be a regular file: {relative}")


def _create_merge_parents(dest: Path, relative: Path, created: list[Path]) -> None:
    current = dest
    for part in relative.parent.parts:
        current /= part
        if current.exists():
            if not current.is_dir() or current.is_symlink():
                _fail(f"staging destination parent is unsafe: {current}")
            continue
        try:
            current.mkdir()
        except OSError as exc:
            _fail(f"could not create staging destination parent: {exc}")
        created.append(current)


def _rollback_merge(updates: list[tuple[Path, Path | None]], created_dirs: list[Path]) -> bool:
    complete = True
    for target, backup in reversed(updates):
        try:
            if os.path.lexists(target):
                target.unlink()
            if backup is not None and backup.exists():
                _replace_payload(backup, target)
        except OSError:
            complete = False
    for directory in reversed(created_dirs):
        try:
            directory.rmdir()
        except OSError:
            complete = False
    return complete


def _merge_staged_payloads(staged: Path, dest: Path, relative_paths: list[Path]) -> None:
    """Merge verified files with rollback if any destination update fails."""
    _preflight_merge_targets(dest, relative_paths)
    backup = _temporary_sibling(dest.with_name(f"{dest.name}-backup"))
    updates: list[tuple[Path, Path | None]] = []
    created_dirs: list[Path] = []
    preserve_backup = False
    try:
        for relative in relative_paths:
            _create_merge_parents(dest, relative, created_dirs)
            source = staged / relative
            target = dest / relative
            backup_file: Path | None = None
            if os.path.lexists(target):
                backup_file = backup / relative
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                _replace_payload(target, backup_file)
            updates.append((target, backup_file))
            _replace_payload(source, target)
    except (OSError, ValidationError) as exc:
        restored = _rollback_merge(updates, created_dirs)
        preserve_backup = not restored
        if isinstance(exc, ValidationError) and restored:
            raise
        detail = "payload merge failed" if restored else "payload merge failed and rollback was incomplete"
        _fail(f"{detail}: {exc}")
    finally:
        if not preserve_backup:
            _remove_temporary_tree(backup)


def _manifest_for(prepared: list[_PreparedArtifact], exported_at: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": REVIDEO_WINNERS_SCHEMA_VERSION,
        "exported_at": exported_at,
        "artifacts": [item.entry for item in prepared],
    }
    manifest["envelope_sha256"] = hashlib.sha256(_canonical_manifest_bytes(manifest)).hexdigest()
    return manifest


def write_bundle(
    dest: str | Path,
    artifacts: list[dict[str, Any]],
    exported_at: str,
) -> WinnersBundleReceipt:
    """Build a bundle envelope from artifact specs.

    Each artifact spec carries the manifest fields plus ``payload_source``
    (the local file to copy into ``payload/``). Also the reference writer
    for the Sinter side — the format here IS the v0.1 contract.
    """
    prepared = _prepare_artifacts(artifacts)
    dest_path = _canonical_leaf(Path(dest), "destination")
    _validate_bundle_destination(dest_path)
    staged = _temporary_sibling(dest_path)
    try:
        payload_dir = staged / "payload"
        payload_dir.mkdir()
        for item in prepared:
            payload = item.entry["payload"]
            _copy_verified_payload(item.source, payload_dir / item.source.name, payload["sha256"], payload["bytes"])
        manifest = _manifest_for(prepared, exported_at)
        (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        receipt = verify_bundle(staged)
        published_paths = [Path(item.entry["payload"]["path"]) for item in prepared]
        published_paths.append(Path("manifest.json"))
        if dest_path.exists() and any(dest_path.iterdir()):
            _merge_staged_payloads(staged, dest_path, published_paths)
            _remove_temporary_tree(staged)
        else:
            _publish_directory(staged, dest_path)
        return receipt
    except ValidationError:
        _remove_temporary_tree(staged)
        raise
    except OSError as exc:
        _remove_temporary_tree(staged)
        _fail(f"bundle copy failed: {exc}")


def _validate_manifest_structure(manifest: Any, bundle_dir: Path) -> tuple[str, list[dict[str, Any]], str]:
    if not isinstance(manifest, dict):
        _fail("manifest.json must be a JSON object")
    missing = [f for f in WINNERS_MANIFEST_REQUIRED_FIELDS if f not in manifest]
    if missing:
        _fail(f"manifest missing required fields: {missing}")
    _reject_unexpected_fields(manifest, WINNERS_MANIFEST_REQUIRED_FIELDS, "manifest")
    schema = manifest["schema_version"]
    if schema != REVIDEO_WINNERS_SCHEMA_VERSION:
        _fail(f"unsupported schema_version {schema!r} — this build pins {REVIDEO_WINNERS_SCHEMA_VERSION!r}")
    if not isinstance(manifest["exported_at"], str) or not manifest["exported_at"]:
        _fail("exported_at must be a non-empty string")
    if not isinstance(manifest["artifacts"], list) or not manifest["artifacts"]:
        _fail("artifacts must be a non-empty list")
    return manifest["exported_at"], manifest["artifacts"], manifest["envelope_sha256"]


def _validate_artifact(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        _fail(f"artifacts[{index}] must be an object")
    missing = [f for f in WINNERS_ARTIFACT_REQUIRED_FIELDS if f not in entry]
    if missing:
        _fail(f"artifacts[{index}] missing required fields: {missing}")
    _reject_unexpected_fields(
        entry, WINNERS_ARTIFACT_REQUIRED_FIELDS, f"artifacts[{index}]", optional=WINNERS_ARTIFACT_OPTIONAL_FIELDS
    )
    for field in ("artifact_id", "event_id"):
        if not _is_hex64(entry[field]):
            _fail(f"artifacts[{index}].{field} must be a 64-char sha256 hex string")
    for field in ("domain", "axes", "level", "license"):
        if not isinstance(entry[field], str) or not entry[field]:
            _fail(f"artifacts[{index}].{field} must be a non-empty string")
    if entry["license"] not in WINNERS_KNOWN_LICENSES:
        _fail(f"artifacts[{index}].license must be one of {sorted(WINNERS_KNOWN_LICENSES)} (got {entry['license']!r})")
    judges = entry.get("judges")
    if judges is not None and (
        not isinstance(judges, list) or not judges or not all(isinstance(j, str) and j for j in judges)
    ):
        _fail(
            f"artifacts[{index}].judges must be null (historical events) or a non-empty list of judge identity strings"
        )
    payload = entry["payload"]
    if not isinstance(payload, dict):
        _fail(f"artifacts[{index}].payload must be an object")
    missing = [f for f in WINNERS_PAYLOAD_REQUIRED_FIELDS if f not in payload]
    if missing:
        _fail(f"artifacts[{index}].payload missing required fields: {missing}")
    _reject_unexpected_fields(payload, WINNERS_PAYLOAD_REQUIRED_FIELDS, f"artifacts[{index}].payload")
    path = payload["path"]
    parsed_path = PurePosixPath(path) if isinstance(path, str) else None
    path_parts = parsed_path.parts if parsed_path is not None else ()
    if (
        parsed_path is None
        or parsed_path.is_absolute()
        or len(path_parts) < 2
        or path_parts[0] != "payload"
        or any(part in {"", ".", ".."} or "\\" in part for part in path_parts)
        or parsed_path.as_posix() != path
    ):
        _fail(f"artifacts[{index}].payload.path must be a bundle-relative payload/ path")
    if not _is_hex64(payload["sha256"]):
        _fail(f"artifacts[{index}].payload.sha256 must be a 64-char sha256 hex string")
    if not isinstance(payload["bytes"], int) or payload["bytes"] < 0:
        _fail(f"artifacts[{index}].payload.bytes must be a non-negative int")
    return entry


def _require_directory(path: Path, label: str) -> None:
    _reject_leaf_symlink(path, label)
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        _fail(f"could not inspect {label}: {exc}")
    if not stat.S_ISDIR(mode):
        _fail(f"{label} must be a directory")


def _payload_inventory(payload_root: Path, relative_root: Path) -> set[Path]:
    """Enumerate regular payload files without following directory links."""
    present: set[Path] = set()
    try:
        for current, directories, files in os.walk(payload_root, followlinks=False):
            current_path = Path(current)
            for name in directories:
                candidate = current_path / name
                if candidate.is_symlink():
                    _fail(f"payload tree must not contain a symlink: {candidate.relative_to(relative_root)}")
            for name in files:
                candidate = current_path / name
                mode = candidate.lstat().st_mode
                if stat.S_ISLNK(mode):
                    _fail(f"payload tree must not contain a symlink: {candidate.relative_to(relative_root)}")
                if not stat.S_ISREG(mode):
                    _fail(f"payload tree must contain only regular files: {candidate.relative_to(relative_root)}")
                present.add(candidate.relative_to(relative_root))
    except OSError as exc:
        _fail(f"could not inspect payload tree: {exc}")
    return present


def _validated_payload_identity(root: Path, payload_root: Path, payload_rel: Path) -> tuple[str, int]:
    candidate = root / payload_rel
    _reject_symlink_below(payload_root, candidate, f"listed payload {payload_rel}")
    try:
        resolved_payload_root = payload_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as exc:
        _fail(f"listed payload missing: {payload_rel} ({exc})")
    if not resolved_candidate.is_relative_to(resolved_payload_root):
        _fail(f"listed payload escapes payload directory: {payload_rel}")
    return _regular_file_identity(candidate, f"listed payload {payload_rel}")


def verify_bundle(bundle_dir: str | Path) -> WinnersBundleReceipt:
    """Verify a winners-bundle envelope end to end (fail-closed)."""
    root = _canonical_leaf(Path(bundle_dir), "bundle directory")
    if not root.is_dir() or not os.path.lexists(root / "manifest.json"):
        _fail(f"no manifest.json in {root}")
    _require_directory(root, "bundle directory")
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(_read_regular_bytes(manifest_path, "manifest.json").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _fail(f"manifest.json is not valid JSON: {exc}")

    exported_at, entries, envelope_claim = _validate_manifest_structure(manifest, root)
    expected = hashlib.sha256(_canonical_manifest_bytes(manifest)).hexdigest()
    if expected != envelope_claim:
        _fail("envelope_sha256 does not match the manifest body")

    payload_root = root / "payload"
    _require_directory(payload_root, "payload directory")
    present = _payload_inventory(payload_root, root)
    receipts: list[WinnersArtifactInfo] = []
    listed: set[Path] = set()
    for index, entry in enumerate(entries):
        validated = _validate_artifact(entry, index)
        payload_rel = Path(validated["payload"]["path"])
        if payload_rel in listed:
            _fail(f"payload listed twice: {payload_rel}")
        listed.add(payload_rel)
        actual_digest, actual_bytes = _validated_payload_identity(root, payload_root, payload_rel)
        if actual_digest != validated["payload"]["sha256"]:
            _fail(f"payload digest mismatch: {payload_rel}")
        if actual_bytes != validated["payload"]["bytes"]:
            _fail(f"payload size mismatch: {payload_rel} ({actual_bytes} != {validated['payload']['bytes']})")
        receipts.append(
            WinnersArtifactInfo(
                artifact_id=validated["artifact_id"],
                event_id=validated["event_id"],
                domain=validated["domain"],
                axes=validated["axes"],
                level=validated["level"],
                license=validated["license"],
                judges=validated.get("judges"),
                payload_path=str(payload_rel),
                payload_sha256=actual_digest,
                payload_bytes=actual_bytes,
            )
        )

    unlisted = sorted(str(p) for p in present - listed)
    if unlisted:
        _fail(f"payload files not listed in the manifest: {unlisted}")

    return WinnersBundleReceipt(
        schema_version=REVIDEO_WINNERS_SCHEMA_VERSION,
        exported_at=exported_at,
        envelope_sha256=envelope_claim,
        artifacts=receipts,
    )


def _verify_staged_payloads(staged: Path, receipt: WinnersBundleReceipt) -> None:
    present = _payload_inventory(staged, staged)
    expected: set[Path] = set()
    for artifact in receipt.artifacts:
        payload_rel = Path(artifact.payload_path).relative_to("payload")
        expected.add(payload_rel)
        digest, size = _validated_payload_identity(staged, staged, payload_rel)
        if digest != artifact.payload_sha256 or size != artifact.payload_bytes:
            _fail(f"copied payload does not match verified bundle: {payload_rel}")
    if present != expected:
        _fail("copied payload set does not match verified bundle")


def stage_bundle(
    bundle_dir: str | Path,
    dest_root: str | Path,
) -> WinnersBundleReceipt:
    """Verify a bundle, then copy its payload into ``dest_root``."""
    receipt = verify_bundle(bundle_dir)
    bundle_root = _canonical_leaf(Path(bundle_dir), "bundle directory")
    dest_argument = Path(dest_root)
    dest = _canonical_leaf(dest_argument, "destination")
    _validate_destination(dest, allow_nonempty=True)
    staged = _temporary_sibling(dest)
    try:
        relative_paths: list[Path] = []
        for artifact in receipt.artifacts:
            payload_rel = Path(artifact.payload_path).relative_to("payload")
            relative_paths.append(payload_rel)
            payload_root = bundle_root / "payload"
            source = payload_root / payload_rel
            _reject_symlink_below(payload_root, source, f"listed payload {artifact.payload_path}")
            _copy_verified_payload(source, staged / payload_rel, artifact.payload_sha256, artifact.payload_bytes)
        _verify_staged_payloads(staged, receipt)
        if dest.exists() and any(dest.iterdir()):
            _merge_staged_payloads(staged, dest, relative_paths)
            _remove_temporary_tree(staged)
        else:
            _publish_directory(staged, dest)
        return receipt.model_copy(update={"staged_dir": str(dest_argument)})
    except ValidationError:
        _remove_temporary_tree(staged)
        raise
    except OSError as exc:
        _remove_temporary_tree(staged)
        _fail(f"payload copy failed: {exc}")
