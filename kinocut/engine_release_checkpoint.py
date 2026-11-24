"""Release-quality gate and human-review artifacts shared by local and MCP callers."""

from __future__ import annotations

import os
from collections.abc import Callable
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
    *,
    assert_quality_fn: Callable[..., dict[str, Any]] | None = None,
    thumbnail_fn: Callable[..., Any] | None = None,
    storyboard_fn: Callable[..., Any] | None = None,
    thumbnail_path_attr: str = "frame_path",
) -> dict[str, Any]:
    """Write review artifacts only after the hard quality gate passes."""
    if assert_quality_fn is None:
        from .quality_guardrails import assert_quality as assert_quality_fn
    if thumbnail_fn is None:
        from .engine_thumbnail import thumbnail as thumbnail_fn
    if storyboard_fn is None:
        from .engine_storyboard import storyboard as storyboard_fn

    report = assert_quality_fn(
        input_path, min_score=min_score, require_audio=require_audio, profile=profile, profile_reason=profile_reason
    )
    review_dir = output_dir or f"{os.path.splitext(input_path)[0]}_release_review"
    os.makedirs(review_dir, exist_ok=True)
    thumb = thumbnail_fn(input_path, output_path=os.path.join(review_dir, "thumbnail.jpg"))
    board = storyboard_fn(input_path, output_dir=os.path.join(review_dir, "storyboard"), frame_count=frame_count)
    fallback_attr = "output_path" if thumbnail_path_attr == "frame_path" else "frame_path"
    thumb_path = getattr(thumb, thumbnail_path_attr, None) or getattr(thumb, fallback_attr, None)
    return {
        "video": input_path,
        "quality": report,
        "quality_profile": profile,
        "thumbnail": thumb_path,
        "storyboard": board.model_dump() if hasattr(board, "model_dump") else board,
        "review_required": True,
        "instructions": "Open the thumbnail/storyboard and inspect the final video before publishing.",
    }
