"""Audio normalization operation for the FFmpeg engine."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .engine_runtime_utils import _build_edit_result, _has_audio, _require_filter, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _run_ffprobe_json,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .errors import MCPVideoError
from .models import EditResult


def _number(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise MCPVideoError(f"{name} must be a finite number", error_type="validation_error", code="invalid_parameter")
    result = float(value)
    if not low <= result <= high:
        raise MCPVideoError(
            f"{name} must be {low} to {high}, got {value}", error_type="validation_error", code="invalid_parameter"
        )
    return result


def _measurement(stderr: str) -> dict[str, float]:
    for text in reversed(re.findall(r"\{.*?\}", stderr, re.DOTALL)):
        try:
            data = json.loads(text)
            names = {
                "input_i": "measured_I",
                "input_lra": "measured_LRA",
                "input_tp": "measured_TP",
                "input_thresh": "measured_thresh",
                "target_offset": "offset",
            }
            result = {dst: float(data[src]) for src, dst in names.items()}
            if all(math.isfinite(value) for value in result.values()):
                return result
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    raise MCPVideoError(
        "FFmpeg loudnorm analysis did not return valid measurements",
        error_type="processing_error",
        code="invalid_loudnorm_analysis",
    )


def _compute_loudnorm_fade_filter(probe: dict, fade: float) -> str:
    """Compute boundary fade filter string for the loudnorm pass."""
    duration_value = next(
        (
            stream.get("duration")
            for stream in probe.get("streams", [])
            if stream.get("codec_type") == "audio" and stream.get("duration") is not None
        ),
        None,
    )
    if duration_value is None:
        format_data = probe.get("format")
        duration_value = format_data.get("duration") if isinstance(format_data, dict) else None
    try:
        duration = float(duration_value)
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise MCPVideoError(
            "Could not determine a finite positive media duration for boundary fades",
            error_type="processing_error",
            code="invalid_media_duration",
        )
    boundary = min(fade, duration / 2)
    if boundary <= 0:
        return ""
    boundary_s = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(boundary, "fade_seconds")))
    fade_out_start_s = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(duration - boundary, "fade_out_start")))
    return f"afade=t=in:st=0:d={boundary_s},afade=t=out:st={fade_out_start_s}:d={boundary_s},"


def _build_loudnorm_render_filter(
    fade_filter: str,
    target_s: str,
    lra_s: str,
    peak_s: str,
    analysis_stderr: str,
) -> str:
    """Build the second-pass loudnorm filter from measured or target values."""
    try:
        measured = _measurement(analysis_stderr)
    except MCPVideoError:
        if "input_i" not in analysis_stderr or "-inf" not in analysis_stderr:
            raise
        return f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}"
    measured_filter = ":".join(
        f"{key}={_escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, key)))}"
        for key, value in measured.items()
    )
    return f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:{measured_filter}:linear=true"


def normalize_audio(
    input_path: str,
    target_lufs: float = -16.0,
    lra: float = 11.0,
    output_path: str | None = None,
    *,
    true_peak_dbtp: float = -1.0,
    fade_seconds: float = 0.01,
) -> EditResult:
    """Normalize audio with FFmpeg's two-pass loudnorm filter."""
    input_path = _validate_input_path(input_path)
    target, loudness_range = _number(target_lufs, "target_lufs", -70, -5), _number(lra, "lra", 0, 50)
    peak = _number(true_peak_dbtp, "true_peak_dbtp", -12, 0)
    fade = _number(fade_seconds, "fade_seconds", 0, 1)
    _require_filter("loudnorm", "Audio normalization")
    output = output_path or _auto_output(input_path, "normalized")
    _validate_output_path(output)

    def _escaped(value: float, name: str) -> str:
        return _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, name)))

    target_s, lra_s, peak_s = (
        _escaped(target, "target_lufs"),
        _escaped(loudness_range, "lra"),
        _escaped(peak, "true_peak_dbtp"),
    )
    probe = _run_ffprobe_json(input_path)
    has_audio = _has_audio(probe)
    with _timed_operation() as timing:
        if not has_audio:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
                    video_codec="copy",
                    audio_codec="copy",
                )
            )
        else:
            fade_filter = _compute_loudnorm_fade_filter(probe, fade)
            analysis = _run_ffmpeg(
                [
                    "-i",
                    input_path,
                    "-af",
                    f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:print_format=json",
                    "-f",
                    "null",
                    "-",
                ]
            )
            render_filter = _build_loudnorm_render_filter(fade_filter, target_s, lra_s, peak_s, analysis.stderr)
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
                    video_codec="copy",
                    audio_filter=render_filter,
                    audio_bitrate="192k",
                )
            )
    return _build_edit_result(
        output, "normalize_audio", timing, format=Path(output).suffix.lstrip(".") or "wav", audio_only=True
    )
