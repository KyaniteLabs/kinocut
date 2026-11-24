"""Quality comparison operation for the FFmpeg engine."""

from __future__ import annotations

import re

from .ffmpeg_helpers import _run_command, _validate_input_path
from .engine_probe import probe
from .engine_runtime_utils import _ffmpeg
from .errors import ProcessingError
from .models import QualityMetricsResult

SUPPORTED_QUALITY_METRICS = {"psnr", "ssim"}


def _validate_quality_metrics(metrics: list[str] | None) -> list[str]:
    requested_metrics = metrics or ["psnr", "ssim"]
    resolved = [metric.lower() for metric in requested_metrics]
    invalid = [metric for metric in resolved if metric not in SUPPORTED_QUALITY_METRICS]
    if invalid:
        raise ProcessingError(
            "compare_quality",
            1,
            f"metrics must be one of {sorted(SUPPORTED_QUALITY_METRICS)}",
            reason=f"metrics must be one of {sorted(SUPPORTED_QUALITY_METRICS)}",
        )
    return resolved


def compare_quality(
    original_path: str,
    distorted_path: str,
    metrics: list[str] | None = None,
) -> QualityMetricsResult:
    """Compare video quality between original and distorted versions.

    Args:
        original_path: Path to the original/reference video.
        distorted_path: Path to the distorted/processed video.
        metrics: List of metrics to compute (default: ["psnr", "ssim"]).
    """
    supported_metrics = _validate_quality_metrics(metrics)
    original_path = _validate_input_path(original_path)
    distorted_path = _validate_input_path(distorted_path)

    computed: dict[str, float] = {}
    orig_info = probe(original_path)
    target_w = orig_info.width
    target_h = orig_info.height

    stderr = _run_metrics(original_path, distorted_path, supported_metrics, target_w, target_h)
    for metric in supported_metrics:
        _parse_metric(stderr, metric, computed)

    return QualityMetricsResult(
        metrics=computed,
        overall_quality=_overall_quality(computed),
    )


def _run_metrics(original_path: str, distorted_path: str, metrics: list[str], target_w: int, target_h: int) -> str:
    scale = f"[1:v]scale={target_w}:{target_h}"
    if len(set(metrics)) == 1:
        graph = f"{scale}[scaled];[0:v][scaled]{metrics[0]}[out]"
    else:
        graph = f"{scale},split[d1][d2];[0:v]split[r1][r2];[r1][d1]psnr[out];[r2][d2]ssim,nullsink"
    cmd = [
        _ffmpeg(),
        "-i",
        original_path,
        "-i",
        distorted_path,
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-f",
        "null",
        "-",
    ]
    return _run_command(cmd).stderr


def _parse_metric(stderr: str, metric_lower: str, computed: dict[str, float]) -> None:
    for line in stderr.split("\n"):
        if metric_lower == "psnr" and "average:" in line.lower():
            try:
                val_match = re.search(r"average:\s*(inf|[0-9.]+)", line, re.IGNORECASE)
                if val_match:
                    raw_val = val_match.group(1).lower()
                    # Identical frames emit PSNR=inf; report JSON-safe 100.0 dB ceiling.
                    computed["psnr"] = 100.0 if raw_val == "inf" else float(raw_val)
            except (ValueError, IndexError):
                continue
        elif metric_lower == "ssim" and "All:" in line:
            try:
                val_match = re.search(r"All[:\s]+([0-9.]+)", line)
                if val_match:
                    computed["ssim"] = float(val_match.group(1))
            except (ValueError, IndexError):
                continue


def _overall_quality(computed: dict[str, float]) -> str:
    if "ssim" in computed:
        ssim_val = computed["ssim"]
        if ssim_val >= 0.95:
            return "high"
        if ssim_val >= 0.80:
            return "medium"
        return "low"
    if "psnr" in computed:
        psnr_val = computed["psnr"]
        if psnr_val >= 40:
            return "high"
        if psnr_val >= 30:
            return "medium"
        return "low"
    return "unknown"
