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
import shutil
from pathlib import Path
from typing import Any

from .defaults import REVIDEO_WINNERS_SCHEMA_VERSION
from .errors import ValidationError
from .revideo_engine import _sha256_file
from .revideo_models import WinnersArtifactInfo, WinnersBundleReceipt
from .validation import (
    WINNERS_ARTIFACT_OPTIONAL_FIELDS,
    WINNERS_ARTIFACT_REQUIRED_FIELDS,
    WINNERS_HEX64_CHARS,
    WINNERS_KNOWN_LICENSES,
    WINNERS_MANIFEST_REQUIRED_FIELDS,
    WINNERS_PAYLOAD_REQUIRED_FIELDS,
)


def _fail(detail: str) -> None:
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


def _prepare_payload_dir(dest_path: Path) -> Path:
    """Validate the destination and create an empty ``payload/`` directory.

    Fail closed rather than deleting data: a second write with a different
    artifact set would leave stale payload files that no longer appear in the
    new manifest, so verify_bundle would (correctly) reject the bundle.
    """
    payload_dir = dest_path / "payload"
    if payload_dir.is_dir() and any(payload_dir.iterdir()):
        _fail(f"destination payload/ directory is not empty: {payload_dir} — use a fresh bundle directory")
    payload_dir.mkdir(parents=True, exist_ok=True)
    return payload_dir


def _ingest_artifact(
    spec: dict[str, Any],
    payload_dir: Path,
    used_names: set[str],
    index: int,
) -> tuple[dict[str, Any], WinnersArtifactInfo]:
    """Copy one payload source into the bundle and build its manifest entry.

    Metadata uses ``.get()`` so a missing field surfaces as a
    ValidationError from ``_validate_artifact``, never a raw KeyError, and
    every entry is validated under the same contract the verifier applies —
    the writer must not emit a self-invalidating bundle (CodeRabbit, #489).
    """
    source = Path(spec["payload_source"])
    if not source.is_file():
        _fail(f"payload source missing: {source}")
    name = source.name
    if name in used_names:
        _fail(f"duplicate payload filename: {name}")
    used_names.add(name)
    shutil.copyfile(source, payload_dir / name)
    digest = _sha256_file(payload_dir / name)
    size = (payload_dir / name).stat().st_size
    payload_rel = f"payload/{name}"
    entry = {
        "artifact_id": spec.get("artifact_id"),
        "event_id": spec.get("event_id"),
        "domain": spec.get("domain"),
        "axes": spec.get("axes"),
        "level": spec.get("level"),
        "license": spec.get("license"),
        "payload": {"path": payload_rel, "sha256": digest, "bytes": size},
    }
    if spec.get("judges") is not None:
        entry["judges"] = list(spec["judges"])
    _validate_artifact(entry, index)
    info = WinnersArtifactInfo(
        artifact_id=entry["artifact_id"],
        event_id=entry["event_id"],
        domain=entry["domain"],
        axes=entry["axes"],
        level=entry["level"],
        license=entry["license"],
        judges=entry.get("judges"),
        payload_path=payload_rel,
        payload_sha256=digest,
        payload_bytes=size,
    )
    return entry, info


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
    dest_path = Path(dest)
    if not artifacts:
        # A bundle whose manifest lists no artifacts can never pass
        # verify_bundle; refuse it before touching the destination.
        _fail("artifacts must be a non-empty list")
    payload_dir = _prepare_payload_dir(dest_path)

    manifest_artifacts: list[dict[str, Any]] = []
    receipt_artifacts: list[WinnersArtifactInfo] = []
    used_names: set[str] = set()
    for index, spec in enumerate(artifacts):
        entry, info = _ingest_artifact(spec, payload_dir, used_names, index)
        manifest_artifacts.append(entry)
        receipt_artifacts.append(info)

    manifest: dict[str, Any] = {
        "schema_version": REVIDEO_WINNERS_SCHEMA_VERSION,
        "exported_at": exported_at,
        "artifacts": manifest_artifacts,
    }
    envelope = hashlib.sha256(_canonical_manifest_bytes(manifest)).hexdigest()
    manifest["envelope_sha256"] = envelope
    (dest_path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return WinnersBundleReceipt(
        schema_version=REVIDEO_WINNERS_SCHEMA_VERSION,
        exported_at=exported_at,
        envelope_sha256=envelope,
        artifacts=receipt_artifacts,
    )


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
    if not isinstance(path, str) or not path.startswith("payload/") or ".." in path:
        _fail(f"artifacts[{index}].payload.path must be a bundle-relative payload/ path")
    if not _is_hex64(payload["sha256"]):
        _fail(f"artifacts[{index}].payload.sha256 must be a 64-char sha256 hex string")
    if not isinstance(payload["bytes"], int) or payload["bytes"] < 0:
        _fail(f"artifacts[{index}].payload.bytes must be a non-negative int")
    return entry


def verify_bundle(bundle_dir: str | Path) -> WinnersBundleReceipt:
    """Verify a winners-bundle envelope end to end (fail-closed)."""
    root = Path(bundle_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        _fail(f"no manifest.json in {root}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"manifest.json is not valid JSON: {exc}")

    exported_at, entries, envelope_claim = _validate_manifest_structure(manifest, root)
    expected = hashlib.sha256(_canonical_manifest_bytes(manifest)).hexdigest()
    if expected != envelope_claim:
        _fail("envelope_sha256 does not match the manifest body")

    receipts: list[WinnersArtifactInfo] = []
    listed: set[Path] = set()
    for index, entry in enumerate(entries):
        validated = _validate_artifact(entry, index)
        payload_rel = Path(validated["payload"]["path"])
        if payload_rel in listed:
            _fail(f"payload listed twice: {payload_rel}")
        listed.add(payload_rel)
        payload_file = root / payload_rel
        if not payload_file.is_file():
            _fail(f"listed payload missing: {payload_rel}")
        actual_digest = _sha256_file(payload_file)
        if actual_digest != validated["payload"]["sha256"]:
            _fail(f"payload digest mismatch: {payload_rel}")
        actual_bytes = payload_file.stat().st_size
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

    payload_root = root / "payload"
    present = {p.relative_to(root) for p in payload_root.rglob("*") if p.is_file()} if payload_root.is_dir() else set()
    unlisted = sorted(str(p) for p in present - listed)
    if unlisted:
        _fail(f"payload files not listed in the manifest: {unlisted}")

    return WinnersBundleReceipt(
        schema_version=REVIDEO_WINNERS_SCHEMA_VERSION,
        exported_at=exported_at,
        envelope_sha256=envelope_claim,
        artifacts=receipts,
    )


def stage_bundle(
    bundle_dir: str | Path,
    dest_root: str | Path,
) -> WinnersBundleReceipt:
    """Verify a bundle, then copy its payload into ``dest_root``."""
    receipt = verify_bundle(bundle_dir)
    dest = Path(dest_root)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(bundle_dir) / "payload", dest, dirs_exist_ok=True)
    return receipt.model_copy(update={"staged_dir": str(dest)})
