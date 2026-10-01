"""Vision QC third — graceful enhancement (P3.3)."""

from __future__ import annotations

import logging
import math
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_input_path
from kinocut.defaults import DEFAULT_VISION_MAX_FRAME_WIDTH, DEFAULT_VISION_SAMPLE_TIMES
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_VIDEO_DURATION, MAX_VISION_KEYFRAME_BYTES, MAX_VISION_SAMPLE_FRAMES

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
                        "-vf",
                        f"scale={DEFAULT_VISION_MAX_FRAME_WIDTH}:{DEFAULT_VISION_MAX_FRAME_WIDTH}:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "5",
                        str(out),
                    ]
                )
                if out.is_file() and 0 < out.stat().st_size <= MAX_VISION_KEYFRAME_BYTES:
                    samples.append(
                        {
                            "time": float(t),
                            "path": str(out.resolve()),
                            "artifact_directory": str(tmp.resolve()),
                            "bytes": out.stat().st_size,
                        }
                    )
                else:
                    samples.append({"time": float(t), "path": None, "error": "empty_or_oversized_frame"})
                    out.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Vision keyframe extraction failed: %s", type(exc).__name__)
                samples.append({"time": float(t), "path": None, "error": type(exc).__name__})
    except Exception as exc:
        logger.warning("Vision keyframe sampling incomplete: %s", type(exc).__name__)
    if not any(sample.get("path") for sample in samples):
        shutil.rmtree(tmp, ignore_errors=True)
    return samples


def _validated_sample_times(sample_times: list[float] | None) -> list[float]:
    times = list(DEFAULT_VISION_SAMPLE_TIMES) if sample_times is None else sample_times
    if not isinstance(times, (list, tuple)) or not 1 <= len(times) <= MAX_VISION_SAMPLE_FRAMES:
        raise MCPVideoError("Vision sample count is outside its bounds", error_type="validation_error")
    if any(
        isinstance(time, bool)
        or not isinstance(time, (int, float))
        or not 0 <= time <= MAX_VIDEO_DURATION
        or not math.isfinite(time)
        for time in times
    ):
        raise MCPVideoError(
            "Vision sample times must be finite nonnegative numbers within media limits", error_type="validation_error"
        )
    if len(set(times)) != len(times):
        raise MCPVideoError("Vision sample times must be unique", error_type="validation_error")
    return [float(time) for time in times]


def _semantic_result(keyframes: list[dict], complete: bool, package_installed: bool) -> dict[str, Any]:
    from .vision_provider import assess_keyframes, configured_vision_model

    result = {
        "vlm_available": False,
        "auto_scored": False,
        "assessment_status": "not_evaluated",
        "reason": "provider_executor_unavailable",
    }
    model = configured_vision_model()
    if model is None:
        return result
    result.update(vlm_available=True, model_id=model)
    if not complete:
        return {**result, "reason": "incomplete_keyframe_sampling"}
    try:
        assessment = assess_keyframes(model, keyframes)
    except Exception as exc:
        logger.warning("Vision provider assessment failed: %s", type(exc).__name__)
        return {**result, "reason": "provider_assessment_failed"}
    return {
        **result,
        "auto_scored": True,
        "assessment_status": "evaluated_sampled_frames",
        "reason": None,
        "semantic_assessment": assessment.model_dump(mode="json"),
    }


def _vision_findings(
    times, keyframes, sampled, complete, sampling_status, semantic, package_installed, required, blocked, verdict
):
    assessment = semantic.get("semantic_assessment")
    return [
        VisionFinding(
            check_id="vision.keyframe_sample",
            severity="info" if complete else "warn",
            message=f"Structural keyframe sample: {sampled}/{len(times)} frames extracted",
            keyframe_times=list(times),
            evidence={"keyframes": keyframes, "sampled": sampled, "sampling_status": sampling_status},
        ),
        VisionFinding(
            check_id="vision.vlm",
            severity="fail" if blocked else "warn" if verdict == "warn" else "info",
            message=assessment["summary"] if assessment else "Semantic vision QC was not evaluated.",
            keyframe_times=list(times),
            evidence={
                **semantic,
                "vlm_package_installed": package_installed,
                "require_vlm": required,
                "keyframes": keyframes,
            },
        ),
    ]


def run_vision_qc(
    input_path: str,
    *,
    sample_times: list[float] | None = None,
    require_vlm: bool = False,
) -> dict[str, Any]:
    """Prepare retained keyframes and optionally assess their semantic quality.

    Explicit KINOCUT_VISION_MODEL + ANTHROPIC_API_KEY configuration opts into one
    paid request. Sparse image assessment never grants whole-film acceptance.
    """
    path = _validate_input_path(input_path)
    times = _validated_sample_times(sample_times)
    if not isinstance(require_vlm, bool):
        raise MCPVideoError("require_vlm must be a boolean", error_type="validation_error")
    from .vision_provider import configured_vision_model

    configured_vision_model()  # Validate explicit configuration before retaining any keyframes.
    from kinocut.rescue.operations import _sha256

    source = Path(path)
    source_before = source.stat()
    source_sha256 = _sha256(source)
    package_installed = _vlm_package_installed()
    keyframes = _sample_keyframes(path, times)
    sampled = sum(1 for k in keyframes if k.get("path"))
    complete = sampled == len(times)
    sampling_status = "complete" if complete else "partial" if sampled else "unavailable"
    semantic = _semantic_result(keyframes, complete, package_installed)
    source_after = source.stat()
    identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    source_unchanged = all(getattr(source_before, key) == getattr(source_after, key) for key in identity_fields)
    if not source_unchanged:
        semantic = {
            "vlm_available": semantic["vlm_available"],
            "auto_scored": False,
            "assessment_status": "not_evaluated",
            "reason": "source_changed_during_assessment",
        }
    assessment = semantic.get("semantic_assessment")
    verdict = (
        assessment["verdict"]
        if assessment
        else "fail"
        if require_vlm
        else "not_evaluated"
        if complete
        else "inconclusive"
    )
    blocked = require_vlm and (not assessment or verdict in {"fail", "inconclusive"})

    findings = _vision_findings(
        times, keyframes, sampled, complete, sampling_status, semantic, package_installed, require_vlm, blocked, verdict
    )

    return {
        "artifact_kind": "vision_qc",
        "input_path": path,
        "source_sha256": source_sha256,
        "source_binding_status": "hashed_media_unchanged_during_assessment" if source_unchanged else "source_changed",
        **semantic,
        "vlm_package_installed": package_installed,
        "sampling_status": sampling_status,
        "blocked": blocked,
        "keyframe_count": sampled,
        "keyframe_directory": next(
            (item["artifact_directory"] for item in keyframes if item.get("artifact_directory")), None
        ),
        "keyframe_retention": "caller_owned_review_artifacts" if sampled else "no_retained_keyframes",
        "findings": [f.to_dict() for f in findings],
        "verdict": verdict,
        "assessment_scope": "sampled_frames_only; whole_film_and_artistic_acceptance_not_granted",
        "whole_film_acceptance": "not_granted",
    }
