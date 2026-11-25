"""Review and execute the closed set of spoken-direction edits."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import engine
from ..direct_validation import clean_path, invalid, validate_args, validate_plan
from ..engine_probe import probe
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _atomic_artifact, _atomic_output, _validate_input_path, _validate_output_path
from ..operation_results import _error_result, _result
from ..output_policy import output_operation
from ..publication import open_staged_writer
from . import parse_direction, plan_direction


def review(
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
    if output_path is None:
        source = Path(input_path)
        output = str(source.with_name(f"{source.stem}_direct.mp4"))
        suffix = 2
        while Path(output).exists() or Path(output).is_symlink():
            output = str(source.with_name(f"{source.stem}_direct-{suffix}.mp4"))
            suffix += 1
    else:
        output = output_path
    clean_path(output)
    # Planning never writes, so checking an existing media target here should
    # not force the caller to supply apply-time overwrite consent prematurely.
    with output_operation(True):
        _validate_output_path(output)
    if Path(output).resolve() == Path(input_path).resolve():
        invalid("Direct output must not replace the source.")
    response = {"success": True}
    if (not direction or not direction.strip()) and audio_path:
        from ..ai_engine import ai_transcribe

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
        parsed.assumptions.append(
            "The default output is a new clip named with _direct beside the source, numbered if needed."
        )
    elif Path(output).exists():
        parsed.assumptions.append("The output already exists; applying this plan requires explicit overwrite consent.")
    plan = plan_direction(parsed, metadata).to_dict()
    plan_id = hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode()).hexdigest()
    response.update(plan=plan, assumptions=plan["assumptions"], question=plan["question"], plan_id=plan_id)
    return response


def _run_step(tool: str, args: dict) -> dict:
    """Dispatch only to the media engines; no evaluation or shell text."""
    if tool == "video_ai_transcribe":
        from ..ai_engine import ai_transcribe
        from ..ai_engine.transcribe import _format_srt

        # Keep sidecar publication under the same artifact guard as other plans.
        result = ai_transcribe(args["input_path"], model=args["model"])
        if result.get("success") is False:
            return result
        if result.get("transcript", "").strip() and result.get("segments"):
            with _atomic_artifact(args["output_srt"]) as staged, open_staged_writer(staged) as handle:
                handle.write(_format_srt(result["segments"]).encode("utf-8"))
            return {"success": True, **result, "output_srt": args["output_srt"]}
        return {"success": True, **result, "no_speech": True}
    if tool == "video_ai_remove_silence":
        from ..ai_engine import ai_remove_silence

        return _result(
            ai_remove_silence(
                args["input_path"],
                args["output_path"],
                args["silence_threshold"],
                args["min_silence_duration"],
                args["keep_margin"],
            )
        )
    handlers = {
        "video_trim": engine.trim,
        "video_speed": engine.speed,
        "video_crop": engine.crop,
        "video_resize": engine.resize,
        "video_normalize_audio": engine.normalize_audio,
        "video_subtitles": engine.subtitles,
        "video_thumbnail": engine.thumbnail,
        "video_add_audio": engine.add_audio,
    }
    result = _result(handlers[tool](**args))
    if tool == "video_add_audio":
        from ..receipts_ai_video import attach_add_audio_receipt

        return attach_add_audio_receipt(result, args["duration_policy"])
    return result


def _stat_or_none(path: str | None) -> os.stat_result | None:
    try:
        return Path(path).stat() if path else None
    except OSError:
        return None


def _artifact_changed(before: os.stat_result | None, after: os.stat_result | None) -> bool:
    if after is None:
        return False
    if before is None:
        return True
    return (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def _execute_step(tool: str, args: dict[str, Any], current: str) -> dict[str, Any]:
    """Validate one step's paths and arguments, then run it; errors become results."""
    try:
        validate_args(tool, args)
        _validate_input_path(clean_path(current))
        if tool == "video_subtitles":
            _validate_input_path(clean_path(args["subtitle_path"]))
        if tool != "video_ai_transcribe":
            _validate_output_path(clean_path(args["output_path"]))
        if tool == "video_trim":
            # Cleanup has unknown length until rendered. Never overrun it.
            info = probe(current)
            duration = info["duration"] if isinstance(info, dict) else info.duration
            available = duration - args["start"]
            if available < 0.01:
                invalid("Trim begins after the available video.")
            if "duration" in args:
                args["duration"] = min(args["duration"], available)
        return _run_step(tool, args)
    except Exception as exc:
        return _error_result(exc)


def _dry_run_result(plan: dict[str, Any]) -> dict[str, Any]:
    """Report a validated plan without rendering anything."""
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


def _copy_silent_output(current: str, plan: dict[str, Any]) -> str:
    """Copy the last render to the plan output when no speech was transcribed."""
    output = plan["output_path"]
    _validate_input_path(clean_path(current))
    _validate_output_path(clean_path(output))
    with (
        _atomic_output(output) as staged,
        open(current, "rb") as src_handle,
        open_staged_writer(staged) as dst_handle,
    ):
        shutil.copyfileobj(src_handle, dst_handle)
    return output


def _cleanup_intermediates(produced: list[str], plan: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """Remove rendered intermediates; return (kept, removed, retained)."""
    final_output = os.path.realpath(plan["output_path"])
    intermediate_paths = {
        os.path.realpath(step["args"]["output_path"])
        for step in plan["steps"]
        if step["tool"] not in {"video_ai_transcribe", "video_thumbnail"}
        and os.path.realpath(step["args"]["output_path"]) != final_output
    }
    removed, retained = [], []
    for path in produced:
        resolved = os.path.realpath(path)
        if resolved == final_output or resolved not in intermediate_paths:
            continue
        try:
            Path(path).unlink()
        except FileNotFoundError:
            removed.append(path)
        except OSError:
            retained.append(path)
        else:
            removed.append(path)
    return [path for path in produced if path not in removed], removed, retained


def apply(plan: dict, confirm: bool = False) -> dict[str, Any]:
    """Validate a reviewed direct plan; render only with explicit confirm=true.

    Hand-edited tools, paths and arguments are checked before any execution.
    Stops at the first failure and reports receipts and artifacts already made.
    Intermediate video renders are removed after every planned step succeeds.
    """
    if type(confirm) is not bool:
        invalid("confirm must be an explicit boolean.")
    plan = validate_plan(copy.deepcopy(plan))
    if not confirm:
        return _dry_run_result(plan)
    question = plan.get("question")
    has_question = bool(question.strip()) if isinstance(question, str) else bool(question)
    ambiguities = plan.get("ambiguities") or plan.get("ambiguity")
    if has_question or ambiguities:
        raise MCPVideoError(
            "Direct plan has unresolved question or ambiguity entries; resolve them before applying.",
            error_type="validation_error",
            code="unresolved_direct_question",
        )
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
        artifact = args.get("output_srt") if tool == "video_ai_transcribe" else args["output_path"]
        before = _stat_or_none(artifact)
        result = _execute_step(tool, args, current)
        if artifact and _artifact_changed(before, _stat_or_none(artifact)):
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
    if no_speech and current != plan["output_path"]:
        try:
            current = _copy_silent_output(current, plan)
        except Exception as exc:
            return {
                "success": False,
                "failed_step": len(plan["steps"]),
                "failed_tool": "video_direct_apply",
                "error": _error_result(exc).get("error"),
                "receipts": receipts,
                "produced": produced,
                "output_path": current,
            }
        produced.append(current)
    produced, removed, retained = _cleanup_intermediates(produced, plan)
    result = {"success": True, "dry_run": False, "receipts": receipts, "produced": produced, "output_path": current}
    if retained:
        result["cleanup"] = {"intermediates_removed": removed, "intermediates_retained": retained}
    return result
