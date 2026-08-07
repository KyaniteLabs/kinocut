"""Audiogram plan — waveform visualization + chapters (TE.4)."""

from __future__ import annotations

from typing import Any
from collections.abc import Sequence

from kinocut.errors import MCPVideoError


def plan_audiogram(
    audio_path: str,
    *,
    width: int = 1080,
    height: int = 1080,
    chapter_marks: Sequence[float] | None = None,
) -> dict[str, Any]:
    if not audio_path:
        raise MCPVideoError("audio_path required", error_type="validation_error", code="audio_required")
    chapters = [float(x) for x in (chapter_marks or [])]
    return {
        "artifact_kind": "audiogram_plan",
        "audio_path": audio_path,
        "width": width,
        "height": height,
        "chapters": [{"time": t, "label": f"ch-{i+1}"} for i, t in enumerate(chapters)],
        "filter_hint": f"showwaves=s={width}x{height}:mode=cline",
        "notes": "Plan for showwaves/showfreqs render; pair with auto_chapters when available.",
    }
