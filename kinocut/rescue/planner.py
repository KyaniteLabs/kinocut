"""Deterministic planning for policy-safe local video rescue."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..workflow._versions import versions
from ._errors import (
    INVALID_RESCUE_PLAN,
    RESCUE_PLAN_MISMATCH,
    RESCUE_POLICY_VIOLATION,
    UNSAFE_RESCUE_OUTPUT,
    rescue_error,
)
from .analyzer import AnalysisResult, analyze_source
from .capabilities import snapshot_capabilities
from .models import (
    Disposition,
    PackageIntent,
    Repair,
    RescuePlan,
    RescuePolicy,
    canonical_payload,
)
from .policy import POLICY_ID, POLICY_VERSION, evaluate_finding


def _realpath(path: str | Path) -> Path:
    return Path(os.path.realpath(os.path.abspath(os.fspath(path))))


def _is_confined(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalize_entry_paths(source_path: str, output_dir: str) -> tuple[Path, Path, Path]:
    if not source_path or not output_dir:
        raise rescue_error("source_path and output_dir are required", UNSAFE_RESCUE_OUTPUT)
    source_entry = Path(os.path.abspath(os.fspath(source_path)))
    output_entry = Path(os.path.abspath(os.fspath(output_dir)))
    source = _realpath(source_path)
    output = _realpath(output_dir)
    if not source.is_file():
        raise rescue_error("source_path must be a readable regular file", UNSAFE_RESCUE_OUTPUT)
    if output == source or (output.exists() and not output.is_dir()):
        raise rescue_error("output_dir must be a directory that does not overwrite the source", UNSAFE_RESCUE_OUTPUT)

    lexical_workspace = Path(os.path.commonpath((source_entry, output_entry)))
    workspace = _realpath(lexical_workspace)
    if workspace == Path(workspace.anchor) or not workspace.is_dir():
        raise rescue_error(
            "source_path and output_dir must share a bounded workspace directory",
            UNSAFE_RESCUE_OUTPUT,
        )
    if not _is_confined(source, workspace) or not _is_confined(output, workspace):
        raise rescue_error("rescue paths escaped their workspace", UNSAFE_RESCUE_OUTPUT)
    return source, output, workspace


def _normalize_save_plan(save_plan: str | None, output: Path) -> Path | None:
    if save_plan is None:
        return None
    if not save_plan:
        raise rescue_error("save_plan must be a non-empty JSON path", UNSAFE_RESCUE_OUTPUT)
    plan_path = _realpath(save_plan)
    if plan_path.suffix.lower() != ".json" or not _is_confined(plan_path, output):
        raise rescue_error("save_plan must be a JSON file inside output_dir", UNSAFE_RESCUE_OUTPUT)
    if plan_path.exists() and not plan_path.is_file():
        raise rescue_error("save_plan must identify a regular file", UNSAFE_RESCUE_OUTPUT)
    return plan_path


def _build_package_intents(analysis: AnalysisResult, capabilities: dict[str, Any]) -> list[PackageIntent]:
    intents = [
        PackageIntent(kind="master", required=True, status="available"),
        PackageIntent(kind="sharing_copy", required=True, status="available"),
        PackageIntent(kind="receipt", required=True, status="available"),
    ]
    has_audio = any(stream.get("codec_type") == "audio" for stream in analysis.source.streams)
    whisper = capabilities.get("whisper", {})
    whisper_models = capabilities.get("whisper_models", {})
    base_model = whisper_models.get("base", {}) if isinstance(whisper_models, dict) else {}
    whisper_available = (
        isinstance(whisper, dict)
        and whisper.get("available") is True
        and isinstance(base_model, dict)
        and base_model.get("available") is True
    )
    derived_available = has_audio and whisper_available
    if derived_available:
        intents.extend(
            [
                PackageIntent(kind="captions", required=False, status="available"),
                PackageIntent(kind="transcript", required=False, status="available"),
            ]
        )
    else:
        reason = "no_audio_stream" if not has_audio else "missing_local_whisper"
        intents.extend(
            [
                PackageIntent(kind="captions", required=False, status="unavailable", reason=reason),
                PackageIntent(kind="transcript", required=False, status="unavailable", reason=reason),
            ]
        )
    return intents


def _partition_repairs(repairs: list[Repair]) -> dict[Disposition, list[Repair]]:
    return {disposition: [repair for repair in repairs if repair.disposition is disposition] for disposition in Disposition}


def _validate_policy_classification(plan: RescuePlan) -> None:
    expected = _partition_repairs(
        [evaluate_finding(finding, plan.capabilities) for finding in plan.findings]
    )
    actual = {
        Disposition.SAFE_REPAIR: plan.safe_repairs,
        Disposition.RECOMMENDATION: plan.recommendations,
        Disposition.UNAVAILABLE: plan.unavailable_repairs,
        Disposition.BLOCKED: plan.blocked_repairs,
    }
    for disposition in Disposition:
        expected_payload = [repair.model_dump(mode="json") for repair in expected[disposition]]
        actual_payload = [repair.model_dump(mode="json") for repair in actual[disposition]]
        if actual_payload != expected_payload:
            raise rescue_error(
                "rescue plan repair buckets do not match current policy classification",
                RESCUE_PLAN_MISMATCH,
            )


def _write_plan(plan: RescuePlan, plan_path: Path) -> None:
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def plan_rescue(
    source_path: str,
    output_dir: str,
    save_plan: str | None = None,
    policy_id: str = POLICY_ID,
) -> dict[str, Any]:
    """Create a deterministic policy-classified plan and optional JSON artifact."""

    source, output, workspace = _normalize_entry_paths(source_path, output_dir)
    plan_path = _normalize_save_plan(save_plan, output)
    if policy_id != POLICY_ID:
        raise rescue_error(f"unsupported rescue policy: {policy_id}", RESCUE_POLICY_VIOLATION)

    capabilities = snapshot_capabilities()
    analysis = analyze_source(str(source), workspace, output / "previews")
    repairs = [evaluate_finding(finding, capabilities) for finding in analysis.findings]
    buckets = _partition_repairs(repairs)
    artifact_base = plan_path.parent if plan_path is not None else output

    plan = RescuePlan(
        workspace_root=os.path.relpath(workspace, artifact_base),
        output_root=os.path.relpath(output, workspace),
        source=analysis.source,
        policy=RescuePolicy(id=POLICY_ID, version=POLICY_VERSION),
        findings=analysis.findings,
        safe_repairs=buckets[Disposition.SAFE_REPAIR],
        recommendations=buckets[Disposition.RECOMMENDATION],
        unavailable_repairs=buckets[Disposition.UNAVAILABLE],
        blocked_repairs=buckets[Disposition.BLOCKED],
        package_intents=_build_package_intents(analysis, capabilities),
        preview_artifacts=analysis.previews,
        estimate=analysis.estimate,
        capabilities=capabilities,
        versions=versions(),
        created_at=datetime.now(UTC),
        observed_planning_seconds=analysis.observed_planning_seconds,
        plan_sha256=None,
    )
    plan_hash = "sha256:" + hashlib.sha256(canonical_payload(plan)).hexdigest()
    plan = plan.model_copy(update={"plan_sha256": plan_hash})
    if plan_path is not None:
        _write_plan(plan, plan_path)
    return plan.model_dump(mode="json")


def _validate_plan_references(plan: RescuePlan, plan_path: Path) -> None:
    workspace = _realpath(plan_path.parent / plan.workspace_root)
    if workspace == Path(workspace.anchor) or not workspace.is_dir():
        raise rescue_error("plan workspace reference is invalid", INVALID_RESCUE_PLAN)
    source = _realpath(workspace / plan.source.path)
    output = _realpath(workspace / plan.output_root)
    if not source.is_file() or not output.is_dir():
        raise rescue_error("plan source or output reference is unavailable", INVALID_RESCUE_PLAN)
    if not _is_confined(source, workspace) or not _is_confined(output, workspace):
        raise rescue_error("plan references escape the workspace", INVALID_RESCUE_PLAN)
    if not _is_confined(plan_path, output):
        raise rescue_error("plan artifact must remain inside its declared output directory", INVALID_RESCUE_PLAN)


def read_plan(path: str | Path) -> RescuePlan:
    """Read, validate, and re-hash a persisted version 1 rescue plan."""

    plan_path = _realpath(path)
    if not plan_path.is_file():
        raise rescue_error("rescue plan is not a readable file", INVALID_RESCUE_PLAN)
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        plan = RescuePlan.model_validate(payload)
    except (OSError, json.JSONDecodeError, PydanticValidationError) as exc:
        raise rescue_error("rescue plan is malformed", INVALID_RESCUE_PLAN) from exc
    if plan.plan_sha256 is None:
        raise rescue_error("rescue plan has no canonical hash", INVALID_RESCUE_PLAN)
    expected = "sha256:" + hashlib.sha256(canonical_payload(plan)).hexdigest()
    if plan.plan_sha256 != expected:
        raise rescue_error("rescue plan hash does not match its action fields", RESCUE_PLAN_MISMATCH)
    _validate_policy_classification(plan)
    _validate_plan_references(plan, plan_path)
    return plan
