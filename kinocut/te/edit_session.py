"""Conversational edit sessions with measured improvement (TE.13)."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import (
    _atomic_artifact,
    _validate_artifact_input_path,
    _validate_artifact_location,
    _validate_artifact_path,
)
from kinocut.output_policy import output_operation


def _write_json(path: Path, state: dict[str, Any], *, recorded: bool = False) -> None:
    target = _validate_artifact_path(str(path), allow_recorded=recorded)
    with _atomic_artifact(target, allow_recorded=recorded) as staged:
        Path(staged).write_text(json.dumps(state, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _load_open_session(path: Path) -> dict[str, Any]:
    _validate_artifact_location(str(path.parent), "Session directory")
    target = _validate_artifact_input_path(str(path))
    try:
        state = json.loads(Path(target).read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise MCPVideoError("Invalid session JSON", error_type="validation_error", code="invalid_session") from None
    if path.name != "session.json" or not isinstance(state, dict) or state.get("artifact_kind") != "edit_session":
        raise MCPVideoError("Invalid edit session", error_type="validation_error", code="invalid_session")
    if state.get("closed_at") is not None:
        raise MCPVideoError("session already closed", error_type="validation_error", code="session_closed")
    return state


def session_open(path: str, goal: str) -> dict[str, Any]:
    root = Path(path)
    _validate_artifact_location(str(root), "Session directory")
    state = {
        "artifact_kind": "edit_session",
        "goal": goal,
        "created_at": time.time(),
        "steps": [],
        "baseline_score": None,
        "current_score": None,
    }
    p = root / "session.json"
    _write_json(p, state)
    return {**state, "path": str(p.resolve())}


def session_step(
    session_path: str,
    *,
    action: str,
    score: float | None = None,
    notes: str = "",
    input_path: str | None = None,
) -> dict[str, Any]:
    p = Path(session_path)
    state = _load_open_session(p)
    if not action:
        raise MCPVideoError("action required", error_type="validation_error", code="action_required")
    measured = score
    if measured is None and input_path:
        measured = _qc_score(input_path)
        notes = notes or f"qc:{input_path}"
    if measured is not None and not math.isfinite(measured):
        raise MCPVideoError("Score must be finite", error_type="validation_error", code="invalid_score")
    step = {
        "index": len(state.get("steps") or []) + 1,
        "action": action,
        "score": measured,
        "notes": notes,
        "at": time.time(),
        "input_path": input_path,
    }
    state.setdefault("steps", []).append(step)
    if state.get("baseline_score") is None and measured is not None:
        state["baseline_score"] = measured
    if measured is not None:
        state["current_score"] = measured
    baseline = state.get("baseline_score")
    current = state.get("current_score")
    improvement = None
    if baseline is not None and current is not None:
        improvement = current - baseline
        if not math.isfinite(improvement):
            raise MCPVideoError("Improvement must be finite", error_type="validation_error", code="invalid_score")
    state["improvement"] = improvement
    with output_operation(overwrite=True):
        _write_json(p, state, recorded=True)
    return {**state, "path": str(p.resolve()), "measured_improvement": improvement}


def _qc_score(input_path: str) -> float:
    from kinocut.quality_guardrails import quality_check

    report = quality_check(input_path, fail_on_warning=False)
    return float(report.get("overall_score") or 0.0)


def session_close(session_path: str, *, write_receipt: bool = True) -> dict[str, Any]:
    """Close a conversational session and optionally write a durable receipt.

    Receipt is required for Track E conversational GO (measured improvement + receipt).
    """
    p = Path(session_path)
    state = _load_open_session(p)
    with output_operation(overwrite=True):
        _validate_artifact_path(str(p), allow_recorded=True)
    state["closed_at"] = time.time()
    baseline = state.get("baseline_score")
    current = state.get("current_score")
    improvement = None
    if baseline is not None and current is not None:
        improvement = float(current) - float(baseline)
    state["improvement"] = improvement
    state["measured_improvement"] = improvement
    receipt_path = None
    if write_receipt:
        receipts = p.parent / "receipts"
        _validate_artifact_location(str(receipts), "Receipts directory")
        receipt_path = receipts / "edit-session.receipt.json"
        receipt = {
            "artifact_kind": "edit_session_receipt",
            "session_path": str(p.resolve()),
            "goal": state.get("goal"),
            "step_count": len(state.get("steps") or []),
            "baseline_score": baseline,
            "current_score": current,
            "measured_improvement": improvement,
            "closed_at": state["closed_at"],
        }
        _write_json(receipt_path, receipt)
    with output_operation(overwrite=True):
        _write_json(p, state, recorded=True)
    return {
        **state,
        "path": str(p.resolve()),
        "measured_improvement": improvement,
        "receipt_path": str(receipt_path) if receipt_path else None,
    }
