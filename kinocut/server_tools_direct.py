"""Review spoken directions and explicitly apply a validated, closed edit plan."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .direct import parse_direction, plan_direction
from .direct_validation import clean_path, invalid, validate_args, validate_plan
from .engine import probe
from .ffmpeg_helpers import _atomic_artifact, _validate_input_path, _validate_output_path
from .output_policy import read_only
from .server_app import _error_result, _safe_tool, mcp


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
    input_path = _validate_input_path(input_path)
    if audio_path is not None:
        audio_path = _validate_input_path(audio_path)
    output = output_path or str(Path(input_path).with_name(f"{Path(input_path).stem}_direct.mp4"))
    clean_path(output)
    _validate_output_path(output)
    if Path(output).resolve() == Path(input_path).resolve():
        invalid("Direct output must not replace the source.")
    response = {"success": True}
    if (not direction or not direction.strip()) and audio_path:
        from .ai_engine import ai_transcribe

        result = ai_transcribe(audio_path)
        if result.get("success") is False:
            return result
        direction = result.get("transcript", "")
        response["transcript"] = direction
    info = probe(input_path)
    metadata = info.model_dump() if hasattr(info, "model_dump") else dict(info)
    for key in ("display_width", "display_height"):
        if hasattr(info, key):
            metadata[key] = getattr(info, key)
    parsed = replace(parse_direction(direction or ""), input_path=input_path, output_path=output)
    if output_path is None:
        parsed.assumptions.append("The default output is a new clip named with _direct beside the source.")
    plan = plan_direction(parsed, metadata).to_dict()
    plan_id = hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode()).hexdigest()
    response.update(plan=plan, assumptions=plan["assumptions"], question=plan["question"], plan_id=plan_id)
    return response


def _run_step(tool: str, args: dict) -> dict:
    """Dispatch only to the existing Python handlers; no evaluation or shell text."""
    if tool == "video_ai_transcribe":
        from .ai_engine import ai_transcribe
        from .ai_engine.transcribe import _format_srt

        # Keep sidecar publication under the same artifact guard as other plans.
        result = ai_transcribe(args["input_path"], model=args["model"])
        if result.get("success") is False:
            return result
        if result.get("transcript", "").strip() and result.get("segments"):
            with _atomic_artifact(args["output_srt"]) as staged:
                Path(staged).write_text(_format_srt(result["segments"]), encoding="utf-8")
            return {"success": True, **result, "output_srt": args["output_srt"]}
        return {"success": True, **result, "no_speech": True}
    from . import server_tools_advanced as advanced
    from . import server_tools_ai as ai
    from . import server_tools_basic as basic
    from . import server_tools_media as media

    handlers = {
        "video_trim": basic.video_trim,
        "video_ai_remove_silence": ai.video_ai_remove_silence,
        "video_speed": basic.video_speed,
        "video_crop": media.video_crop,
        "video_resize": basic.video_resize,
        "video_normalize_audio": advanced.video_normalize_audio,
        "video_subtitles": media.video_subtitles,
        "video_thumbnail": media.video_thumbnail,
        "video_add_audio": basic.video_add_audio,
    }
    handler = handlers[tool]
    if "review" in inspect.signature(handler).parameters:
        # Intermediate steps are internal; the user reviews the direct plan.
        args = {**args, "review": False}
    result = handler(**args)
    if inspect.isawaitable(result):
        # 2.x renders some edits as async tools. This tool may be called from
        # inside the MCP event loop, so finish the coroutine on its own loop.
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(asyncio.run, result).result()
    return result


@mcp.tool()
@_safe_tool
def video_direct_apply(plan: dict, confirm: Annotated[bool, Field(strict=True)] = False) -> dict[str, Any]:
    """Validate a reviewed direct plan; render only with explicit confirm=true.

    Hand-edited tools, paths and arguments are checked before any execution.
    Stops at the first failure and reports receipts and artifacts already made.
    """
    if type(confirm) is not bool:
        invalid("confirm must be an explicit boolean.")
    plan = validate_plan(copy.deepcopy(plan))
    if not confirm:
        return {
            "success": True,
            "dry_run": True,
            "step_count": len(plan["steps"]),
            "steps": plan["steps"],
            "assumptions": plan.get("assumptions", []),
            "question": plan.get("question"),
            "output_path": plan["output_path"],
            "receipts": [],
        }
    current = plan["input_path"]
    receipts, produced = [], []
    no_speech = False
    for index, step in enumerate(plan["steps"], 1):
        tool = step["tool"]
        args = dict(step["args"])
        if tool == "video_add_audio":
            args.update(video_path=current, audio_path=current)
        else:
            args["input_path"] = current
        if tool == "video_subtitles" and no_speech:
            receipts.append({"step": index, "tool": tool, "success": True, "skipped": "No speech was transcribed."})
            continue
        try:
            validate_args(tool, args)
            _validate_input_path(clean_path(current))
            if tool == "video_subtitles":
                _validate_input_path(clean_path(args["subtitle_path"]))
            if tool != "video_ai_transcribe":
                _validate_output_path(clean_path(args["output_path"]))
            if tool == "video_trim" and "duration" in args:
                # Cleanup has unknown length until rendered. Never overrun it.
                info = probe(current)
                duration = info["duration"] if isinstance(info, dict) else info.duration
                available = duration - args["start"]
                if available <= 0:
                    invalid("Trim begins after the available video.")
                args["duration"] = min(args["duration"], available)
            result = _run_step(tool, args)
        except Exception as exc:
            result = _error_result(exc)
        artifact = args.get("output_srt") if tool == "video_ai_transcribe" else args["output_path"]
        if artifact and Path(artifact).is_file():
            produced.append(artifact)
        elif result.get("success") and not result.get("no_speech"):
            result = {
                "success": False,
                "error": {
                    "type": "processing_error",
                    "code": "missing_direct_output",
                    "message": "The step returned without producing its planned artifact.",
                },
            }
        receipt = {"step": index, "tool": tool, "args": args, "success": result.get("success", False), "result": result}
        receipts.append(receipt)
        if not result.get("success"):
            return {
                "success": False,
                "failed_step": index,
                "failed_tool": tool,
                "error": result.get("error"),
                "receipts": receipts,
                "produced": produced,
                "output_path": current,
            }
        if tool == "video_ai_transcribe":
            no_speech = result.get("no_speech", False)
        elif tool != "video_thumbnail":
            current = args["output_path"]
    return {"success": True, "dry_run": False, "receipts": receipts, "produced": produced, "output_path": current}
