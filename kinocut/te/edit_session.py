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
) -> dict[str, Any]:
    p = Path(session_path)
    if not p.is_file():
        raise InputFileError(str(p), "session.json not found")
    state = json.loads(p.read_text(encoding="utf-8"))
    if not action:
        raise MCPVideoError("action required", error_type="validation_error", code="action_required")
    step = {
        "index": len(state.get("steps") or []) + 1,
        "action": action,
        "score": score,
        "notes": notes,
        "at": time.time(),
    }
    state.setdefault("steps", []).append(step)
    if state.get("baseline_score") is None and score is not None:
        state["baseline_score"] = score
    if score is not None:
        state["current_score"] = score
    baseline = state.get("baseline_score")
    current = state.get("current_score")
    improvement = None
    if baseline is not None and current is not None:
        improvement = current - baseline
    state["improvement"] = improvement
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {**state, "path": str(p.resolve()), "measured_improvement": improvement}
