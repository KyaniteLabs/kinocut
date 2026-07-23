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


def normalize_audio(
    input_path: str,
    target_lufs: float = -16.0,
    lra: float = 11.0,
    output_path: str | None = None,
    *,
    true_peak_dbtp: float = -1.0,
) -> EditResult:
    """Normalize audio with FFmpeg's two-pass loudnorm filter."""
    input_path = _validate_input_path(input_path)
    target, loudness_range = _number(target_lufs, "target_lufs", -70, -5), _number(lra, "lra", 0, 50)
    peak = _number(true_peak_dbtp, "true_peak_dbtp", -12, 0)
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
    has_audio = _has_audio(_run_ffprobe_json(input_path))
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
            analysis = _run_ffmpeg(
                [
                    "-i",
                    input_path,
                    "-af",
                    f"loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:print_format=json",
                    "-f",
                    "null",
                    "-",
                ]
            )
            try:
                measured = _measurement(analysis.stderr)
            except MCPVideoError:
                if "input_i" not in analysis.stderr or "-inf" not in analysis.stderr:
                    raise
                render_filter = f"loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}"
            else:
                measured_filter = ":".join(f"{key}={_escaped(value, key)}" for key, value in measured.items())
                render_filter = f"loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:{measured_filter}:linear=true"
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
