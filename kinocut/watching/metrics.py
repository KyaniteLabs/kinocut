"""Offline metric QC third (P3.2): duration, blackdetect, loudness proxy."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT
from kinocut.errors import InputFileError
from kinocut.ffmpeg_helpers import _get_video_duration, _validate_input_path


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

    black = _blackdetect_ratio(path, duration)
    if black is None:
        findings.append(
            MetricFinding(
                check_id="black_frames.ratio",
                severity="warn",
                message="blackdetect unavailable; skipped",
                evidence={"available": False},
            )
        )
    elif black > max_black_ratio:
        findings.append(
            MetricFinding(
                check_id="black_frames.ratio",
                severity="fail",
                message=f"black ratio {black:.3f} exceeds max {max_black_ratio}",
                time_range=(0.0, duration),
                evidence={"black_ratio": black, "max": max_black_ratio},
            )
        )
    else:
        findings.append(
            MetricFinding(
                check_id="black_frames.ratio",
                severity="info",
                message=f"black ratio {black:.3f} ok",
                evidence={"black_ratio": black},
            )
        )

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
    if duration <= 0:
        return None
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        path,
        "-vf",
        "blackdetect=d=0.1:pix_th=0.10",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_FFMPEG_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stderr or "") + (proc.stdout or "")
    # black_start:0 black_end:1.2 black_duration:1.2
    spans = re.findall(r"black_duration:([0-9.]+)", text)
    if not spans and "blackdetect" not in text.lower() and proc.returncode != 0:
        return None
    total_black = sum(float(x) for x in spans)
    return min(1.0, total_black / duration)


def _integrated_lufs(path: str) -> float | None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        path,
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
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
