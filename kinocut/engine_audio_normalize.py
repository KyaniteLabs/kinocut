"""Audio normalization operation for the FFmpeg engine."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from pathlib import Path

from .defaults import DEFAULT_AUDIO_NORMALIZE_TRUE_PEAK_DBTP, DEFAULT_AUDIO_NORMALIZE_BITRATE
from .engine_runtime_utils import _build_edit_result, _get_audio_stream, _has_audio, _require_filter, _timed_operation
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
from .engine_audio_normalize_output import (
    MeasuredInputLoudness,
    MeasuredOutputLoudness,
    NormalizedAudioResult,
    _normalization_codec,
    _validate_normalized_output,
)
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


def _loudnorm_summaries(stderr: str) -> Iterator[dict]:
    parsed_blocks = re.findall(r"\[Parsed_loudnorm_[^\]]*\]\s*(\{.*?\})", stderr, re.DOTALL)
    candidates = parsed_blocks if parsed_blocks else re.findall(r"\{.*?\}", stderr, re.DOTALL)
    for text in reversed(candidates):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            yield data


def _measurement(stderr: str) -> dict[str, float]:
    names = {
        "input_i": "measured_I",
        "input_lra": "measured_LRA",
        "input_tp": "measured_TP",
        "input_thresh": "measured_thresh",
        "target_offset": "offset",
    }
    for data in _loudnorm_summaries(stderr):
        try:
            result = {dst: float(data[src]) for src, dst in names.items()}
            if all(math.isfinite(value) for value in result.values()):
                return result
        except (KeyError, TypeError, ValueError):
            continue
    raise MCPVideoError(
        "FFmpeg loudnorm analysis did not return valid measurements",
        error_type="processing_error",
        code="invalid_loudnorm_analysis",
    )


def _compute_loudnorm_fade_filter(probe: dict, fade: float) -> str:
    """Compute boundary fade filter string for the loudnorm pass."""
    audio = _get_audio_stream(probe) or {}
    duration = _timestamp(audio.get("duration"))
    if duration is None or duration <= 0:
        raise MCPVideoError(
            "Could not determine a finite positive media duration for boundary fades",
            error_type="processing_error",
            code="invalid_media_duration",
        )
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


def _input_reading(measured: dict[str, float] | None) -> MeasuredInputLoudness | None:
    if measured is None:
        return None
    return MeasuredInputLoudness(I=measured["measured_I"], LRA=measured["measured_LRA"], TP=measured["measured_TP"])


def _output_reading(stderr: str | None) -> MeasuredOutputLoudness | None:
    """Read achieved I and TP from the second-pass loudnorm JSON summary."""
    if not isinstance(stderr, str):
        return None
    for data in _loudnorm_summaries(stderr):
        try:
            integrated, peak = float(data["output_i"]), float(data["output_tp"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(integrated) and math.isfinite(peak):
            return MeasuredOutputLoudness(I=integrated, TP=peak)
    return None


def _unmeasurable_input_warnings(stderr: str) -> list[str] | None:
    """Non-finite integrated loudness can mean gated audio, not silence."""
    for data in _loudnorm_summaries(stderr):
        try:
            integrated, peak = float(data["input_i"]), float(data["input_tp"])
        except (KeyError, TypeError, ValueError):
            continue
        if integrated == -math.inf:
            if peak == -math.inf:
                return ["input_is_silent: the first audio track has no measurable signal."]
            if math.isfinite(peak):
                return []
    return None


def _build_loudnorm_render_filter(
    fade_filter: str,
    target_s: str,
    lra_s: str,
    peak_s: str,
    analysis_stderr: str,
    resample: str = "",
) -> tuple[str, list[str], dict[str, float] | None]:
    """Build the second-pass loudnorm filter from measured or target values.

    Returns the filter, warnings, and finite first-pass measurements.
    ``print_format=json`` makes the render pass report achieved loudness.
    ``resample`` is appended after loudnorm, which always outputs 192 kHz.
    """
    try:
        measured = _measurement(analysis_stderr)
    except MCPVideoError:
        warnings = _unmeasurable_input_warnings(analysis_stderr)
        if warnings is None:
            raise
        if warnings:
            return f"{fade_filter}anull{resample}", warnings, None
        return (
            f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:print_format=json{resample}",
            warnings,
            None,
        )
    measured_filter = ":".join(
        f"{key}={_escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, 'measured level')))}"
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
    render_filter = (
        f"{fade_filter}loudnorm=I={target_s}:LRA={lra_s}:TP={peak_s}:"
        f"{measured_filter}:linear=true:print_format=json{resample}"
    )
    return render_filter, warnings, measured


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
    audio = _get_audio_stream(probe) or {}
    duration = _timestamp(audio.get("duration"))
    if duration is not None and duration > 0 and not video_container:
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


def _normalized_result(
    staged: str,
    output: str,
    codec: str | None,
    timing: dict,
    warnings: list[str],
    measured_input: MeasuredInputLoudness | None = None,
    measured_output: MeasuredOutputLoudness | None = None,
) -> EditResult:
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
        **{
            **result.model_dump(),
            "audio_codec": audio.get("codec_name"),
            "warnings": [*result.warnings, *warnings],
            "measured_input": measured_input,
            "measured_output": measured_output,
            "measured_output_source": "second_pass_loudnorm_filter" if measured_output is not None else None,
        }
    )


def _apply_loudnorm(
    input_path: str,
    probe: dict,
    staged: str,
    fade: float,
    target_s: str,
    lra_s: str,
    peak_s: str,
    codec: str,
    video_container: bool,
) -> tuple[list[str], MeasuredInputLoudness | None, MeasuredOutputLoudness | None]:
    """Run two-pass loudnorm and return warnings plus before/after readings."""
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
    render_filter, warnings, measured = _build_loudnorm_render_filter(
        fade_filter, target_s, lra_s, peak_s, analysis.stderr, _resample_filter(probe)
    )
    rendered = _run_audio_ffmpeg(
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
    output_reading = _output_reading(rendered.stderr) if "loudnorm=" in render_filter else None
    return warnings, _input_reading(measured), output_reading


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
    measured_input: MeasuredInputLoudness | None = None
    measured_output: MeasuredOutputLoudness | None = None
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
            # Nothing was normalized; the caller must not read this as a loudness result.
            warnings = ["input_has_no_audio_stream: nothing was normalized; the output is a stream copy of the input."]
        else:
            warnings, measured_input, measured_output = _apply_loudnorm(
                input_path, probe, staged, fade, target_s, lra_s, peak_s, codec, video_container
            )
        result = _normalized_result(
            staged,
            output,
            codec if has_audio else None,
            timing,
            warnings,
            measured_input,
            measured_output,
        )
    return result.model_copy(update={"output_path": output, "elapsed_ms": timing["elapsed_ms"]})
