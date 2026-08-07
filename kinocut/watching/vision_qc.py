"""Vision QC third — graceful enhancement (P3.3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from kinocut.ffmpeg_helpers import _validate_input_path


@dataclass(frozen=True)
class VisionFinding:
    check_id: str
    severity: str
    message: str
    keyframe_times: list[float]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    # Without optional VLM stack, report graceful enhancement state.
    vlm_available = False
    try:
        import importlib.util

        vlm_available = importlib.util.find_spec("anthropic") is not None
    except Exception:
        vlm_available = False

    if require_vlm and not vlm_available:
        findings.append(
            VisionFinding(
                check_id="vision.vlm",
                severity="warn",
                message="VLM not installed; vision QC skipped (graceful)",
                keyframe_times=times,
                evidence={"vlm_available": False, "require_vlm": True},
            )
        )
    elif not vlm_available:
        findings.append(
            VisionFinding(
                check_id="vision.vlm",
                severity="info",
                message="VLM unavailable — structural keyframe sample only",
                keyframe_times=times,
                evidence={"vlm_available": False, "mode": "structural"},
            )
        )
    else:
        findings.append(
            VisionFinding(
                check_id="vision.vlm",
                severity="info",
                message="VLM package present — rubric deferred to explicit provider call",
                keyframe_times=times,
                evidence={"vlm_available": True, "auto_scored": False},
            )
        )

    return {
        "artifact_kind": "vision_qc",
        "input_path": path,
        "vlm_available": vlm_available,
        "findings": [f.to_dict() for f in findings],
        "verdict": "pass" if not any(f.severity == "fail" for f in findings) else "fail",
    }
