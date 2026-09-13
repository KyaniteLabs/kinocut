#!/usr/bin/env python3
"""Fail-closed first-run proof for the confidence baseline workflow."""

from __future__ import annotations

import importlib.metadata
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT, DEFAULT_QUALITY_GATE_SCORE
from kinocut.errors import MCPVideoError
from kinocut.source_identity import SourceIdentity, stream_source_identity

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "05-confidence-baseline" / "workflow.py"
OUTPUT = ROOT / "workflows" / "05-confidence-baseline" / "output"
ADVISORY_CHECKS = frozenset({"temporal_motion"})
MAX_DIAGNOSTIC_CHARS = 1000


class GoldenPathError(MCPVideoError):
    """One bounded, user-readable golden-path failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_type="validation_error", code="golden_path_failed")


def _bounded(value: object) -> str:
    return str(value or "")[-MAX_DIAGNOSTIC_CHARS:]


def _run(
    cmd: list[str], *, cwd: Path | None = None, timeout: float, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    print(f"\n$ {' '.join(cmd)}")
    try:
        return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        detail = _bounded(exc.stderr or exc.stdout)
        raise GoldenPathError(f"command timed out after {timeout:g}s: {cmd[0]}\n{detail}") from exc
    except OSError as exc:
        raise GoldenPathError(f"cannot start command {cmd[0]}: {_bounded(exc)}") from exc


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoldenPathError(f"invalid {path.name}: {_bounded(exc)}") from exc
    if not isinstance(value, dict):
        raise GoldenPathError(f"invalid {path.name}: expected JSON object")
    return value


def _validate_doctor(raw: str) -> dict[str, Any]:
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GoldenPathError(f"invalid doctor JSON: {_bounded(exc)}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("summary"), dict):
        raise GoldenPathError("invalid doctor JSON: missing summary object")
    if report["summary"].get("required_ok") is not True:
        raise GoldenPathError("doctor summary.required_ok must be literal true")
    return report


def _commit_identity() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GoldenPathError(f"candidate commit cannot be verified: {_bounded(exc)}") from exc
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise GoldenPathError("candidate commit must be a full lowercase Git SHA")
    configured = os.environ.get("GITHUB_SHA")
    if configured is not None and configured != commit:
        raise GoldenPathError("GITHUB_SHA does not match the checked-out candidate commit")
    return commit


def _finite_score(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoldenPathError(f"{label} score must be numeric")
    try:
        score = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise GoldenPathError(f"{label} score must be finite") from exc
    if not math.isfinite(score):
        raise GoldenPathError(f"{label} score must be finite")
    return score


def _validate_quality(quality: dict[str, Any]) -> None:
    if quality.get("all_passed") is not True:
        raise GoldenPathError("quality all_passed must be literal true")
    if _finite_score(quality.get("overall_score"), "quality") < DEFAULT_QUALITY_GATE_SCORE:
        raise GoldenPathError(f"quality score must be at least {DEFAULT_QUALITY_GATE_SCORE:g}")
    checks = quality.get("checks")
    if not isinstance(checks, list) or not checks:
        raise GoldenPathError("quality checks must be a non-empty list")
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            raise GoldenPathError("quality check entries must be named objects")
        if check["name"] not in ADVISORY_CHECKS and check.get("passed") is not True:
            raise GoldenPathError(f"non-advisory quality check failed: {check['name']}")


def _inside_output(value: object, output: Path, label: str, *, expected: Path | None = None) -> Path:
    if not isinstance(value, str) or not value:
        raise GoldenPathError(f"{label} path is missing")
    try:
        path = Path(value).resolve(strict=True)
        root = output.resolve(strict=True)
    except OSError as exc:
        raise GoldenPathError(f"{label} is missing: {_bounded(exc)}") from exc
    if not path.is_file() or (path != root and root not in path.parents):
        raise GoldenPathError(f"{label} must be a file inside output")
    if expected is not None and path != expected.resolve(strict=True):
        raise GoldenPathError(f"{label} does not match its expected output path")
    return path


def _source_identity(receipt: dict[str, Any]) -> tuple[Path, SourceIdentity]:
    source = receipt.get("source_media")
    if not isinstance(source, dict):
        raise GoldenPathError("source_media object is missing")
    value = source.get("path")
    claimed_hash = source.get("sha256")
    claimed_size = source.get("byte_size")
    if not isinstance(value, str) or not value:
        raise GoldenPathError("source path is missing")
    if not isinstance(claimed_hash, str) or isinstance(claimed_size, bool) or not isinstance(claimed_size, int):
        raise GoldenPathError("source identity is missing")
    return Path(value), SourceIdentity(claimed_hash, claimed_size)


def _require_identity(path: Path, expected: SourceIdentity, label: str) -> None:
    try:
        observed = stream_source_identity(str(path))
    except MCPVideoError as exc:
        raise GoldenPathError(f"{label} identity cannot be verified") from exc
    if observed != expected:
        raise GoldenPathError(f"{label} identity does not match the receipt")


def _validate_candidate(receipt: dict[str, Any], expected_commit: str) -> None:
    candidate = receipt.get("candidate")
    if not isinstance(candidate, dict):
        raise GoldenPathError("candidate identity is missing")
    installed_version = importlib.metadata.version("kinocut")
    if candidate.get("package") != "kinocut" or candidate.get("version") != installed_version:
        raise GoldenPathError("candidate package/version does not match the installed distribution")
    commit = candidate.get("commit")
    valid = isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) is not None
    if not valid or commit != expected_commit:
        raise GoldenPathError("candidate commit does not match the checked-out commit")


def _validate_final(receipt: dict[str, Any], output: Path) -> None:
    artifacts = receipt.get("review_artifacts")
    if not isinstance(artifacts, dict):
        raise GoldenPathError("review_artifacts object is missing")
    final = _inside_output(artifacts.get("final_video"), output, "final video", expected=output / "final_clip.mp4")
    claimed = artifacts.get("final_sha256")
    if not isinstance(claimed, str):
        raise GoldenPathError("final output identity is missing")
    observed = stream_source_identity(str(final))
    if observed.asset_id != claimed:
        raise GoldenPathError("final output identity does not match the receipt")


def _review_path(value: object, output: Path, label: str) -> Path:
    path = _inside_output(value, output, label)
    checkpoint_root = (output / "checkpoint").resolve(strict=True)
    if checkpoint_root not in path.parents:
        raise GoldenPathError(f"{label} must be inside the checkpoint directory")
    return path


def _validate_checkpoint(checkpoint: dict[str, Any], output: Path) -> None:
    quality = checkpoint.get("quality")
    if not isinstance(quality, dict):
        raise GoldenPathError("checkpoint quality object is missing")
    if _finite_score(quality.get("overall_score"), "checkpoint") < DEFAULT_QUALITY_GATE_SCORE:
        raise GoldenPathError(f"checkpoint score must be at least {DEFAULT_QUALITY_GATE_SCORE:g}")
    if checkpoint.get("review_required") is not True:
        raise GoldenPathError("checkpoint review_required must be literal true")
    _review_path(checkpoint.get("thumbnail"), output, "thumbnail")
    storyboard = checkpoint.get("storyboard")
    frames = storyboard.get("frames") if isinstance(storyboard, dict) else None
    if not isinstance(frames, list) or not frames:
        raise GoldenPathError("checkpoint storyboard frames are missing")
    for frame in frames:
        _review_path(frame, output, "storyboard frame")


def _validate_artifacts(
    output: Path, run_id: str, expected_commit: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    receipt = _json_object(output / "video_receipt.json")
    quality = _json_object(output / "quality.json")
    checkpoint = _json_object(output / "release_checkpoint.json")
    if receipt.get("run_id") != run_id:
        raise GoldenPathError("video receipt run_id does not match this run")
    if not isinstance(receipt.get("tool_calls"), list) or not receipt["tool_calls"]:
        raise GoldenPathError("video receipt has no tool_calls")
    _validate_candidate(receipt, expected_commit)
    source, claimed_source = _source_identity(receipt)
    source = _inside_output(source.as_posix(), output, "source", expected=output / "source.mp4")
    _require_identity(source, claimed_source, "source")
    review = receipt.get("human_review")
    if not isinstance(review, dict) or review.get("required") is not True or review.get("status") != "pending":
        raise GoldenPathError("human review must be required and pending")
    _validate_final(receipt, output)
    _validate_quality(quality)
    _validate_checkpoint(checkpoint, output)
    return receipt, quality, checkpoint


def _fail(message: str) -> int:
    print(f"FAIL: {_bounded(message)}", file=sys.stderr)
    return 1


def main() -> int:
    run_id = uuid.uuid4().hex
    try:
        commit = _commit_identity()
        doctor = _run(
            [sys.executable, "-m", "kinocut", "doctor", "--json"],
            timeout=min(60, DEFAULT_FFMPEG_TIMEOUT),
        )
        if doctor.returncode:
            raise GoldenPathError(f"kino doctor exited {doctor.returncode}: {_bounded(doctor.stderr or doctor.stdout)}")
        _validate_doctor(doctor.stdout)
        if not WORKFLOW.is_file():
            raise GoldenPathError(f"missing workflow script: {WORKFLOW}")
        if OUTPUT.exists():
            shutil.rmtree(OUTPUT)
        OUTPUT.mkdir(parents=True)
        env = os.environ.copy()
        env["KINOCUT_GOLDEN_RUN_ID"] = run_id
        workflow = _run([sys.executable, str(WORKFLOW)], cwd=WORKFLOW.parent, timeout=DEFAULT_FFMPEG_TIMEOUT, env=env)
        if workflow.returncode:
            raise GoldenPathError(
                f"confidence baseline exited {workflow.returncode}: {_bounded(workflow.stderr or workflow.stdout)}"
            )
        _validate_artifacts(OUTPUT, run_id, commit)
    except GoldenPathError as exc:
        return _fail(str(exc))
    print("GOLDEN PATH GREEN")
    print(f"run_id={run_id}")
    print("Human visual/audio review remains required and pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
