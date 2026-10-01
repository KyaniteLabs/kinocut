"""Audio normalization operation for the FFmpeg engine."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .defaults import DEFAULT_AUDIO_NORMALIZE_TRUE_PEAK_DBTP, DEFAULT_AUDIO_NORMALIZE_BITRATE
from .engine_runtime_utils import _build_edit_result, _has_audio, _require_filter, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import (
    _atomic_output,
    _build_ffmpeg_cmd,
    _escape_ffmpeg_filter_value,
    _format_ffmpeg_number,
    _run_ffmpeg,
    _run_ffprobe_json,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .errors import MCPVideoError
from .engine_media_timeline import _primary_audio_timeline, _timestamp
from .engine_audio_validation import _audio_number as _number
from .engine_audio_validation import _run_audio_ffmpeg
from .models import EditResult
from .engine_audio_normalize_output import NormalizedAudioResult, _normalization_codec, _validate_normalized_output
from .validation import (
    AUDIO_NORMALIZE_MIN_TARGET_LUFS,
    AUDIO_NORMALIZE_MAX_TARGET_LUFS,
    AUDIO_NORMALIZE_MIN_LRA,
    AUDIO_NORMALIZE_MAX_LRA,
    AUDIO_NORMALIZE_MIN_TRUE_PEAK_DBTP,
    AUDIO_NORMALIZE_MAX_TRUE_PEAK_DBTP,
    AUDIO_NORMALIZE_MIN_FADE_SECONDS,
    AUDIO_NORMALIZE_MAX_FADE_SECONDS,
)


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
    audio = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), {})
    start = _timestamp(audio.get("start_time")) or 0.0
    origin = _timestamp(probe.get("format", {}).get("start_time")) or 0.0
    start -= origin
    boundary = min(fade, duration / 2)
    if boundary <= 0:
        return ""
    boundary_s = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(boundary, "fade_seconds")))
    fade_out_start_s = _escape_ffmpeg_filter_value(
        str(_sanitize_ffmpeg_number(start + duration - boundary, "fade_out_start"))
    )
    start_s = _escape_ffmpeg_filter_value(_format_ffmpeg_number(start))
    return f"afade=t=in:st={start_s}:d={boundary_s},afade=t=out:st={fade_out_start_s}:d={boundary_s},"


def _build_loudnorm_render_filter(
    fade_filter: str,
    target_s: str,
    lra_s: str,
    peak_s: str,
    analysis_stderr: str,
    resample: str = "",
) -> tuple[str, list[str]]:
    """Build the second-pass loudnorm filter from measured or target values.

    Returns the filter and the warnings to report. ``resample`` is appended
    after loudnorm, which always outputs 192 kHz.
    """
    try:
        measured = _measurement(analysis_stderr)
    except MCPVideoError:
        if "input_i" not in analysis_stderr or "-inf" not in analysis_stderr:
            raise
        return f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}{resample}", []
    measured_filter = ":".join(
        f"{key}={_escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, key)))}"
        for key, value in measured.items()
    )
    warnings = []
    # loudnorm keeps linear=true only if the gain keeps the true peak under TP; otherwise it silently
    # switches to its dynamic limiter, which reshapes the dynamics and can end above the ceiling.
    peak_after_gain = measured["measured_TP"] + float(target_s) - measured["measured_I"]
    if peak_after_gain > float(peak_s):
        warnings.append(
            f"A linear gain to {target_s} LUFS would put the true peak at {peak_after_gain:.1f} dBTP, above "
            f"{peak_s} dBTP, so FFmpeg loudnorm used dynamic mode: short peaks may exceed the ceiling. "
            "Lower target_lufs or compress the peaks first to keep the gain linear."
        )
    return (
        f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:{measured_filter}:linear=true{resample}",
        warnings,
    )


def _resample_filter(probe: dict) -> str:
    """Bring loudnorm's 192 kHz output back to the source sample rate."""
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            try:
                rate = int(stream.get("sample_rate") or 0)
            except (TypeError, ValueError):
                rate = 0
            if 8000 <= rate <= 192000:
                return f",aresample={rate}"
    return ",aresample=48000"


def _render_extra(probe: dict, video_container: bool) -> list[str]:
    extra = ["-xerror", "-map", "0:v:0?", "-map", "0:a:0"] if video_container else ["-xerror", "-vn", "-map", "0:a:0"]
    audio = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), {})
    try:
        duration = float(audio.get("duration") or probe.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if math.isfinite(duration) and duration > 0 and not video_container:
        extra += ["-t", str(duration)]
    return extra


def _normalization_probe(path: str) -> dict:
    """Bind all normalization metadata to the explicitly mapped primary audio."""
    probe = _run_ffprobe_json(path)
    if not _has_audio(probe):
        return probe
    start, duration = _primary_audio_timeline(path, probe)
    probe = {**probe, "streams": [dict(stream) for stream in probe["streams"]]}
    audio = next(stream for stream in probe["streams"] if stream.get("codec_type") == "audio")
    audio.update(start_time=start, duration=duration)
    return probe


def _normalized_result(staged: str, output: str, codec: str | None, timing: dict, warnings: list[str]) -> EditResult:
    observed = _validate_normalized_output(staged, codec)
    result = _build_edit_result(
        staged,
        "normalize_audio",
        timing,
        format=observed.get("format", {}).get("format_name") or Path(output).suffix.lstrip("."),
        audio_only=True,
    )
    audio = next((item for item in observed.get("streams", []) if item.get("codec_type") == "audio"), {})
    return NormalizedAudioResult(
        **{**result.model_dump(), "audio_codec": audio.get("codec_name"), "warnings": [*result.warnings, *warnings]}
    )


def normalize_audio(
    input_path: str,
    target_lufs: float = -16.0,
    lra: float = 11.0,
    output_path: str | None = None,
    *,
    true_peak_dbtp: float = DEFAULT_AUDIO_NORMALIZE_TRUE_PEAK_DBTP,
    fade_seconds: float = 0.01,
) -> EditResult:
    """Normalize audio with FFmpeg's two-pass loudnorm filter."""
    input_path = _validate_input_path(input_path)
    target = _number(target_lufs, "target_lufs", AUDIO_NORMALIZE_MIN_TARGET_LUFS, AUDIO_NORMALIZE_MAX_TARGET_LUFS)
    loudness_range = _number(lra, "lra", AUDIO_NORMALIZE_MIN_LRA, AUDIO_NORMALIZE_MAX_LRA)
    peak = _number(
        true_peak_dbtp, "true_peak_dbtp", AUDIO_NORMALIZE_MIN_TRUE_PEAK_DBTP, AUDIO_NORMALIZE_MAX_TRUE_PEAK_DBTP
    )
    fade = _number(fade_seconds, "fade_seconds", AUDIO_NORMALIZE_MIN_FADE_SECONDS, AUDIO_NORMALIZE_MAX_FADE_SECONDS)
    _require_filter("loudnorm", "Audio normalization")
    output = output_path or _auto_output(input_path, "normalized")
    _validate_output_path(output)
    codec, video_container = _normalization_codec(output)

    def _escaped(value: float, name: str) -> str:
        return _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, name)))

    target_s = _escaped(target, "target_lufs")
    lra_s, peak_s = _escaped(loudness_range, "lra"), _escaped(peak, "true_peak_dbtp")
    probe = _normalization_probe(input_path)
    has_audio = _has_audio(probe)
    warnings: list[str] = []
    with _timed_operation() as timing, _atomic_output(output) as staged:
        _validate_output_path(staged)
        if not has_audio:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=staged,
                    video_codec="copy",
                    audio_codec="copy",
                )
            )
        else:
            fade_filter = _compute_loudnorm_fade_filter(probe, fade)
            analysis = _run_audio_ffmpeg(
                [
                    "-xerror",
                    "-i",
                    input_path,
                    "-vn",
                    "-map",
                    "0:a:0",
                    "-af",
                    f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:print_format=json",
                    "-f",
                    "null",
                    "-",
                ],
                runner=_run_ffmpeg,
            )
            render_filter, warnings = _build_loudnorm_render_filter(
                fade_filter, target_s, lra_s, peak_s, analysis.stderr, _resample_filter(probe)
            )
            _run_audio_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=staged,
                    video_codec="copy" if video_container else None,
                    audio_codec=codec,
                    audio_filter=render_filter if video_container else render_filter + ",asetpts=N/SR/TB,apad",
                    audio_bitrate=DEFAULT_AUDIO_NORMALIZE_BITRATE,
                    extra=_render_extra(probe, video_container),
                ),
                runner=_run_ffmpeg,
            )
        result = _normalized_result(staged, output, codec if has_audio else None, timing, warnings)
    return result.model_copy(update={"output_path": output, "elapsed_ms": timing["elapsed_ms"]})
