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
    subtitle_source: str | None = None,
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
    sources: list[dict[str, Any]] = [{"id": "hero", "path": source}]
    ops: list[dict[str, Any]] = []
    if duration is not None:
        ops.append({"op": "trim", "start": 0, "duration": duration})
    if aspect:
        height = 1920 if aspect == "9:16" else 1080
        width = 1080 if aspect == "9:16" else 1920
        if aspect == "1:1":
            width, height = 1080, 1080
        ops.append({"op": "resize", "width": width, "height": height})
    wants_captions = any(k in lower for k in ("caption", "subtitle", "srt"))
    warnings: list[str] = []
    requires_transcription = False
    if wants_captions:
        if subtitle_source and subtitle_source.strip():
            sources.append({"id": "subtitles", "path": subtitle_source.strip()})
            video_ref = f"step_{len(ops)}" if ops else "hero"
            ops.append({"op": "burn_in", "srcs": [video_ref, "subtitles"]})
        else:
            requires_transcription = True
            warnings.append(
                "Captions requested without a subtitle_source; transcribe with video_ai_transcribe "
                "and attach a burn_in op (or use video_direct) instead of placeholder text."
            )
    if not ops:
        ops.append({"op": "trim", "start": 0, "duration": duration or 15})
    cf = validate_cutfile(
        {
            "name": name or _slug(text),
            "version": 1,
            "sources": sources,
            "ops": ops,
        }
    )
    payload = cf.to_dict()
    payload["goal"] = text
    payload["next_action"] = "review_then_cutfile_render"
    if requires_transcription:
        payload["requires_transcription"] = True
        payload["warnings"] = warnings
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
