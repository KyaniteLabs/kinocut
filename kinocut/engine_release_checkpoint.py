"""Release-quality gate and human-review artifacts shared by local and MCP callers."""

from __future__ import annotations

import os
from typing import Any

from .defaults import DEFAULT_QUALITY_GATE_SCORE


def release_checkpoint(
    input_path: str,
    output_dir: str | None = None,
    min_score: float = DEFAULT_QUALITY_GATE_SCORE,
    frame_count: int = 6,
    require_audio: bool = True,
    profile: str = "default",
    profile_reason: str | None = None,
) -> dict[str, Any]:
    """Write review artifacts only after the hard quality gate passes."""
    from .quality_guardrails import assert_quality
    from .engine_thumbnail import thumbnail
    from .engine_storyboard import storyboard

    report = assert_quality(
        input_path, min_score=min_score, require_audio=require_audio, profile=profile, profile_reason=profile_reason
    )
    review_dir = output_dir or f"{os.path.splitext(input_path)[0]}_release_review"
    os.makedirs(review_dir, exist_ok=True)
    thumb = thumbnail(input_path, output_path=os.path.join(review_dir, "thumbnail.jpg"))
    board = storyboard(input_path, output_dir=os.path.join(review_dir, "storyboard"), frame_count=frame_count)
    return {
        "video": input_path,
        "quality": report,
        "quality_profile": profile,
        "thumbnail": thumb.frame_path,
        "storyboard": board.model_dump(),
        "review_required": True,
        "instructions": "Open the thumbnail/storyboard and inspect the final video before publishing.",
    }
