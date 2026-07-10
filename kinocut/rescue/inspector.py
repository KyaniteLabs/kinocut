"""Read-only, additive inspection of rescue plans and receipts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ._errors import INVALID_RESCUE_RECEIPT, rescue_error
from .models import receipt_integrity_sha256


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _confined(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def inspect_rescue(path: str) -> dict[str, Any]:
    """Inspect known v1 fields while tolerating future additive fields."""
    artifact = Path(os.path.realpath(path))
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise rescue_error("rescue artifact is not readable JSON", INVALID_RESCUE_RECEIPT) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("receipt_kind") not in {"rescue_plan", "rescue"}:
        raise rescue_error("unsupported rescue artifact", INVALID_RESCUE_RECEIPT)
    if not all(key in payload for key in ("tool", "status", "source")):
        raise rescue_error("rescue artifact is missing required v1 fields", INVALID_RESCUE_RECEIPT)

    package = payload.get("package", {})
    kind = payload["receipt_kind"]
    if kind == "rescue_plan":
        workspace_base = Path(os.path.realpath(artifact.parent / payload.get("workspace_root", ".")))
        if workspace_base == Path(workspace_base.anchor) or not _confined(artifact.parent, workspace_base):
            raise rescue_error("rescue plan workspace reference is unsafe", INVALID_RESCUE_RECEIPT)
        records = [(payload.get("source", {}), workspace_base)]
        records.extend((record, workspace_base) for record in payload.get("preview_artifacts", []))
    else:
        package_path = package.get("path") if isinstance(package, dict) else None
        packaged_receipt = isinstance(package_path, str) and artifact.parent.name == Path(package_path).name
        output_base = artifact.parent.parent if packaged_receipt else artifact.parent
        package_base = artifact.parent if packaged_receipt else output_base / package_path if package_path else output_base
        workspace_base = Path(os.path.realpath(output_base / payload.get("workspace_root", ".")))
        if workspace_base == Path(workspace_base.anchor) or not _confined(output_base, workspace_base):
            raise rescue_error("rescue receipt workspace reference is unsafe", INVALID_RESCUE_RECEIPT)
        package_base = Path(os.path.realpath(package_base))
        if not _confined(package_base, output_base):
            package_base = output_base / ".invalid-package-root"
        records = [(payload.get("source", {}), workspace_base)]
        if isinstance(package, dict):
            records.extend((record, package_base) for record in package.get("artifacts", []))
    artifacts = []
    if kind == "rescue" and isinstance(payload.get("receipt_sha256"), str):
        actual_receipt_hash = receipt_integrity_sha256(payload)
        artifacts.append(
            {
                "path": payload.get("receipt_path") or artifact.name,
                "present": True,
                "matching": actual_receipt_hash == payload["receipt_sha256"],
                "expected_sha256": payload["receipt_sha256"],
                "actual_sha256": actual_receipt_hash,
            }
        )
    for record, base in records:
        if not isinstance(record, dict) or not record.get("path"):
            continue
        candidate = Path(os.path.realpath(base / record["path"]))
        present = _confined(candidate, base) and candidate.is_file()
        if present and record.get("kind") == "receipt":
            try:
                actual = receipt_integrity_sha256(json.loads(candidate.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError):
                actual = None
        else:
            actual = _hash(candidate) if present else None
        expected = record.get("sha256")
        artifacts.append({"path": record["path"], "present": present, "matching": present and (expected is None or actual == expected), "expected_sha256": expected, "actual_sha256": actual})
    return {
        "kind": kind, "schema_version": 1, "tool": payload["tool"], "status": payload["status"],
        "dispositions": {name: len(payload.get(name, [])) for name in ("safe_repairs", "recommendations", "unavailable_repairs", "blocked_repairs")},
        "approved_repair_ids": payload.get("approved_repair_ids", []), "applied_repair_ids": payload.get("applied_repair_ids", []), "skipped_repair_ids": payload.get("skipped_repair_ids", []),
        "verification": payload.get("verification", []), "package": package, "privacy": payload.get("privacy", {}), "warnings": payload.get("warnings", []), "cleanup": payload.get("cleanup", {}), "resume": payload.get("resume", {}),
        "integrity": {"all_present": all(item["present"] for item in artifacts), "all_matching": all(item["matching"] for item in artifacts), "artifacts": artifacts},
    }
