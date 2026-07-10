"""Render, verify, and atomically promote policy-approved rescue packages."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..errors import MCPVideoError
from ..workflow._versions import versions
from ..ai_engine.transcribe import ai_transcribe
from ._errors import (
    RESCUE_APPROVAL_INVALID,
    RESCUE_CANCELLED,
    RESCUE_DEPENDENCY_MISMATCH,
    RESCUE_INTERMEDIATE_MISMATCH,
    RESCUE_SOURCE_MISMATCH,
    RESCUE_VERIFICATION_FAILED,
    UNSAFE_RESCUE_OUTPUT,
    rescue_error,
)
from .models import (
    CleanupState,
    OperationEntry,
    PackageArtifact,
    PackageManifest,
    RescuePlan,
    RescueReceipt,
    ResumeState,
    VerificationCheck,
    canonical_payload,
    receipt_integrity_sha256,
)
from .capabilities import snapshot_capabilities, whisper_model_path
from .operations import OperationResult, execute_repair, make_master, make_universal_copy
from .planner import read_plan
from .verifier import verify_package

logger = logging.getLogger(__name__)


class RescueCancellation(Exception):
    """Internal cooperative-cancellation signal."""


def _sha(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _confined(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _relative(path: str | Path, root: Path) -> str:
    return Path(path).resolve().relative_to(root).as_posix()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _entry(result: OperationResult, input_path: Path, workspace_root: Path, executor: str) -> OperationEntry:
    return OperationEntry(
        id=f"{result.operation}:{result.repair_id or 'package'}",
        repair_id=result.repair_id,
        status="completed",
        input_path=_relative(input_path, workspace_root),
        input_sha256=_sha(input_path),
        output_path=_relative(result.output_path, workspace_root),
        output_sha256=result.sha256,
        executor=executor,
        executor_version=versions().get("ffmpeg"),
        elapsed_ms=result.elapsed_ms,
    )


def _resolve_plan_paths(plan_path: Path, plan: RescuePlan) -> tuple[Path, Path, Path]:
    workspace = (plan_path.parent / plan.workspace_root).resolve()
    output = (workspace / plan.output_root).resolve()
    source = (workspace / plan.source.path).resolve()
    if not workspace.is_dir() or not output.is_dir() or not source.is_file():
        raise rescue_error("rescue plan paths are unavailable", UNSAFE_RESCUE_OUTPUT)
    if not _confined(source, workspace) or not _confined(output, workspace) or not _confined(plan_path, output):
        raise rescue_error("rescue plan paths escaped their workspace", UNSAFE_RESCUE_OUTPUT)
    return workspace, output, source


def _validate_receipt_path(path: str | None, output: Path) -> Path | None:
    if path is None:
        return None
    resolved = Path(os.path.realpath(path))
    if resolved.suffix.lower() != ".json" or not _confined(resolved, output):
        raise rescue_error("save_receipt must be a JSON file inside output_root", UNSAFE_RESCUE_OUTPUT)
    return resolved


def _check_cancel(cancel_file: Path | None) -> None:
    if cancel_file is not None and cancel_file.exists():
        raise RescueCancellation


def _policy_hash(plan: RescuePlan) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(plan.policy, excluded=frozenset())).hexdigest()


def _run_local_transcript(
    master: Path,
    package_dir: Path,
    workspace: Path,
    capabilities: dict[str, Any],
) -> tuple[Path, Path, OperationEntry]:
    try:
        whisper = importlib.import_module("whisper")
    except ImportError as exc:
        raise MCPVideoError(
            "planned Whisper executor is no longer installed",
            error_type="dependency_error",
            code="missing_whisper",
        ) from exc
    model_path = whisper_model_path("base")
    model_url = getattr(whisper, "_MODELS", {}).get("base")
    expected = model_url.rstrip("/").split("/")[-2] if isinstance(model_url, str) else None
    model_sha256 = _sha(model_path) if model_path.is_file() else None
    actual = model_sha256.removeprefix("sha256:") if model_sha256 else None
    planned_model = capabilities.get("whisper_models", {}).get("base", {}).get("sha256")
    if not expected or actual != expected or model_sha256 != planned_model:
        raise rescue_error("cached Whisper base model failed integrity validation", RESCUE_DEPENDENCY_MISMATCH)
    if model_sha256 is None:
        raise rescue_error("cached Whisper base model failed integrity validation", RESCUE_DEPENDENCY_MISMATCH)

    captions = package_dir / "captions.srt"
    transcript = package_dir / "transcript.txt"
    started = time.monotonic()
    result = ai_transcribe(str(master), output_srt=str(captions), model="base")
    transcript.write_text(str(result.get("transcript", "")).strip() + "\n", encoding="utf-8")
    parameters: dict[str, int | float | str | bool] = {
        "transcript_path": _relative(transcript, workspace),
        "model": "base",
        "model_sha256": model_sha256,
    }
    if isinstance(result.get("language"), str):
        parameters["language"] = result["language"]
    entry = OperationEntry(
        id="captions_transcript:package",
        status="completed",
        input_path=_relative(master, workspace),
        input_sha256=_sha(master),
        output_path=_relative(captions, workspace),
        output_sha256=_sha(captions),
        parameters=parameters,
        executor="openai-whisper",
        executor_version=capabilities.get("whisper", {}).get("version"),
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    return captions, transcript, entry


def _base_receipt(
    plan: RescuePlan,
    status: Literal["completed", "failed", "cancelled", "quarantined"],
    approved: list[str],
    operations: list[OperationEntry],
    verification: list,
    package: PackageManifest,
    workspace: Path,
    output: Path,
    job_dir: Path,
    *,
    resume_used: bool = False,
    resume_receipt_path: str | None = None,
    error: dict[str, Any] | None = None,
) -> RescueReceipt:
    applied = [entry.repair_id for entry in operations if entry.repair_id]
    return RescueReceipt(
        status=status,
        workspace_root=os.path.relpath(workspace, output),
        output_root=".",
        source=plan.source,
        plan_sha256=plan.plan_sha256 or "sha256:" + "0" * 64,
        policy=plan.policy,
        policy_sha256=_policy_hash(plan),
        approved_repair_ids=approved,
        applied_repair_ids=applied,
        skipped_repair_ids=[repair.id for repair in plan.safe_repairs if repair.id not in approved],
        unavailable_repair_ids=[repair.id for repair in plan.unavailable_repairs],
        blocked_repair_ids=[repair.id for repair in plan.blocked_repairs],
        operations=operations,
        verification=verification,
        package=package,
        progress={"completed_stages": len(operations)},
        cleanup=CleanupState(
            work_dir=_relative(job_dir, output),
            intermediates=[
                entry.output_path
                for entry in operations
                if entry.repair_id and entry.output_path is not None
            ],
            cleaned=[],
        ),
        resume=ResumeState(used=resume_used, receipt_path=resume_receipt_path, resumed_from=resume_receipt_path),
        versions=versions(),
        created_at=datetime.now(UTC),
        error=error,
    )


def _write_receipt(receipt: RescueReceipt, path: Path) -> None:
    _atomic_json(path, receipt.model_dump(mode="json"))


def _remap_operations(
    operations: list[OperationEntry],
    old_root: Path,
    new_root: Path,
    workspace: Path,
) -> list[OperationEntry]:
    remapped: list[OperationEntry] = []
    for entry in operations:
        updates: dict[str, str] = {}
        for field in ("input_path", "output_path"):
            value = getattr(entry, field)
            if value is None:
                continue
            absolute = (workspace / value).resolve()
            if _confined(absolute, old_root):
                updates[field] = (new_root / absolute.relative_to(old_root)).relative_to(workspace).as_posix()
        remapped.append(entry.model_copy(update=updates))
    return remapped


def _load_resume(
    receipt_path: str,
    plan: RescuePlan,
    workspace: Path,
    output: Path,
    current_versions: dict[str, str | None],
) -> tuple[Path, list[str], list[OperationEntry], dict[str, Path]]:
    path = Path(os.path.realpath(receipt_path))
    if not path.is_file() or not _confined(path, output):
        raise rescue_error("resume receipt must be a file inside output_root", RESCUE_INTERMEDIATE_MISMATCH)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise rescue_error("resume receipt is not readable JSON", RESCUE_INTERMEDIATE_MISMATCH) from exc
    if (
        payload.get("receipt_kind") != "rescue"
        or payload.get("status") not in {"cancelled", "failed"}
        or payload.get("plan_sha256") != plan.plan_sha256
        or payload.get("source", {}).get("sha256") != plan.source.sha256
        or payload.get("policy") != plan.policy.model_dump(mode="json")
        or payload.get("versions") != current_versions
    ):
        raise rescue_error("resume receipt does not match this plan and runtime", RESCUE_INTERMEDIATE_MISMATCH)

    approved = payload.get("approved_repair_ids")
    if not isinstance(approved, list) or any(not isinstance(value, str) for value in approved):
        raise rescue_error("resume approval set is invalid", RESCUE_INTERMEDIATE_MISMATCH)
    work_ref = payload.get("cleanup", {}).get("work_dir")
    if not isinstance(work_ref, str):
        raise rescue_error("resume receipt has no retained work directory", RESCUE_INTERMEDIATE_MISMATCH)
    job_dir = (output / work_ref).resolve()
    work_root = (output / ".rescue-work").resolve()
    if not job_dir.is_dir() or not _confined(job_dir, work_root):
        raise rescue_error("retained resume job escaped .rescue-work", RESCUE_INTERMEDIATE_MISMATCH)

    operations: list[OperationEntry] = []
    repair_outputs: dict[str, Path] = {}
    try:
        for raw in payload.get("operations", []):
            entry = OperationEntry.model_validate(raw)
            if entry.status != "completed" or entry.output_path is None or entry.output_sha256 is None:
                raise ValueError("incomplete operation")
            artifact = (workspace / entry.output_path).resolve()
            if not artifact.is_file() or not _confined(artifact, job_dir) or _sha(artifact) != entry.output_sha256:
                raise ValueError("intermediate hash mismatch")
            operations.append(entry)
            if entry.repair_id:
                repair_outputs[entry.repair_id] = artifact
    except (ValueError, TypeError) as exc:
        raise rescue_error("retained intermediate failed integrity validation", RESCUE_INTERMEDIATE_MISMATCH) from exc

    completed_repairs = [entry.repair_id for entry in operations if entry.repair_id]
    planned_prefix = [repair.id for repair in plan.safe_repairs if repair.id in approved][: len(completed_repairs)]
    if completed_repairs != planned_prefix:
        raise rescue_error("resume stages are not a valid completed plan prefix", RESCUE_INTERMEDIATE_MISMATCH)
    return job_dir, approved, operations, repair_outputs


def render_rescue(
    plan_path: str,
    approved_repair_ids: Sequence[str] | None = None,
    save_receipt: str | None = None,
    resume_receipt: str | None = None,
    cancel_file: str | None = None,
    keep_intermediates: bool = False,
) -> dict[str, Any]:
    """Render one immutable plan and promote only independently verified artifacts."""

    persisted_plan = Path(os.path.realpath(plan_path))
    plan = read_plan(persisted_plan)
    workspace, output, source = _resolve_plan_paths(persisted_plan, plan)
    receipt_copy = _validate_receipt_path(save_receipt, output)
    if _sha(source) != plan.source.sha256:
        raise rescue_error("source hash changed after planning", RESCUE_SOURCE_MISMATCH)
    current_versions = versions()
    if any(plan.versions.get(key) != current_versions.get(key) for key in ("mcp_video", "ffmpeg")):
        raise rescue_error("local executor versions differ from the plan", RESCUE_DEPENDENCY_MISMATCH)
    current_capabilities = snapshot_capabilities()
    for key in ("ffmpeg", "whisper", "whisper_models", "filters"):
        if plan.capabilities.get(key) != current_capabilities.get(key):
            raise rescue_error("local rescue capabilities differ from the plan", RESCUE_DEPENDENCY_MISMATCH)

    safe = {repair.id: repair for repair in plan.safe_repairs}
    requested = None if approved_repair_ids is None else list(approved_repair_ids)
    approved = list(safe) if requested is None else requested
    if len(approved) != len(set(approved)) or any(repair_id not in safe for repair_id in approved):
        raise rescue_error("approved ids must be unique safe repairs from this plan", RESCUE_APPROVAL_INVALID)

    plan_prefix = (plan.plan_sha256 or "sha256:unknown").removeprefix("sha256:")[:12]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-._") or "video"
    final_name = f"{stem}-rescue-{plan_prefix}"
    final_dir = output / final_name
    if final_dir.exists():
        raise rescue_error("final rescue package already exists", UNSAFE_RESCUE_OUTPUT)
    prior_operations: list[OperationEntry] = []
    repair_outputs: dict[str, Path] = {}
    if resume_receipt is not None:
        job_dir, prior_approved, prior_operations, repair_outputs = _load_resume(
            resume_receipt, plan, workspace, output, current_versions
        )
        if requested is not None and requested != prior_approved:
            raise rescue_error("resume approval set changed", RESCUE_INTERMEDIATE_MISMATCH)
        approved = prior_approved
        run_id = job_dir.name.rsplit("-", 1)[-1]
    else:
        run_id = uuid.uuid4().hex[:12]
        job_dir = output / ".rescue-work" / f"{plan_prefix}-{run_id}"
    intermediates = job_dir / "intermediates"
    package_dir = job_dir / "package"
    intermediates.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(exist_ok=True)
    state_path = job_dir / "state.json"
    cancel = Path(os.path.realpath(cancel_file)) if cancel_file else None
    operations: list[OperationEntry] = list(prior_operations)

    def persist() -> None:
        _atomic_json(state_path, {"plan_sha256": plan.plan_sha256, "approved_repair_ids": approved, "operations": [entry.model_dump(mode="json") for entry in operations]})

    try:
        _check_cancel(cancel)
        current = source
        approved_outputs: list[str] = []
        for index, repair in enumerate(plan.safe_repairs):
            if repair.id not in approved:
                continue
            if repair.id in repair_outputs:
                current = repair_outputs[repair.id]
                approved_outputs.append(str(current))
                continue
            _check_cancel(cancel)
            target = intermediates / f"{index:03d}-{repair.type.value}{source.suffix or '.mp4'}"
            result = execute_repair(repair, str(current), str(target))
            operations.append(_entry(result, current, workspace, repair.executor or "unknown"))
            approved_outputs.append(str(target))
            current = target
            persist()
            _check_cancel(cancel)

        master = package_dir / f"{stem}-master{source.suffix or '.mp4'}"
        result = make_master(str(source), approved_outputs, str(master))
        operations.append(_entry(result, current, workspace, "python.copy2"))
        persist()
        _check_cancel(cancel)

        sharing = package_dir / f"{stem}-sharing.mp4"
        def progress_cancel(_: float) -> None:
            _check_cancel(cancel)

        result = make_universal_copy(str(master), str(sharing), progress_cancel)
        operations.append(_entry(result, master, workspace, "ffmpeg.convert"))
        persist()
        _check_cancel(cancel)

        captions: Path | None = None
        transcript: Path | None = None
        captions_unavailable_reason: str | None = None
        caption_failure: VerificationCheck | None = None
        captions_intent = next((intent for intent in plan.package_intents if intent.kind == "captions"), None)
        if captions_intent is not None and captions_intent.status == "available":
            try:
                captions, transcript, transcript_entry = _run_local_transcript(
                    master, package_dir, workspace, current_capabilities
                )
                operations.append(transcript_entry)
                persist()
                _check_cancel(cancel)
            except MCPVideoError as exc:
                if exc.code == "missing_whisper":
                    captions_unavailable_reason = "missing_whisper"
                else:
                    caption_failure = VerificationCheck(
                        id="caption_generation",
                        passed=False,
                        message="Local caption generation failed.",
                        details={"error_code": exc.code},
                    )
            except Exception as exc:
                logger.warning(
                    "Local caption generation failed with %s; the package will be quarantined.",
                    type(exc).__name__,
                )
                caption_failure = VerificationCheck(
                    id="caption_generation",
                    passed=False,
                    message="Local caption generation failed.",
                    details={
                        "error_code": "caption_generation_failed",
                        "exception_type": type(exc).__name__,
                    },
                )
        elif captions_intent is not None:
            captions_unavailable_reason = captions_intent.reason

        checks = verify_package(
            str(source),
            str(master),
            str(sharing),
            str(captions) if captions else None,
            str(transcript) if transcript else None,
        )
        if caption_failure is not None:
            checks.append(caption_failure)
        failed = [check for check in checks if check.gating and not check.passed]
        artifacts = [
            PackageArtifact(kind="master", status="available", path=master.name, sha256=_sha(master), size_bytes=master.stat().st_size),
            PackageArtifact(kind="sharing_copy", status="available", path=sharing.name, sha256=_sha(sharing), size_bytes=sharing.stat().st_size),
        ]
        if captions is not None and transcript is not None:
            artifacts.extend(
                [
                    PackageArtifact(kind="captions", status="available", path=captions.name, sha256=_sha(captions), size_bytes=captions.stat().st_size),
                    PackageArtifact(kind="transcript", status="available", path=transcript.name, sha256=_sha(transcript), size_bytes=transcript.stat().st_size),
                ]
            )
        else:
            reason = captions_unavailable_reason or "caption_sidecars_unavailable"
            artifacts.extend(
                [
                    PackageArtifact(kind="captions", status="unavailable", reason=reason),
                    PackageArtifact(kind="transcript", status="unavailable", reason=reason),
                ]
            )
        if failed:
            quarantine = output / ".rescue-quarantine" / run_id
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            os.replace(job_dir, quarantine)
            quarantined_operations = _remap_operations(operations, job_dir, quarantine, workspace)
            resume_ref = _relative(resume_receipt, output) if resume_receipt else None
            receipt = _base_receipt(plan, "quarantined", approved, quarantined_operations, checks, PackageManifest(path=None, promoted=False, artifacts=[], quarantine_path=_relative(quarantine, output)), workspace, output, quarantine, resume_used=resume_receipt is not None, resume_receipt_path=resume_ref, error={"code": RESCUE_VERIFICATION_FAILED})
            _write_receipt(receipt, quarantine / "rescue-receipt.json")
            if receipt_copy:
                _write_receipt(receipt, receipt_copy)
            raise rescue_error("rescue verification failed; package quarantined", RESCUE_VERIFICATION_FAILED)
        promoted_operations = _remap_operations(operations, package_dir, final_dir, workspace)
        resume_ref = _relative(resume_receipt, output) if resume_receipt else None
        receipt_ref = f"{final_name}/rescue-receipt.json"
        placeholder_hash = "sha256:" + "0" * 64
        artifacts.append(
            PackageArtifact(
                kind="receipt",
                status="available",
                path="rescue-receipt.json",
                sha256=placeholder_hash,
            )
        )
        receipt = _base_receipt(plan, "completed", approved, promoted_operations, checks, PackageManifest(path=final_name, promoted=True, artifacts=artifacts), workspace, output, job_dir, resume_used=resume_receipt is not None, resume_receipt_path=resume_ref)
        receipt = receipt.model_copy(
            update={"receipt_path": receipt_ref, "receipt_sha256": placeholder_hash}
        )
        receipt_hash = receipt_integrity_sha256(receipt)
        finalized_artifacts = [
            artifact.model_copy(update={"sha256": receipt_hash})
            if artifact.kind == "receipt"
            else artifact
            for artifact in receipt.package.artifacts
        ]
        receipt = receipt.model_copy(
            update={
                "receipt_sha256": receipt_hash,
                "package": receipt.package.model_copy(update={"artifacts": finalized_artifacts}),
            }
        )
        packaged_receipt = package_dir / "rescue-receipt.json"
        _write_receipt(receipt, packaged_receipt)
        os.replace(package_dir, final_dir)
        if receipt_copy:
            _write_receipt(receipt, receipt_copy)
        if not keep_intermediates:
            shutil.rmtree(job_dir, ignore_errors=True)
        return receipt.model_dump(mode="json")
    except RescueCancellation as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        operations = [entry for entry in operations if entry.repair_id]
        resume_ref = _relative(resume_receipt, output) if resume_receipt else None
        receipt = _base_receipt(plan, "cancelled", approved, operations, [], PackageManifest(path=None, promoted=False, artifacts=[]), workspace, output, job_dir, resume_used=resume_receipt is not None, resume_receipt_path=resume_ref, error={"code": RESCUE_CANCELLED})
        persist()
        if receipt_copy:
            _write_receipt(receipt, receipt_copy)
        raise rescue_error("rescue cancelled; no package was promoted", RESCUE_CANCELLED) from exc
