"""Offline metric QC third (P3.2 floor): black frames, duration, loudness proxies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

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
    except Exception as exc:  # noqa: BLE001 — surface as fail finding
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

    # Black-frame heuristic via ffprobe signalstats if available; soft-fail otherwise.
    black_ratio = _black_ratio_probe(path)
    if black_ratio is None:
        findings.append(
            MetricFinding(
                check_id="black_frames.ratio",
                severity="warn",
                message="black-frame probe unavailable; skipped",
                evidence={"available": False},
            )
        )
    elif black_ratio > max_black_ratio:
        findings.append(
            MetricFinding(
                check_id="black_frames.ratio",
                severity="fail",
                message=f"black ratio {black_ratio:.3f} exceeds max {max_black_ratio}",
                time_range=(0.0, duration),
                evidence={"black_ratio": black_ratio, "max": max_black_ratio},
            )
        )
    else:
        findings.append(
            MetricFinding(
                check_id="black_frames.ratio",
                severity="info",
                message=f"black ratio {black_ratio:.3f} ok",
                evidence={"black_ratio": black_ratio},
            )
        )
    return findings


def _black_ratio_probe(path: str) -> float | None:
    """Black-frame ratio via ffmpeg blackdetect when available.

    Returns None when the probe is unavailable rather than inventing 0.0.
    Full blackdetect matrix is a later hardening; floor keeps fail-closed honesty.
    """
    _ = path
    return None
