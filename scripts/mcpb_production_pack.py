#!/usr/bin/env python3
"""Aggregate exact MCPB build, validation, runtime, and review evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import stat
from pathlib import Path
from typing import Any


MAX_RECEIPT_BYTES = 64 * 1024
REQUIRED_HOSTS = {"linux", "macos", "windows"}
REQUIRED_RUNTIME_GATES = {
    "initialize",
    "list_tools",
    "core_call",
    "core_after_missing_whisper",
    "missing_whisper",
    "hyperframes_not_found",
    "session_reuse",
    "cleanup_probe",
}
REQUIRED_OPTIONAL_GATES = {"imagehash_detected", "hyperframes_0_8_30_detected", "scene_tool_callable"}
REQUIRED_DESKTOP_GATES = {
    "wheel_import",
    "server_start",
    "mcp_round_trip",
    "unsigned_warning_observed",
    "local_access_label_reviewed",
}
REVIEWED_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _canonical_hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _valid_review(review: Any) -> bool:
    if not isinstance(review, dict) or review.get("status") != "passed":
        return False
    reviewer = review.get("reviewer")
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(reviewed_at, str):
        return False
    if REVIEWED_AT_PATTERN.fullmatch(reviewed_at) is None:
        return False
    try:
        dt.datetime.strptime(reviewed_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _read_receipt(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        mode = path.stat(follow_symlinks=False).st_mode
        if path.is_symlink() or not stat.S_ISREG(mode) or path.stat().st_size > MAX_RECEIPT_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _bound(receipt: dict[str, Any] | None, source: str, digest: str | None, kind: str) -> bool:
    return bool(
        receipt
        and _canonical_hex(source, 40)
        and _canonical_hex(digest, 64)
        and receipt.get("artifact_kind") == kind
        and receipt.get("source_sha") == source
        and receipt.get("archive_sha256") == digest
    )


def _artifact(build: dict[str, Any] | None, source: str) -> tuple[dict[str, Any], str | None]:
    inventory = ["README.md", "manifest.json", "server/launcher.js"]
    digest = build.get("archive_sha256") if build else None
    valid = bool(
        build
        and _canonical_hex(source, 40)
        and build.get("artifact_kind") == "mcpb_build_receipt"
        and build.get("source_sha") == source
        and _canonical_hex(digest, 64)
        and build.get("archive_inventory") == inventory
    )
    return {"status": "built" if valid else "not_run", "sha256": digest if valid else None}, digest if valid else None


def _official(receipt: dict[str, Any] | None, source: str, digest: str | None) -> dict[str, Any]:
    valid = _bound(receipt, source, digest, "mcpb_official_validation") and receipt.get("validator") == {
        "name": "@anthropic-ai/mcpb",
        "version": "2.1.2",
    }
    valid = bool(valid and receipt.get("source_manifest") == "passed" and receipt.get("extracted_manifest") == "passed")
    wheel_digest = receipt.get("wheel_sha256") if receipt and valid else None
    valid = bool(valid and _canonical_hex(wheel_digest, 64))
    return {
        "status": "passed" if valid else "not_run",
        "validator": "@anthropic-ai/mcpb@2.1.2",
        "wheel_sha256": wheel_digest if valid else None,
    }


def _hosted(
    receipts: list[dict[str, Any] | None], source: str, digest: str | None, wheel_digest: str | None
) -> dict[str, Any]:
    states: dict[str, Any] = {}
    duplicates: set[str] = set()
    for receipt in receipts:
        host = receipt.get("os") if receipt else None
        if host not in REQUIRED_HOSTS:
            continue
        if host in states:
            duplicates.add(host)
        gates = receipt.get("gates", {})
        valid = _bound(receipt, source, digest, "mcpb_hosted_runtime")
        valid = bool(
            valid
            and receipt.get("status") == "passed"
            and receipt.get("cleanup") == "passed"
            and _canonical_hex(wheel_digest, 64)
            and receipt.get("wheel_sha256") == wheel_digest
            and isinstance(receipt.get("architecture"), str)
            and bool(receipt["architecture"].strip())
            and receipt.get("archive_inventory") == ["README.md", "manifest.json", "server/launcher.js"]
            and isinstance(gates, dict)
            and {name for name, state in gates.items() if state == "passed"} >= REQUIRED_RUNTIME_GATES
        )
        states[host] = {"status": "passed" if valid else "failed"}
    for host in duplicates:
        states[host] = {"status": "failed"}
    for host in REQUIRED_HOSTS - states.keys():
        states[host] = {"status": "not_run"}
    return dict(sorted(states.items()))


def _optional(
    receipts: list[dict[str, Any] | None], source: str, digest: str | None, wheel_digest: str | None
) -> dict[str, str]:
    receipt = receipts[0] if len(receipts) == 1 else None
    gates = receipt.get("gates", {}) if receipt else {}
    valid = _bound(receipt, source, digest, "mcpb_optional_dependencies")
    valid = bool(
        valid
        and receipt.get("os") == "linux"
        and isinstance(receipt.get("architecture"), str)
        and bool(receipt["architecture"].strip())
        and receipt.get("status") == "passed"
        and receipt.get("cleanup") == "passed"
        and _canonical_hex(wheel_digest, 64)
        and receipt.get("wheel_sha256") == wheel_digest
        and receipt.get("archive_inventory") == ["README.md", "manifest.json", "server/launcher.js"]
        and isinstance(gates, dict)
        and {name for name, state in gates.items() if state == "passed"} >= REQUIRED_OPTIONAL_GATES
    )
    return {"present": "passed" if valid else "not_run"}


def _desktop(
    receipts: list[dict[str, Any] | None], source: str, digest: str | None, wheel_digest: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    states: dict[str, Any] = {}
    duplicates: set[str] = set()
    for receipt in receipts:
        host = receipt.get("os") if receipt else None
        if host not in {"macos", "windows"}:
            continue
        if host in states:
            duplicates.add(host)
        gates = receipt.get("gates", {})
        review = receipt.get("human_review", {})
        valid = _bound(receipt, source, digest, "mcpb_desktop_install")
        valid = bool(
            valid
            and receipt.get("status") == "passed"
            and _canonical_hex(wheel_digest, 64)
            and receipt.get("wheel_sha256") == wheel_digest
            and isinstance(receipt.get("architecture"), str)
            and bool(receipt["architecture"].strip())
            and isinstance(gates, dict)
            and {name for name, state in gates.items() if state == "passed"} >= REQUIRED_DESKTOP_GATES
            and _valid_review(review)
        )
        state = {"status": "passed" if valid else "failed"}
        if valid:
            state.update(
                architecture=receipt["architecture"],
                reviewer=review["reviewer"],
                reviewed_at=review["reviewed_at"],
            )
        states[host] = state
    for host in duplicates:
        states[host] = {"status": "failed"}
    complete = len(receipts) == 2 and len(states) == 2 and all(item["status"] == "passed" for item in states.values())
    human = {"status": "passed" if complete else "not_run"}
    return dict(sorted(states.items())), human


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("dist/mcpb-production"))
    parser.add_argument("--source-sha", default="")
    parser.add_argument("--build-receipt", type=Path)
    parser.add_argument("--official-validation-receipt", type=Path)
    parser.add_argument("--hosted-runtime-receipt", type=Path, action="append", default=[])
    parser.add_argument("--optional-dependencies-receipt", type=Path, action="append", default=[])
    parser.add_argument("--desktop-install-receipt", type=Path, action="append", default=[])
    parser.add_argument("--require-ready", choices=("ci_validated", "install_reviewed"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    build = _read_receipt(args.build_receipt)
    artifact, digest = _artifact(build, args.source_sha)
    official = _official(_read_receipt(args.official_validation_receipt), args.source_sha, digest)
    wheel_digest = official["wheel_sha256"]
    hosted = _hosted(
        [_read_receipt(path) for path in args.hosted_runtime_receipt], args.source_sha, digest, wheel_digest
    )
    optional = _optional(
        [_read_receipt(path) for path in args.optional_dependencies_receipt], args.source_sha, digest, wheel_digest
    )
    desktop, human_review = _desktop(
        [_read_receipt(path) for path in args.desktop_install_receipt], args.source_sha, digest, wheel_digest
    )
    ci_ready = artifact["status"] == "built" and official["status"] == "passed"
    ci_ready = ci_ready and all(item["status"] == "passed" for item in hosted.values())
    absent_ready = all(item["status"] == "passed" for item in hosted.values())
    optional["absent"] = "passed" if absent_ready else "not_run"
    ci_ready = ci_ready and optional["present"] == "passed" and optional["absent"] == "passed"
    install_ready = ci_ready and human_review["status"] == "passed"
    status = "install_reviewed" if install_ready else "ci_validated" if ci_ready else "blocked"
    checklist = {
        "artifact_kind": "mcpb_readiness_receipt",
        "source_sha": args.source_sha if _canonical_hex(args.source_sha, 40) else None,
        "artifact": artifact,
        "official_validation": official,
        "hosted_runtime": hosted,
        "optional_dependencies": optional,
        "desktop_install_review": desktop,
        "signing": {"status": "unsigned", "rationale": "supported user-configured-local-access product"},
        "publication": {"status": "not_attempted"},
        "human_review": human_review,
        "candidate_status": status,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "production-checklist.json").write_text(json.dumps(checklist, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(checklist, sort_keys=True))
    return 2 if args.require_ready and status != args.require_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
