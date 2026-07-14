"""One validated, canonical-store-backed public boundary for Wave 3."""

from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from kinocut.contracts._common import Sha256
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.asset import AssetRecord
from kinocut.contracts.review import DecisionType, ReviewDecision
from kinocut.contracts.verdict import ClipVerdict
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path
from kinocut.limits import (
    MAX_WAVE3_AUTH_DECISION_IDS,
    MAX_WAVE3_JSON_BYTES,
    MAX_WAVE3_VERDICT_IDS,
)
from kinocut.projectstore import Project, open_project, read_records
from kinocut.projectstore import store
from kinocut.source_identity import stream_source_identity

Operation = Literal["verdict", "acceptance_eval", "body_swap", "salvage"]
logger = logging.getLogger(__name__)
_SHA = TypeAdapter(Sha256)
_REQUEST_FIELDS = {
    "verdict": frozenset({"project_dir", "verdict"}),
    "acceptance_eval": frozenset({"project_dir", "acceptance_spec_id", "verdict_ids"}),
    "body_swap": frozenset(
        {
            "project_dir",
            "video_source",
            "audio_source",
            "output_path",
            "duration_policy",
            "authorization_decision_ids",
        }
    ),
    "salvage": frozenset(
        {
            "project_dir",
            "source_asset_id",
            "recipe",
            "policy",
            "acceptance_spec_id",
            "authorization_decision_ids",
        }
    ),
}


def _error(message: str, code: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _existing_project(project_dir: str) -> Project:
    root = Path(_string(project_dir, "Wave 3 project"))
    store_root = root / ".kinocut"
    if not root.is_dir() or root.is_symlink() or not store_root.is_dir() or store_root.is_symlink():
        raise _error("Wave 3 project does not exist", "wave3_project_missing")
    return open_project(root)


def _bounded_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error(f"{label} must be an object", "wave3_input_invalid")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise _error(f"{label} is invalid", "wave3_input_invalid") from exc
    if len(encoded) > MAX_WAVE3_JSON_BYTES:
        raise _error(f"{label} exceeds its size limit", "wave3_input_too_large")
    return value


def _sha(value: Any, label: str) -> str:
    try:
        return _SHA.validate_python(value)
    except ValidationError as exc:
        raise _error(f"{label} is invalid", "wave3_id_invalid") from exc


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error(f"{label} is invalid", "wave3_input_invalid")
    try:
        encoded = value.encode()
    except UnicodeError as exc:
        raise _error(f"{label} is invalid", "wave3_input_invalid") from exc
    if len(encoded) > MAX_WAVE3_JSON_BYTES:
        raise _error(f"{label} exceeds its size limit", "wave3_input_too_large")
    return value


def _id_list(value: Any, label: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise _error(f"{label} is invalid", "wave3_collection_invalid")
    result = tuple(_sha(item, label) for item in value)
    if len(set(result)) != len(result):
        raise _error(f"{label} contains duplicates", "wave3_collection_invalid")
    return result


def _validated(model: type, value: Any, *, code: str) -> Any:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        logger.warning("Wave 3 record validation failed: %s", model.__name__)
        raise _error("Wave 3 record is invalid", code) from exc


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _active_records(project: Project, kind: str, model: type) -> list[Any]:
    records = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in records if item.supersedes is not None}
    return [item for item in records if item.record_id not in superseded]


def _active_record(project: Project, kind: str, model: type, record_id: Any, label: str) -> Any:
    wanted = _sha(record_id, label)
    matches = [item for item in _active_records(project, kind, model) if item.record_id == wanted]
    if len(matches) != 1:
        raise _error(f"{label} is not one active stored record", "wave3_record_missing")
    return matches[0]


def _active_asset(project: Project, asset_id: str) -> AssetRecord:
    matches = [item for item in _active_records(project, "asset_record", AssetRecord) if item.asset_id == asset_id]
    if len(matches) != 1:
        raise _error("asset is not one active stored record", "wave3_asset_missing")
    return matches[0]


def _asset_for_input(project: Project, value: Any, label: str) -> tuple[str, AssetRecord, Any]:
    validated = _validate_input_path(_string(value, label))
    resolved = Path(validated).resolve()
    matches = []
    for asset in _active_records(project, "asset_record", AssetRecord):
        target = store.safe_target(project, PurePosixPath(asset.original_location))
        if target.resolve() == resolved and target.is_file():
            matches.append(asset)
    if len(matches) != 1:
        raise _error(f"{label} is not one active stored asset", "wave3_asset_missing")
    asset = matches[0]
    try:
        identity = stream_source_identity(validated)
    except MCPVideoError as exc:
        raise _error(f"{label} integrity cannot be verified", "wave3_asset_integrity_failed") from exc
    if identity.asset_id != asset.asset_id or identity.byte_size != asset.byte_size:
        raise _error(f"{label} integrity does not match its record", "wave3_asset_integrity_failed")
    return validated, asset, identity


def _active_authorizations(project: Project, ids: tuple[str, ...]) -> tuple[str, ...]:
    from kinocut.aivideo.protection import decision_history

    decisions, active_ids = decision_history(project)
    for decision_id in ids:
        decision = decisions.get(decision_id)
        if not (
            decision_id in active_ids
            and type(decision) is ReviewDecision
            and decision.project_id == project.project_id
            and decision.actor == "human"
            and decision.created_by.startswith("human")
            and decision.decision is DecisionType.APPROVE
        ):
            raise _error(
                "authorization is not one active stored human approval",
                "wave3_authorization_invalid",
            )
    return ids


def _run_verdict(project_dir: str, verdict: Any) -> dict[str, Any]:
    from kinocut.aivideo.verdict import approval_decision, record_verdict
    from kinocut.contracts.verdict import Disposition

    parsed = _validated(
        ClipVerdict,
        _bounded_mapping(verdict, "verdict"),
        code="wave3_verdict_invalid",
    )
    project = _existing_project(project_dir)
    if parsed.project_id != project.project_id:
        raise _error("verdict belongs to another project", "wave3_record_foreign")
    spec = _active_record(
        project,
        "generation_acceptance_spec",
        GenerationAcceptanceSpec,
        parsed.acceptance_spec_id,
        "acceptance spec",
    )
    asset = _active_asset(project, parsed.asset_hash)
    if spec.project_id != parsed.project_id or asset.project_id != parsed.project_id:
        raise _error("verdict dependencies belong to another project", "wave3_record_foreign")
    if (
        parsed.disposition in {Disposition.APPROVED, Disposition.APPROVED_WITH_TRIM}
        and approval_decision(project, spec, parsed) is None
    ):
        raise _error(
            "approved verdict requires active exact human evidence",
            "wave3_approval_invalid",
        )
    stored = record_verdict(project, parsed)
    return {"success": True, "operation": "verdict", "verdict": _dump(stored)}


def _run_acceptance(project_dir: str, acceptance_spec_id: Any, verdict_ids: Any) -> dict[str, Any]:
    from kinocut.aivideo.verdict import acceptance_eval

    spec_id = _sha(acceptance_spec_id, "acceptance spec")
    ids = _id_list(verdict_ids, "verdict ids", MAX_WAVE3_VERDICT_IDS)
    project = _existing_project(project_dir)
    spec = _active_record(
        project,
        "generation_acceptance_spec",
        GenerationAcceptanceSpec,
        spec_id,
        "acceptance spec",
    )
    verdicts = tuple(_active_record(project, "clip_verdict", ClipVerdict, item, "verdict") for item in ids)
    if spec.project_id != project.project_id or any(
        item.project_id != spec.project_id or item.acceptance_spec_id != spec.record_id for item in verdicts
    ):
        raise _error("acceptance evidence belongs to another record", "wave3_record_foreign")
    report = acceptance_eval(project, spec=spec, verdicts=verdicts)
    return {"success": True, "operation": "acceptance_eval", "report": _dump(report)}


def _run_body_swap(
    project_dir: str,
    video_source: Any,
    audio_source: Any,
    output_path: str,
    *,
    duration_policy: str | None,
    authorization_decision_ids: Any,
) -> dict[str, Any]:
    from kinocut.engine_body_swap import body_swap

    auth = _id_list(
        authorization_decision_ids,
        "authorization decision ids",
        MAX_WAVE3_AUTH_DECISION_IDS,
    )
    output = _string(output_path, "output path")
    if duration_policy is not None:
        _string(duration_policy, "duration policy")
    project = _existing_project(project_dir)
    auth = _active_authorizations(project, auth)
    video_path, _, video_identity = _asset_for_input(project, video_source, "video source")
    audio_path, _, audio_identity = _asset_for_input(project, audio_source, "audio source")
    try:
        result = body_swap(
            video_path,
            audio_path,
            output,
            duration_policy=duration_policy,
            project=project,
            authorization_decision_ids=auth,
            verified_source_identities=(video_identity, audio_identity),
        )
    except MCPVideoError as exc:
        if exc.code == "source_identity_changed":
            raise _error(
                "body-swap source integrity cannot be verified",
                "wave3_asset_integrity_failed",
            ) from exc
        raise
    return {"success": True, "operation": "body_swap", **result}


def _run_salvage(
    project_dir: str,
    source_asset_id: Any,
    recipe: str,
    policy: Any,
    acceptance_spec_id: Any,
    *,
    authorization_decision_ids: Any,
) -> dict[str, Any]:
    from kinocut.aivideo.salvage import create_salvage_derivative

    validated_policy = _bounded_mapping(policy, "salvage policy")
    auth = _id_list(
        authorization_decision_ids,
        "authorization decision ids",
        MAX_WAVE3_AUTH_DECISION_IDS,
    )
    source_id = _sha(source_asset_id, "source asset")
    spec_id = _sha(acceptance_spec_id, "acceptance spec")
    selected_recipe = _string(recipe, "salvage recipe")
    project = _existing_project(project_dir)
    auth = _active_authorizations(project, auth)
    spec = _active_record(
        project,
        "generation_acceptance_spec",
        GenerationAcceptanceSpec,
        spec_id,
        "acceptance spec",
    )
    if spec.project_id != project.project_id:
        raise _error("acceptance spec belongs to another project", "wave3_record_foreign")
    result = create_salvage_derivative(
        project,
        source_asset_id=source_id,
        recipe=selected_recipe,
        policy=validated_policy,
        acceptance_spec_id=spec.record_id,
        authorization_decision_ids=auth,
    )
    return {"success": True, "operation": "salvage", "result": _dump(result)}


def run_wave3_operation(operation: Operation, **kwargs: Any) -> dict[str, Any]:
    """Run one governed Wave 3 operation against canonical project records."""

    runners = {
        "verdict": _run_verdict,
        "acceptance_eval": _run_acceptance,
        "body_swap": _run_body_swap,
        "salvage": _run_salvage,
    }
    try:
        runner = runners[operation]
        fields = _REQUEST_FIELDS[operation]
    except (KeyError, TypeError) as exc:
        raise _error("Wave 3 operation is invalid", "wave3_operation_invalid") from exc
    if set(kwargs) != fields:
        raise _error("Wave 3 request shape is invalid", "wave3_input_invalid")
    return runner(**kwargs)
