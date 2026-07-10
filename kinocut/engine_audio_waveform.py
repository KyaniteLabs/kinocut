"""Audio waveform extraction operation for the FFmpeg engine."""

from __future__ import annotations

import subprocess

from .ffmpeg_helpers import _validate_input_path
from .engine_probe import probe
from .engine_runtime_utils import _ffmpeg
from .errors import MCPVideoError, ProcessingError
from .limits import DEFAULT_FFMPEG_TIMEOUT
from .models import WaveformResult


def audio_waveform(
    input_path: str,
    bins: int = 50,
) -> WaveformResult:
    """Extract audio waveform data (peaks and silence regions).

    Args:
        input_path: Path to the input video/audio file.
        bins: Number of time segments to analyze (default 50).
    """
    input_path = _validate_input_path(input_path)
    if not isinstance(bins, int) or bins < 1 or bins > 1000:
        raise MCPVideoError(
            f"bins must be between 1 and 1000, got {bins}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    input_info = probe(input_path)
    if input_info.audio_codec is None:
        raise MCPVideoError(
            "Audio waveform extraction requires an audio stream, but this video has none",
            error_type="validation_error",
            code="waveform_no_audio",
        )

    duration = input_info.duration
    segment_duration = duration / bins
    cmd = [_ffmpeg(), "-i", input_path, "-af", "astats=metadata=1:reset=0,ametadata=1", "-f", "null", "-"]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(
            " ".join(cmd),
            -1,
            f"Audio waveform extraction timed out after {DEFAULT_FFMPEG_TIMEOUT} seconds",
        ) from exc
    if proc.returncode != 0:
        if _is_known_ametadata_failure(proc.stderr):
            return _synthetic_waveform(duration, segment_duration, bins)
        raise ProcessingError(" ".join(cmd), proc.returncode, proc.stderr)
    levels = _parse_rms_levels(proc.stderr)
    if not levels:
        return _synthetic_waveform(duration, segment_duration, bins)

    binned = _bin_levels(levels, bins)
    peaks = _build_peaks(binned, segment_duration)
    silence_regions = _detect_silence(binned, segment_duration, duration)

    mean_level = sum(binned) / len(binned) if binned else -60.0
    max_level = max(binned) if binned else -60.0
    min_level = min(binned) if binned else -60.0

    return WaveformResult(
        duration=duration,
        peaks=peaks,
        mean_level=round(mean_level, 1),
        max_level=round(max_level, 1),
        min_level=round(min_level, 1),
        silence_regions=silence_regions,
    )


def _parse_rms_levels(stderr: str) -> list[float]:
    levels: list[float] = []
    for line in stderr.split("\n"):
        line = line.strip()
        if "Parsed_dc" in line or "n_samples" in line:
            continue
        if "RMS_level_dB" not in line:
            continue
        try:
            parts = line.split("RMS_level_dB=")
            if len(parts) >= 2:
                levels.append(float(parts[1].split()[0]))
        except (ValueError, IndexError):
            continue
    return levels


def _is_known_ametadata_failure(stderr: str) -> bool:
    has_missing_key = "Metadata key must be set" in stderr
    has_filter_init_failure = "Error initializing filters" in stderr or "Error reinitializing filters" in stderr
    return has_missing_key and has_filter_init_failure


def _synthetic_waveform(duration: float, segment_duration: float, bins: int) -> WaveformResult:
    peaks = []
    for i in range(bins):
        t = (i + 0.5) * segment_duration
        peaks.append({"time": round(t, 2), "level": -20.0})

    return WaveformResult(
        duration=duration,
        peaks=peaks,
        mean_level=-20.0,
        max_level=-20.0,
        min_level=-20.0,
        silence_regions=[],
        synthetic=True,
    )


def _bin_levels(levels: list[float], bins: int) -> list[float]:
    samples_per_bin = max(1, len(levels) // bins)
    binned: list[float] = []
    for i in range(bins):
        start_idx = i * samples_per_bin
        end_idx = min((i + 1) * samples_per_bin, len(levels))
        if start_idx < len(levels):
            binned.append(sum(levels[start_idx:end_idx]) / (end_idx - start_idx))
    return binned


def _build_peaks(binned: list[float], segment_duration: float) -> list[dict]:
    peaks = []
    for i, level in enumerate(binned):
        t = (i + 0.5) * segment_duration
        peaks.append({"time": round(t, 2), "level": round(level, 1)})
    return peaks


def _detect_silence(binned: list[float], segment_duration: float, duration: float) -> list[dict]:
    silence_threshold = -50.0
    silence_regions: list[dict] = []
    in_silence = False
    silence_start = 0.0
    for i, level in enumerate(binned):
        t = (i + 0.5) * segment_duration
        if level < silence_threshold and not in_silence:
            in_silence = True
            silence_start = t
        elif level >= silence_threshold and in_silence:
            in_silence = False
            silence_regions.append({"start": round(silence_start, 2), "end": round(t, 2)})
    if in_silence:
        silence_regions.append({"start": round(silence_start, 2), "end": round(duration, 2)})
    return silence_regions
