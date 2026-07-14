"""Persisted mutation-fingerprint and authorization proof for salvage lineage.

Schema v2 adds ``mutation_fingerprint`` and ``authorization_decision_ids`` to
the salvage-lineage manifest so that prior-derivative reads can re-prove the
exact operation and authorization at render time. Schema v1 manifests remain
read-compatible but cannot bypass current authorization: replay treats them
as unauthenticated and still enforces the current protected state.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from kinocut.aivideo.protection import (
    MutationIntent,
    active_human_approval_bound_to,
    assert_no_protected_collision,
    decision_history,
    mutation_fingerprint,
)
from kinocut.aivideo.salvage_checks import PreservationCheck, _salvage_error
from kinocut.contracts.asset import AssetRecord
from kinocut.projectstore import Project, layout, store
from kinocut.rescue.operations import _sha256

SALVAGE_LINEAGE_SCHEMA_VERSION = 2
_V1_SCHEMA = 1
_SUPPORTED_SCHEMAS = {_V1_SCHEMA, SALVAGE_LINEAGE_SCHEMA_VERSION}


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def checked_hash(path: Path, *, missing_message: str) -> str:
    """Hash one existing in-store file with privacy-safe filesystem errors."""

    with store._mapped_os_errors():
        if not path.is_file():
            raise _salvage_error(missing_message, "salvage_integrity_failed")
        return _sha256(path)


def manifest_payload(
    *,
    operation: str,
    policy: dict[str, Any],
    policy_hash: str,
    source_asset_id: str,
    output_hash: str,
    preservation_checks: tuple[PreservationCheck, ...],
    intent: MutationIntent,
) -> dict[str, Any]:
    """Build the canonical v2 salvage-lineage manifest payload."""

    return {
        "schema_version": SALVAGE_LINEAGE_SCHEMA_VERSION,
        "operation": operation,
        "policy": policy,
        "policy_hash": policy_hash,
        "source_asset_id": source_asset_id,
        "output_hash": output_hash,
        "mutation_fingerprint": mutation_fingerprint(intent),
        "authorization_decision_ids": list(intent.authorization_decision_ids),
        "preservation_checks": [item.model_dump(mode="json") for item in preservation_checks],
    }


def install_manifest(project: Project, payload: dict[str, Any]) -> tuple[str, str]:
    """Persist the manifest immutably; return (artifact_id, relative_location)."""

    content = _canonical(payload)
    artifact_id = _digest(content)
    rel = layout.artifact_relative_path(artifact_id, "salvage-lineage.json")
    destination = store.safe_target(project, rel)
    with store._mapped_os_errors():
        destination.parent.mkdir(parents=True, exist_ok=True)
        exists = destination.exists()
    if exists:
        if checked_hash(destination, missing_message="lineage artifact is missing") != artifact_id:
            raise _salvage_error("lineage artifact integrity check failed", "salvage_integrity_failed")
        return artifact_id, str(rel)
    _atomic_link(destination, content, artifact_id)
    return artifact_id, str(rel)


def _atomic_link(destination: Path, content: bytes, artifact_id: str) -> None:
    """Atomically write content to a content-addressed destination."""

    with store._mapped_os_errors():
        fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".salvage.", suffix=".tmp")
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, destination)
            except FileExistsError:
                if _sha256(destination) != artifact_id:
                    raise _salvage_error(
                        "lineage artifact integrity check failed",
                        "salvage_integrity_failed",
                    ) from None
            store._fsync_dir(destination.parent)
        finally:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)


def _parse_checks(payload: dict[str, Any]) -> tuple[PreservationCheck, ...]:
    """Validate the manifest shape and return its preservation checks."""

    schema = payload.get("schema_version")
    if schema not in _SUPPORTED_SCHEMAS:
        raise _salvage_error("lineage artifact schema is unsupported", "salvage_integrity_failed")
    try:
        checks = tuple(PreservationCheck.model_validate(item) for item in payload["preservation_checks"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise _salvage_error("lineage artifact is invalid", "salvage_integrity_failed") from exc
    return checks


def _structural_mismatch(
    payload: dict[str, Any],
    *,
    operation: str,
    policy: dict[str, Any],
    policy_hash: str,
    source_asset_id: str,
    output_hash: str,
) -> bool:
    """Whether the manifest's structural fields disagree with the asset."""

    expected = {
        "operation": operation,
        "policy": policy,
        "policy_hash": policy_hash,
        "source_asset_id": source_asset_id,
        "output_hash": output_hash,
    }
    return any(payload.get(key) != value for key, value in expected.items())


def _verify_authorization_refs(
    project: Project,
    authorization_decision_ids: tuple[str, ...],
    expected_fingerprint: str,
) -> None:
    """Each stored auth ref must be active and human-approve-bound to fingerprint."""

    decisions, active_ids = decision_history(project)
    for decision_id in authorization_decision_ids:
        decision = decisions.get(decision_id)
        if active_human_approval_bound_to(decision, decision_id, active_ids, expected_fingerprint) is None:
            raise _salvage_error(
                "stored authorization reference is no longer valid",
                "salvage_integrity_failed",
            )


def _extract_v2_proof(
    payload: dict[str, Any],
    project: Project,
    expected_fingerprint: str,
) -> tuple[str, ...]:
    """Verify v2 mutation_fingerprint and authorization refs; return the refs."""

    stored_fingerprint = payload.get("mutation_fingerprint")
    if not isinstance(stored_fingerprint, str) or stored_fingerprint != expected_fingerprint:
        raise _salvage_error(
            "lineage artifact fingerprint is invalid or tampered",
            "salvage_integrity_failed",
        )
    raw_refs = payload.get("authorization_decision_ids")
    if not isinstance(raw_refs, list):
        raise _salvage_error(
            "lineage artifact authorization references are invalid",
            "salvage_integrity_failed",
        )
    stored_refs = tuple(str(ref) for ref in raw_refs)
    _verify_authorization_refs(project, stored_refs, expected_fingerprint)
    return stored_refs


def read_prior_derivative(
    project: Project,
    *,
    asset: AssetRecord,
    policy: dict[str, Any],
    policy_hash: str,
    intent: MutationIntent,
) -> tuple[str, str, tuple[PreservationCheck, ...]]:
    """Verify a prior derivative's manifest; fail closed on any mismatch.

    Returns ``(artifact_id, artifact_location, preservation_checks)``. The
    caller must have already verified the asset's output hash matches its
    content-addressed id and that the asset is the active derivative.
    """

    if len(asset.derived_artifact_ids) != 1:
        raise _salvage_error("lineage artifact reference is invalid", "salvage_integrity_failed")
    artifact_id = asset.derived_artifact_ids[0]
    rel = layout.artifact_relative_path(artifact_id, "salvage-lineage.json")
    artifact = store.safe_target(project, rel)
    if checked_hash(artifact, missing_message="published lineage artifact is missing") != artifact_id:
        raise _salvage_error("lineage artifact integrity check failed", "salvage_integrity_failed")
    try:
        with store._mapped_os_errors():
            payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _salvage_error("lineage artifact is invalid", "salvage_integrity_failed") from exc

    checks = _parse_checks(payload)
    expected_fingerprint = mutation_fingerprint(intent)
    if _structural_mismatch(
        payload,
        operation=policy["recipe"],
        policy=policy,
        policy_hash=policy_hash,
        source_asset_id=intent.source_asset,
        output_hash=asset.asset_id,
    ):
        raise _salvage_error("lineage artifact does not match its asset", "salvage_integrity_failed")

    schema = payload.get("schema_version")
    if schema == SALVAGE_LINEAGE_SCHEMA_VERSION:
        stored_refs = _extract_v2_proof(payload, project, expected_fingerprint)
    else:
        # v1 manifests predate persisted authorization proof. Treat them as
        # unauthenticated: replay cannot bypass current authorization, but
        # legacy renders without protected elements remain idempotent.
        stored_refs = ()

    if not all(check.passed for check in checks):
        raise _salvage_error("lineage artifact records failed preservation", "salvage_integrity_failed")

    # Enforce current protected state on replay. A protected lock that now
    # requires fresh approval blocks the replay even if the original render
    # proceeded without one.
    replay_intent = intent.model_copy(update={"authorization_decision_ids": stored_refs})
    assert_no_protected_collision(project, replay_intent)

    return artifact_id, str(rel), checks
