"""Audio waveform extraction operation for the FFmpeg engine."""

from __future__ import annotations

import math
import subprocess
import tempfile

from .defaults import (
    DEFAULT_FFMPEG_TIMEOUT,
    DEFAULT_WAVEFORM_FRAME_SAMPLES,
    DEFAULT_WAVEFORM_LEVEL_FLOOR,
    DEFAULT_WAVEFORM_SILENCE_THRESHOLD,
)
from .ffmpeg_helpers import _validate_input_path
from .engine_probe import probe_audio_input as probe
from .engine_runtime_utils import _ffmpeg
from .errors import MCPVideoError, ProcessingError
from .models import WaveformResult


def audio_waveform(input_path: str, bins: int = 50) -> WaveformResult:
    """Measure first-stream RMS dBFS in at most ``bins`` source-time windows.

    Video is not decoded. Missing audio at the start/end of the media timeline
    is silence; final-window RMS excludes padding used for bounded aggregation.
    """
    input_path = _validate_input_path(input_path)
    if isinstance(bins, bool) or not isinstance(bins, int) or not 1 <= bins <= 1000:
        raise MCPVideoError(
            f"bins must be between 1 and 1000, got {bins}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    input_info = probe(input_path)
    if input_info.audio_codec is None:
        raise MCPVideoError(
            "Audio waveform extraction requires an audio stream, but this media has none",
            error_type="validation_error",
            code="waveform_no_audio",
        )
    duration, sample_rate = input_info.duration, input_info.audio_sample_rate
    if not math.isfinite(duration) or duration <= 0 or not sample_rate or sample_rate <= 0:
        raise MCPVideoError(
            "Audio waveform extraction requires a positive duration and sample rate",
            error_type="validation_error",
            code="waveform_invalid_metadata",
        )
    target_samples = max(1, math.ceil(duration * sample_rate / bins))
    frames_per_window = math.ceil(target_samples / DEFAULT_WAVEFORM_FRAME_SAMPLES)
    frame_samples = math.ceil(target_samples / frames_per_window)
    window_samples = frame_samples * frames_per_window
    window_seconds = window_samples / sample_rate
    window_count = min(bins, math.ceil(duration / window_seconds))
    cmd = _waveform_command(input_path, duration, sample_rate, frame_samples, frames_per_window, window_count)
    metadata, stderr, returncode = _analyze_waveform(cmd, bins)
    if returncode != 0:
        if _is_known_ametadata_failure(stderr):
            return _synthetic_waveform(duration, duration / bins, bins)
        raise ProcessingError(" ".join(cmd), returncode, stderr)
    levels = _parse_rms_levels(metadata)
    if len(levels) != window_count:
        return _synthetic_waveform(duration, duration / bins, bins)
    return _measured_waveform(levels[:window_count], window_seconds, duration)


def _waveform_command(
    path: str,
    duration: float,
    sample_rate: int,
    frame_samples: int,
    frames_per_window: int,
    windows: int,
) -> list[str]:
    # Bound frame allocation even for hours-long input with one requested bin.
    # astats aggregates small frames; emit only each completed window. Pad the
    # last window for emission and correct its measured power before returning.
    total_samples = frame_samples * frames_per_window * windows
    filters = (
        f"aresample={sample_rate}:async=1:first_pts=0,atrim=duration={duration},"
        f"apad=whole_len={total_samples},atrim=end_sample={total_samples},"
        f"asetnsamples=n={frame_samples}:p=1,"
        f"astats=metadata=1:reset={frames_per_window}:measure_overall=RMS_level:measure_perchannel=none,"
        f"aselect=eq(mod(n+1\\,{frames_per_window})\\,0),"
        "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )
    return [
        _ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-xerror",
        "-i",
        path,
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        filters,
        "-frames:a",
        str(windows),
        "-f",
        "null",
        "-",
    ]


def _analyze_waveform(cmd: list[str], bins: int) -> tuple[str, str, int]:
    # Keep FFmpeg diagnostics and metadata off Python's unbounded PIPE buffers.
    # Each output frame emits only a header and the selected RMS key.
    with tempfile.TemporaryFile() as metadata_file, tempfile.TemporaryFile() as error_file:
        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=metadata_file,
                stderr=error_file,
                timeout=DEFAULT_FFMPEG_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError(
                " ".join(cmd),
                -1,
                f"Audio waveform extraction timed out after {DEFAULT_FFMPEG_TIMEOUT} seconds",
            ) from exc
        metadata_file.seek(0)
        metadata = metadata_file.read(bins * 256 + 1024).decode("utf-8", errors="replace")
        error_file.seek(0)
        stderr = error_file.read(4096).decode("utf-8", errors="replace")
        # Some callers inject CompletedProcess-like failures for compatibility.
        stderr = stderr or getattr(proc, "stderr", "") or ""
    return metadata, stderr, proc.returncode


def _parse_rms_levels(metadata: str) -> list[float]:
    levels: list[float] = []
    key = "lavfi.astats.Overall.RMS_level="
    for line in metadata.splitlines():
        if not line.startswith(key):
            continue
        try:
            level = float(line[len(key) :])
        except ValueError:
            continue
        if level == -math.inf:
            level = DEFAULT_WAVEFORM_LEVEL_FLOOR
        if math.isfinite(level):
            levels.append(max(DEFAULT_WAVEFORM_LEVEL_FLOOR, level))
    return levels


def _measured_waveform(levels: list[float], window: float, duration: float) -> WaveformResult:
    widths = [max(0.0, min(window, duration - index * window)) for index in range(len(levels))]
    levels = [
        level + 10 * math.log10(window / width) if level > DEFAULT_WAVEFORM_LEVEL_FLOOR else level
        for level, width in zip(levels, widths, strict=True)
    ]
    weighted_power = sum(10 ** (level / 10) * width for level, width in zip(levels, widths, strict=True))
    mean = max(DEFAULT_WAVEFORM_LEVEL_FLOOR, 10 * math.log10(weighted_power / sum(widths)))
    return WaveformResult(
        duration=duration,
        peaks=[
            {"time": round(index * window + width / 2, 2), "level": round(level, 1)}
            for index, (level, width) in enumerate(zip(levels, widths, strict=True))
        ],
        mean_level=round(mean, 1),
        max_level=round(max(levels), 1),
        min_level=round(min(levels), 1),
        silence_regions=_detect_silence(levels, window, duration),
    )


def _is_known_ametadata_failure(stderr: str) -> bool:
    has_missing_key = "Metadata key must be set" in stderr
    has_filter_init_failure = "Error initializing filters" in stderr or "Error reinitializing filters" in stderr
    return has_missing_key and has_filter_init_failure


def _synthetic_waveform(duration: float, segment_duration: float, bins: int) -> WaveformResult:
    return WaveformResult(
        duration=duration,
        peaks=[{"time": round((i + 0.5) * segment_duration, 2), "level": -20.0} for i in range(bins)],
        mean_level=-20.0,
        max_level=-20.0,
        min_level=-20.0,
        silence_regions=[],
        synthetic=True,
    )


def _detect_silence(levels: list[float], window: float, duration: float) -> list[dict]:
    regions: list[dict] = []
    start: float | None = None
    for index, level in enumerate(levels):
        if level < DEFAULT_WAVEFORM_SILENCE_THRESHOLD and start is None:
            start = index * window
        elif level >= DEFAULT_WAVEFORM_SILENCE_THRESHOLD and start is not None:
            regions.append({"start": round(start, 2), "end": round(index * window, 2)})
            start = None
    if start is not None:
        regions.append({"start": round(start, 2), "end": round(duration, 2)})
    return regions
