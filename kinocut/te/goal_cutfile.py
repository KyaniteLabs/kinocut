"""Compile a natural-language goal into a reviewable Cutfile (N1)."""

from __future__ import annotations

import re
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.te.cutfile import validate_cutfile


def compile_goal_to_cutfile(
    goal: str,
    *,
    source: str = "media/hero.mp4",
    name: str | None = None,
) -> dict[str, Any]:
    """Turn a goal string into a schema-valid cutfile dict.

    Does not render. Agents and humans review ops before ``render_cutfile``.
    """
    text = (goal or "").strip()
    if not text:
        raise MCPVideoError("goal required", error_type="validation_error", code="goal_required")
    lower = text.lower()
    duration = _infer_duration(lower)
    aspect = _infer_aspect(lower)
    ops: list[dict[str, Any]] = []
    if duration is not None:
        ops.append({"op": "trim", "start": 0, "duration": duration})
    if aspect:
        height = 1920 if aspect == "9:16" else 1080
        width = 1080 if aspect == "9:16" else 1920
        if aspect == "1:1":
            width, height = 1080, 1080
        ops.append({"op": "resize", "width": width, "height": height})
    if any(k in lower for k in ("caption", "subtitle", "srt")):
        ops.append({"op": "add_text", "text": "CAPTIONS", "position": "bottom-center"})
    if not ops:
        ops.append({"op": "trim", "start": 0, "duration": duration or 15})
    cf = validate_cutfile(
        {
            "name": name or _slug(text),
            "version": 1,
            "sources": [{"id": "hero", "path": source}],
            "ops": ops,
        }
    )
    payload = cf.to_dict()
    payload["goal"] = text
    payload["next_action"] = "review_then_cutfile_render"
    return payload


def _infer_duration(lower: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b", lower)
    if m:
        return float(m.group(1))
    if "short" in lower or "reel" in lower or "tiktok" in lower:
        return 15.0
    return None


def _infer_aspect(lower: str) -> str | None:
    if "9:16" in lower or "vertical" in lower or "reel" in lower or "tiktok" in lower or "short" in lower:
        return "9:16"
    if "1:1" in lower or "square" in lower:
        return "1:1"
    if "16:9" in lower or "landscape" in lower or "widescreen" in lower:
        return "16:9"
    return None


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug or "goal")[:48]
