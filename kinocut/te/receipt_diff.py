"""Diff two workflow/session receipts (N3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kinocut.errors import InputFileError, MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path


def diff_receipts(left: str | dict[str, Any], right: str | dict[str, Any]) -> dict[str, Any]:
    """Compare two receipt objects or JSON paths. Does not render."""
    a = _load(left)
    b = _load(right)
    a_ops = _ops(a)
    b_ops = _ops(b)
    added = [op for op in b_ops if op not in a_ops]
    removed = [op for op in a_ops if op not in b_ops]
    replay = {
        "artifact_kind": "receipt_replay_plan",
        "ops": b_ops,
        "next_action": "compile_cutfile_or_workflow_from_ops",
        "dry_run": True,
    }
    return {
        "artifact_kind": "receipt_diff",
        "added": added,
        "removed": removed,
        "unchanged": [op for op in a_ops if op in b_ops],
        "left_kind": a.get("artifact_kind"),
        "right_kind": b.get("artifact_kind"),
        "replay": replay,
        "changed": bool(added or removed),
    }


def _load(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    path = Path(_validate_input_path(str(value)))
    if not path.is_file():
        raise InputFileError(str(path), "receipt not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPVideoError(f"invalid receipt json: {exc}", error_type="validation_error", code="bad_receipt") from exc
    if not isinstance(data, dict):
        raise MCPVideoError("receipt root must be an object", error_type="validation_error", code="bad_receipt")
    return data


def _ops(receipt: dict[str, Any]) -> list[str]:
    for key in ("ops", "tool_calls", "steps"):
        raw = receipt.get(key)
        if isinstance(raw, list) and raw:
            out: list[str] = []
            for item in raw:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    out.append(str(item.get("op") or item.get("tool") or item.get("action") or item.get("name") or item))
            return out
    if receipt.get("operation"):
        return [str(receipt["operation"])]
    return []
