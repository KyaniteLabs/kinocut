"""Scene detection operation for the FFmpeg engine."""

from __future__ import annotations

import re
import subprocess

from .engine_probe import probe
from .engine_runtime_utils import _ffmpeg
from .ffmpeg_helpers import _sanitize_ffmpeg_number
from .errors import MCPVideoError, ProcessingError, parse_ffmpeg_error
from .ffmpeg_helpers import _validate_input_path, _escape_ffmpeg_filter_value
from .limits import DEFAULT_FFMPEG_TIMEOUT
from .models import SceneDetectionResult


def detect_scenes(
    input_path: str,
    threshold: float = 0.3,
    min_scene_duration: float = 1.0,
) -> SceneDetectionResult:
    """Detect scene changes in a video.

    Args:
        input_path: Path to the input video.
        threshold: Scene detection sensitivity (0.0-1.0, lower = more sensitive).
        min_scene_duration: Minimum duration of a scene in seconds.
    """
    input_path = _validate_input_path(input_path)
    if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
        raise MCPVideoError(
            f"threshold must be 0.0-1.0, got {threshold}", error_type="validation_error", code="invalid_parameter"
        )
    safe_threshold = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(threshold, "threshold")))
    info = probe(input_path)
    duration = info.duration

    cmd = [
        _ffmpeg(),
        "-i",
        input_path,
        "-vf",
        f"select='gt(scene,{safe_threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(
            " ".join(cmd),
            -1,
            f"Scene detection timed out after {DEFAULT_FFMPEG_TIMEOUT} seconds",
        ) from exc
    if proc.returncode != 0:
        raise parse_ffmpeg_error(proc.stderr)

    scene_times = _parse_scene_times(proc.stderr)
    scenes: list[dict] = []
    prev_time = 0.0
    for t in scene_times:
        if t - prev_time >= min_scene_duration:
            scenes.append(
                {
                    "start": round(prev_time, 2),
                    "end": round(t, 2),
                    "start_frame": round(prev_time * info.fps),
                    "end_frame": round(t * info.fps),
                }
            )
            prev_time = t

    if duration - prev_time >= 0.1:
        scenes.append(
            {
                "start": round(prev_time, 2),
                "end": round(duration, 2),
                "start_frame": round(prev_time * info.fps),
                "end_frame": round(duration * info.fps),
            }
        )

    return SceneDetectionResult(
        scenes=scenes,
        scene_count=len(scenes),
        duration=duration,
    )


def _parse_scene_times(stderr: str) -> list[float]:
    scene_times: list[float] = []
    for line in stderr.split("\n"):
        if "showinfo" not in line or "pts_time:" not in line:
            continue
        try:
            pts_match = re.search(r"pts_time:(\d+\.?\d*)", line)
            if pts_match:
                scene_times.append(float(pts_match.group(1)))
        except (ValueError, IndexError):
            continue
    return scene_times
