"""Offline metric QC third (P3.2): duration, blackdetect, loudness proxy."""

from __future__ import annotations

import json
import contextlib
import logging
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT
from kinocut.errors import InputFileError, MCPVideoError
from kinocut.ffmpeg_helpers import (
    _escape_ffmpeg_filter_path,
    _get_video_duration,
    _run_command,
    _validate_input_path,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricFinding:
    check_id: str
    severity: str  # info | warn | fail
    message: str
    time_range: tuple[float, float] | None = None
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.time_range is not None:
            d["time_range"] = {"start": self.time_range[0], "end": self.time_range[1]}
        return d


def _black_finding(path: str, duration: float, max_black_ratio: float) -> MetricFinding:
    """Build a black_frames finding from blackdetect ratio."""
    black = _blackdetect_ratio(path, duration)
    if black is None:
        return MetricFinding(
            check_id="black_frames.ratio",
            severity="warn",
            message="blackdetect unavailable; skipped",
            evidence={"available": False},
        )
    if black > max_black_ratio:
        return MetricFinding(
            check_id="black_frames.ratio",
            severity="fail",
            message=f"black ratio {black:.3f} exceeds max {max_black_ratio}",
            time_range=(0.0, duration),
            evidence={"black_ratio": black, "max": max_black_ratio},
        )
    return MetricFinding(
        check_id="black_frames.ratio",
        severity="info",
        message=f"black ratio {black:.3f} ok",
        evidence={"black_ratio": black},
    )


def run_metric_qc(
    input_path: str,
    *,
    min_duration_seconds: float = 0.5,
    max_black_ratio: float = 0.95,
) -> list[MetricFinding]:
    """Run offline metric checks anchored to whole-file or range findings."""
    path = _validate_input_path(input_path)
    findings: list[MetricFinding] = []
    try:
        duration = float(_get_video_duration(path))
    except Exception as exc:
        raise InputFileError(path, f"cannot probe duration: {exc}") from exc

    if duration < min_duration_seconds:
        findings.append(
            MetricFinding(
                check_id="duration.min",
                severity="fail",
                message=f"duration {duration:.3f}s below min {min_duration_seconds}",
                time_range=(0.0, duration),
                evidence={"duration": duration, "min": min_duration_seconds},
            )
        )
    else:
        findings.append(
            MetricFinding(
                check_id="duration.min",
                severity="info",
                message=f"duration {duration:.3f}s ok",
                time_range=(0.0, duration),
                evidence={"duration": duration},
            )
        )

    findings.append(_black_finding(path, duration, max_black_ratio))

    lufs = _integrated_lufs(path)
    if lufs is None:
        findings.append(
            MetricFinding(
                check_id="audio.lufs",
                severity="warn",
                message="loudnorm probe unavailable; skipped",
                evidence={"available": False},
            )
        )
    else:
        # Informative band only — not a hard delivery gate.
        severity = "info" if -24.0 <= lufs <= -9.0 else "warn"
        findings.append(
            MetricFinding(
                check_id="audio.lufs",
                severity=severity,
                message=f"integrated LUFS ≈ {lufs:.2f}",
                evidence={"integrated_lufs": lufs},
            )
        )

    findings.append(
        MetricFinding(
            check_id="av_sync.proxy",
            severity="info",
            message="AV-sync deep probe not claimed; use compare_quality for pairwise metrics",
            evidence={"available": False},
        )
    )
    return findings


def _blackdetect_ratio(path: str, duration: float) -> float | None:
    """Measure displayed black coverage over decoded video, including its last frame.

    Container duration may include a longer audio track. Compact frame metadata
    stays on a managed temporary file and is reduced incrementally, so Python
    memory does not grow with video length. Failed decoding is never a zero ratio.
    """
    if duration <= 0:
        return None
    try:
        with contextlib.ExitStack() as stack:
            metadata_dir = stack.enter_context(tempfile.TemporaryDirectory(prefix="kinocut_black_"))
            metadata = Path(metadata_dir) / "frames.txt"
            diagnostics = stack.enter_context(tempfile.TemporaryFile())
            movie_path, pass_fds = path, ()
            if os.name == "posix" and Path("/proc/self/fd").is_dir():
                source = stack.enter_context(open(path, "rb"))
                movie_path, pass_fds = f"/proc/self/fd/{source.fileno()}", (source.fileno(),)
            _run_command(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"movie={_escape_ffmpeg_filter_path(movie_path)},blackdetect=d=0.1:pix_th=0.10",
                    "-show_frames",
                    "-show_entries",
                    "frame=best_effort_timestamp_time,duration_time,pkt_duration_time:"
                    "frame_tags=lavfi.black_start,lavfi.black_end",
                    "-of",
                    "compact",
                    "-o",
                    str(metadata),
                ],
                timeout=DEFAULT_FFMPEG_TIMEOUT,
                pass_fds=pass_fds,
                stderr_sink=diagnostics,
            )
            # Some decoders conceal damage and exit zero despite error diagnostics.
            diagnostics.seek(0)
            if diagnostics.read(1):
                logger.warning("Black coverage decode emitted error diagnostics")
                return None
            with metadata.open(encoding="utf-8") as frames:
                return _black_coverage_from_frames(frames)
    except (OSError, MCPVideoError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Black coverage unavailable: %s", type(exc).__name__)
        return None


def _black_coverage_from_frames(frames: Iterable[str]) -> float | None:
    """Reduce blackdetect transitions using PTS intervals and terminal duration."""
    previous_time = None
    previous_black = False
    black_seconds = total_seconds = terminal_duration = 0.0
    for line in frames:
        if not line.strip():
            continue
        if not line.startswith("frame|"):
            return None
        fields = dict(part.split("=", 1) for part in line.strip().split("|")[1:])
        timestamp = float(fields["best_effort_timestamp_time"])
        terminal_duration = float(fields.get("duration_time", fields.get("pkt_duration_time", "0")))
        if not math.isfinite(timestamp) or not math.isfinite(terminal_duration) or terminal_duration < 0:
            return None
        if previous_time is not None:
            interval = timestamp - previous_time
            if interval <= 0:
                return None
            total_seconds += interval
            if previous_black:
                black_seconds += interval
        if "tag:lavfi.black_start" in fields:
            previous_black = True
        if "tag:lavfi.black_end" in fields:
            previous_black = False
        previous_time = timestamp
    if previous_time is None or terminal_duration <= 0:
        return None
    total_seconds += terminal_duration
    if previous_black:
        black_seconds += terminal_duration
    return black_seconds / total_seconds


def _integrated_lufs(path: str) -> float | None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        path,
        "-vn",
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=DEFAULT_FFMPEG_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    stderr = proc.stderr or ""
    # loudnorm prints JSON block at end of stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return float(data.get("input_i"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
