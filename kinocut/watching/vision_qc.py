"""Vision QC third — graceful enhancement (P3.3)."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_input_path
from kinocut.defaults import DEFAULT_VISION_SAMPLE_TIMES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisionFinding:
    check_id: str
    severity: str
    message: str
    keyframe_times: list[float]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _vlm_package_installed() -> bool:
    """Probe the optional SDK only; package presence is not an executable scorer."""
    try:
        import importlib.util

        return importlib.util.find_spec("anthropic") is not None
    except Exception as exc:
        logger.warning("Optional vision SDK probe failed: %s", type(exc).__name__)
        return False


def _sample_keyframes(path: str, times: list[float]) -> list[dict[str, Any]]:
    """Extract structural keyframe JPEGs when FFmpeg is available."""
    samples: list[dict[str, Any]] = []
    tmp = Path(tempfile.mkdtemp(prefix="kinocut_vision_"))
    try:
        for i, t in enumerate(times):
            out = tmp / f"kf_{i:02d}.jpg"
            try:
                _run_ffmpeg(
                    [
                        "-ss",
                        f"{float(t):.3f}",
                        "-i",
                        path,
                        "-frames:v",
                        "1",
                        "-q:v",
                        "5",
                        str(out),
                    ]
                )
                if out.is_file() and out.stat().st_size > 0:
                    samples.append(
                        {
                            "time": float(t),
                            "path": str(out.resolve()),
                            "bytes": out.stat().st_size,
                        }
                    )
                else:
                    samples.append({"time": float(t), "path": None, "error": "empty_frame"})
            except Exception as exc:
                logger.warning("Vision keyframe extraction failed: %s", type(exc).__name__)
                samples.append({"time": float(t), "path": None, "error": type(exc).__name__})
    except Exception as exc:
        logger.warning("Vision keyframe sampling incomplete: %s", type(exc).__name__)
        return samples
    return samples


def run_vision_qc(
    input_path: str,
    *,
    sample_times: list[float] | None = None,
    require_vlm: bool = False,
) -> dict[str, Any]:
    """Prepare retained keyframes; semantic vision quality is not evaluated.

    No provider executor is implemented here. Optional inspection remains usable
    without one, but cannot pass semantic QC; an explicitly required VLM fails
    closed as a structured result. Extracted paths stay available for host review.
    """
    path = _validate_input_path(input_path)
    times = sample_times or list(DEFAULT_VISION_SAMPLE_TIMES)
    findings: list[VisionFinding] = []
    package_installed = _vlm_package_installed()
    keyframes = _sample_keyframes(path, times)
    sampled = sum(1 for k in keyframes if k.get("path"))
    complete = sampled == len(times)
    sampling_status = "complete" if complete else "partial" if sampled else "unavailable"

    findings.append(
        VisionFinding(
            check_id="vision.keyframe_sample",
            severity="info" if complete else "warn",
            message=f"Structural keyframe sample: {sampled}/{len(times)} frames extracted",
            keyframe_times=list(times),
            evidence={"keyframes": keyframes, "sampled": sampled, "sampling_status": sampling_status},
        )
    )

    findings.append(
        VisionFinding(
            check_id="vision.vlm",
            severity="fail" if require_vlm else "info",
            message="No executable VLM scorer; semantic vision QC was not evaluated.",
            keyframe_times=list(times),
            evidence={
                "vlm_available": False,
                "vlm_package_installed": package_installed,
                "require_vlm": require_vlm,
                "auto_scored": False,
                "assessment_status": "not_evaluated",
                "reason": "provider_executor_unavailable",
                "keyframes": keyframes,
            },
        )
    )

    return {
        "artifact_kind": "vision_qc",
        "input_path": path,
        "vlm_available": False,
        "vlm_package_installed": package_installed,
        "auto_scored": False,
        "assessment_status": "not_evaluated",
        "sampling_status": sampling_status,
        "blocked": require_vlm,
        "keyframe_count": sampled,
        "findings": [f.to_dict() for f in findings],
        "verdict": "fail" if require_vlm else "not_evaluated" if complete else "inconclusive",
    }
