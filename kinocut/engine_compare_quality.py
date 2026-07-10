"""Quality comparison operation for the FFmpeg engine."""

from __future__ import annotations

import logging
import re
import subprocess

from .ffmpeg_helpers import _validate_input_path
from .engine_probe import probe
from .engine_runtime_utils import _ffmpeg
from .errors import ProcessingError
from .limits import DEFAULT_FFMPEG_TIMEOUT
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
            f"metrics must be one of {sorted(SUPPORTED_QUALITY_METRICS)}, got invalid values: {invalid}",
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

    for metric_lower in supported_metrics:
        try:
            stderr = _run_metric(original_path, distorted_path, metric_lower, target_w, target_h)
            _parse_metric(stderr, metric_lower, computed)
        except Exception as e:
            if isinstance(e, ProcessingError):
                raise
            logging.warning("Quality metric %s failed: %s", metric_lower, e)
            raise ProcessingError(
                _metric_command_label(original_path, distorted_path, metric_lower),
                1,
                str(e)[:500],
            ) from e

    return QualityMetricsResult(
        metrics=computed,
        overall_quality=_overall_quality(computed),
    )


def _run_metric(original_path: str, distorted_path: str, metric_lower: str, target_w: int, target_h: int) -> str:
    filter_str = f"[1:v]scale={target_w}:{target_h}[scaled];[0:v][scaled]{metric_lower}"
    cmd = [
        _ffmpeg(),
        "-i",
        original_path,
        "-i",
        distorted_path,
        "-lavfi",
        filter_str,
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
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(
            " ".join(cmd),
            -1,
            f"Quality metric '{metric_lower}' timed out after {DEFAULT_FFMPEG_TIMEOUT} seconds",
        ) from exc
    if proc.returncode != 0:
        raise ProcessingError(" ".join(cmd), proc.returncode, proc.stderr)
    return proc.stderr


def _parse_metric(stderr: str, metric_lower: str, computed: dict[str, float]) -> None:
    for line in stderr.split("\n"):
        if metric_lower == "psnr" and "average:" in line.lower():
            try:
                val_match = re.search(r"average:\s*([0-9.]+)", line, re.IGNORECASE)
                if val_match:
                    computed["psnr"] = float(val_match.group(1))
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


def _metric_command_label(original_path: str, distorted_path: str, metric_lower: str) -> str:
    return f"ffmpeg -i {original_path} -i {distorted_path} -lavfi {metric_lower}"
