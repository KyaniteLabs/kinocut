"""Conversational edit sessions with measured improvement (TE.13)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from kinocut.errors import InputFileError, MCPVideoError


def session_open(path: str, goal: str) -> dict[str, Any]:
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    state = {
        "artifact_kind": "edit_session",
        "goal": goal,
        "created_at": time.time(),
        "steps": [],
        "baseline_score": None,
        "current_score": None,
    }
    p = root / "session.json"
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
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
    if not p.is_file():
        raise InputFileError(str(p), "session.json not found")
    state = json.loads(p.read_text(encoding="utf-8"))
    if not action:
        raise MCPVideoError("action required", error_type="validation_error", code="action_required")
    measured = score
    if measured is None and input_path:
        measured = _qc_score(input_path)
        notes = notes or f"qc:{input_path}"
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
    state["improvement"] = improvement
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
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
    if not p.is_file():
        raise InputFileError(str(p), "session.json not found")
    state = json.loads(p.read_text(encoding="utf-8"))
    if state.get("closed_at"):
        raise MCPVideoError("session already closed", error_type="validation_error", code="session_closed")
    state["closed_at"] = time.time()
    baseline = state.get("baseline_score")
    current = state.get("current_score")
    improvement = None
    if baseline is not None and current is not None:
        improvement = float(current) - float(baseline)
    state["improvement"] = improvement
    state["measured_improvement"] = improvement
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    receipt_path = None
    if write_receipt:
        receipts = p.parent / "receipts"
        receipts.mkdir(parents=True, exist_ok=True)
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
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return {
        **state,
        "path": str(p.resolve()),
        "measured_improvement": improvement,
        "receipt_path": str(receipt_path) if receipt_path else None,
    }
