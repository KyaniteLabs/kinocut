"""Read-only, additive inspection of rescue plans and receipts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ._errors import INVALID_RESCUE_RECEIPT, rescue_error


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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

    records = [payload.get("source", {})]
    package = payload.get("package", {})
    if isinstance(package, dict):
        records.extend(package.get("artifacts", []))
    records.extend(payload.get("preview_artifacts", []))
    artifacts = []
    for record in records:
        if not isinstance(record, dict) or not record.get("path"):
            continue
        candidate = Path(os.path.realpath(artifact.parent / record["path"]))
        confined = candidate == artifact.parent or artifact.parent in candidate.parents
        present = confined and candidate.is_file()
        actual = _hash(candidate) if present else None
        expected = record.get("sha256")
        artifacts.append({"path": record["path"], "present": present, "matching": present and (expected is None or actual == expected), "expected_sha256": expected, "actual_sha256": actual})
    return {
        "kind": payload["receipt_kind"], "schema_version": 1, "tool": payload["tool"], "status": payload["status"],
        "dispositions": {name: len(payload.get(name, [])) for name in ("safe_repairs", "recommendations", "unavailable_repairs", "blocked_repairs")},
        "approved_repair_ids": payload.get("approved_repair_ids", []), "applied_repair_ids": payload.get("applied_repair_ids", []), "skipped_repair_ids": payload.get("skipped_repair_ids", []),
        "verification": payload.get("verification", []), "package": package, "privacy": payload.get("privacy", {}), "warnings": payload.get("warnings", []), "cleanup": payload.get("cleanup", {}), "resume": payload.get("resume", {}),
        "integrity": {"all_present": all(item["present"] for item in artifacts), "all_matching": all(item["matching"] for item in artifacts), "artifacts": artifacts},
    }
