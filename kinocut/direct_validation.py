"""Admission for untrusted, possibly model-edited direct plans."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

from .direct.planner import ALLOWED_TOOLS
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_artifact_path, _validate_input_path, _validate_output_path
from .limits import MAX_RESOLUTION, MAX_VIDEO_DURATION


def invalid(message: str):
    raise MCPVideoError(message, error_type="validation_error", code="invalid_direct_plan")


def clean_path(value) -> str:
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        invalid("Direct paths must be nonempty absolute local paths.")
    if any(ord(c) < 32 for c in value) or ".." in re.split(r"[\\/]+", value):
        invalid("Direct paths cannot contain controls or directory traversal.")
    return value


def _number(args, key, low, high, *, integer=False):
    value = args.get(key)
    types = (int,) if integer else (int, float)
    if type(value) not in types or not math.isfinite(value) or not low <= value <= high:
        invalid(f"{key} must be a finite number between {low} and {high}.")


def validate_args(tool: str, args: dict):
    """Exact keys and bounded primitives; no arbitrary filter or model parameters."""
    common = {"input_path", "output_path"}
    allowed = {
        "video_trim": common | {"start", "duration", "accurate"},
        "video_ai_remove_silence": common | {"silence_threshold", "min_silence_duration", "keep_margin"},
        "video_speed": common | {"factor"},
        "video_crop": common | {"width", "height"},
        "video_resize": common | {"width", "height", "quality"},
        "video_normalize_audio": common | {"target_lufs"},
        "video_ai_transcribe": {"input_path", "output_srt", "model"},
        "video_subtitles": common | {"subtitle_path"},
        "video_thumbnail": common | {"timestamp"},
        "video_add_audio": {"video_path", "audio_path", "output_path", "volume", "mix", "duration_policy"},
    }
    if tool not in ALLOWED_TOOLS:
        invalid("Unknown tool in direct plan.")
    required = allowed[tool] - ({"duration"} if tool == "video_trim" else set())
    if not isinstance(args, dict) or set(args) - allowed[tool] or required - set(args):
        invalid("Unexpected or missing arguments for this direct step.")
    if tool == "video_trim":
        _number(args, "start", 0, MAX_VIDEO_DURATION)
        if "duration" in args:
            _number(args, "duration", 0.01, MAX_VIDEO_DURATION)
        if args["accurate"] is not True:
            invalid("Direct trims must be frame accurate.")
    elif tool == "video_speed":
        _number(args, "factor", 0.5, 2.0)
    elif tool == "video_ai_remove_silence":
        _number(args, "silence_threshold", -70, 0)
        _number(args, "min_silence_duration", 0.01, 10)
        _number(args, "keep_margin", 0, 2)
    elif tool in {"video_crop", "video_resize"}:
        for key in ("width", "height"):
            _number(args, key, 2, MAX_RESOLUTION, integer=True)
            if args[key] % 2:
                invalid("Direct dimensions must be even.")
        if tool == "video_resize" and args["quality"] != "high":
            invalid("Direct resize quality must be high.")
    elif tool == "video_normalize_audio":
        _number(args, "target_lufs", -70, -5)
    elif tool == "video_ai_transcribe" and args["model"] != "base":
        invalid("Direct captions use only the existing base transcription path.")
    elif tool == "video_thumbnail":
        _number(args, "timestamp", 0, MAX_VIDEO_DURATION)
    elif tool == "video_add_audio":
        _number(args, "volume", 0, 0)
        if args["mix"] is not False or args["duration_policy"] != "keep_video":
            invalid("Direct muting must replace audio at zero gain and preserve video duration.")


def validate_plan(plan: dict) -> dict:
    """Validate the entire chain before the first write, including future outputs."""
    if not isinstance(plan, dict) or type(plan.get("version")) is not int or plan["version"] != 1:
        invalid("Expected a version 1 direct plan.")
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) > 16:
        invalid("Expected at most 16 direct steps.")
    source = _validate_input_path(clean_path(plan.get("input_path")))
    final = clean_path(plan.get("output_path"))
    current, srt = source, None
    outputs = {source}
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str):
            invalid("Invalid direct step.")
        tool, args = step["tool"], step.get("args")
        validate_args(tool, args)
        inp = clean_path(args["video_path"] if tool == "video_add_audio" else args["input_path"])
        if os.path.realpath(inp) != current:
            invalid("Step inputs must follow the planned output chain.")
        if tool == "video_add_audio" and os.path.realpath(clean_path(args["audio_path"])) != current:
            invalid("Muting must use this step's video as its zero-gain audio source.")
        dest = clean_path(args.get("output_srt") if tool == "video_ai_transcribe" else args.get("output_path"))
        if tool == "video_ai_transcribe":
            _validate_artifact_path(dest)
            if Path(dest).suffix != ".srt":
                invalid("Transcription output must be an SRT file.")
        else:
            _validate_output_path(dest)
            suffixes = {".jpg", ".png"} if tool == "video_thumbnail" else {".mp4", ".mov", ".mkv", ".webm"}
            if Path(dest).suffix.lower() not in suffixes:
                invalid("Unsupported direct output extension.")
        resolved = os.path.realpath(dest)
        if resolved in outputs:
            invalid("Direct outputs must be unique and must not overwrite inputs.")
        outputs.add(resolved)
        if tool == "video_ai_transcribe":
            srt = resolved
        elif tool == "video_subtitles":
            if os.path.realpath(clean_path(args["subtitle_path"])) != srt:
                invalid("Captions must use the SRT generated by this plan.")
            current = resolved
        elif tool != "video_thumbnail":
            current = resolved
    if os.path.realpath(final) != current:
        invalid("Final output must match the last video in the chain.")
    return plan
