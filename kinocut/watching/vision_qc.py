"""Vision QC third — graceful enhancement (P3.3)."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_input_path


@dataclass(frozen=True)
class VisionFinding:
    check_id: str
    severity: str
    message: str
    keyframe_times: list[float]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _vlm_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("anthropic") is not None
    except Exception:
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
                samples.append({"time": float(t), "path": None, "error": type(exc).__name__})
    except Exception:
        return samples
    return samples


def run_vision_qc(
    input_path: str,
    *,
    sample_times: list[float] | None = None,
    require_vlm: bool = False,
) -> dict[str, Any]:
    """Sample keyframe rubric. VLM is optional; never hard-require for pass."""
    path = _validate_input_path(input_path)
    times = sample_times or [0.5, 1.0, 2.0]
    findings: list[VisionFinding] = []
    vlm_available = _vlm_available()
    keyframes = _sample_keyframes(path, times)
    sampled = sum(1 for k in keyframes if k.get("path"))

    findings.append(
        VisionFinding(
            check_id="vision.keyframe_sample",
            severity="info",
            message=f"Structural keyframe sample: {sampled}/{len(times)} frames extracted",
            keyframe_times=list(times),
            evidence={"keyframes": keyframes, "sampled": sampled},
        )
    )

    if require_vlm and not vlm_available:
        findings.append(
            VisionFinding(
                check_id="vision.vlm",
                severity="warn",
                message="VLM not installed; vision QC skipped (graceful)",
                keyframe_times=list(times),
                evidence={"vlm_available": False, "require_vlm": True},
            )
        )
    elif not vlm_available:
        findings.append(
            VisionFinding(
                check_id="vision.vlm",
                severity="info",
                message="VLM unavailable — structural keyframe sample only",
                keyframe_times=list(times),
                evidence={"vlm_available": False, "mode": "structural"},
            )
        )
    else:
        # Package present: still no auto-score without explicit provider credentials.
        # Evidence includes keyframe paths so a host can call a VLM out-of-band.
        findings.append(
            VisionFinding(
                check_id="vision.vlm",
                severity="info",
                message="VLM package present — rubric deferred to explicit provider call; keyframes ready",
                keyframe_times=list(times),
                evidence={
                    "vlm_available": True,
                    "auto_scored": False,
                    "keyframes": keyframes,
                    "next_action": "call_provider_with_keyframe_paths",
                },
            )
        )

    return {
        "artifact_kind": "vision_qc",
        "input_path": path,
        "vlm_available": vlm_available,
        "keyframe_count": sampled,
        "findings": [f.to_dict() for f in findings],
        "verdict": "pass" if not any(f.severity == "fail" for f in findings) else "fail",
    }
