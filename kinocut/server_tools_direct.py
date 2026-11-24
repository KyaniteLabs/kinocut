"""Review spoken directions and explicitly apply a validated, closed edit plan."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .direct import executor
from .output_policy import read_only
from .server_app import _safe_tool, mcp


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
@_safe_tool
@read_only
def video_direct(
    input_path: str,
    direction: str | None = None,
    audio_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Turn the user's words verbatim into a reviewable edit plan. Never renders.

    Read assumptions back, ask the single question if present, then call
    video_direct_apply with confirm=true only after the user agrees. An optional
    voice memo is transcribed locally only when direction is empty.
    """
    return executor.review(input_path, direction, audio_path, output_path)


@mcp.tool()
@_safe_tool
def video_direct_apply(plan: dict, confirm: Annotated[bool, Field(strict=True)] = False) -> dict[str, Any]:
    """Validate a reviewed direct plan; render only with explicit confirm=true.

    Hand-edited tools, paths and arguments are checked before any execution.
    Stops at the first failure and reports receipts and artifacts already made.
    Intermediate video renders are removed after every planned step succeeds.
    """
    return executor.apply(plan, confirm)
