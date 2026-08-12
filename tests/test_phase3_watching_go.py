"""Phase 3 Watching formal GO suite — metric floor, review, mutations, vision."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.watching import (
    ReviewPolicy,
    apply_mutations_silently,
    decide_review,
    propose_mutations_from_findings,
    run_metric_qc,
    run_narrative_qc,
    run_review,
    run_vision_qc,
)


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _make_short_clip(path: Path, *, seconds: float = 0.2, color: str = "black") -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:d={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg required")
def test_metric_floor_fails_short_duration(tmp_path: Path) -> None:
    clip = tmp_path / "short.mp4"
    _make_short_clip(clip, seconds=0.2)
    findings = run_metric_qc(str(clip), min_duration_seconds=1.0)
    fails = [f for f in findings if f.severity == "fail" and f.check_id == "duration.min"]
    assert fails, findings


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg required")
def test_metric_floor_unavailable_probe_not_invented(tmp_path: Path) -> None:
    # silent video has no audio → LUFS probe unavailable
    clip = tmp_path / "silent.mp4"
    _make_short_clip(clip, seconds=1.0, color="blue")
    findings = run_metric_qc(str(clip), min_duration_seconds=0.5)
    lufs = next(f for f in findings if f.check_id == "audio.lufs")
    assert lufs.severity == "warn"
    assert lufs.evidence is not None
    assert lufs.evidence.get("available") is False
    assert "integrated_lufs" not in (lufs.evidence or {})


def test_metric_floor_on_golden_fixture(sample_video: str) -> None:
    findings = run_metric_qc(sample_video, min_duration_seconds=0.1)
    assert findings
    assert not any(f.severity == "fail" for f in findings if f.check_id == "duration.min")


def test_review_run_and_decide_on_media(sample_video: str) -> None:
    result = run_review(sample_video, ReviewPolicy())
    payload = result.to_dict()
    assert payload["artifact_kind"] == "review_run"
    assert "findings" in payload
    # accept fail requires reason
    if payload.get("verdict") == "fail" or payload.get("blocked"):
        with pytest.raises(MCPVideoError):
            decide_review(payload, "accept", reason="")
        decided = decide_review(payload, "accept", reason="operator override")
    else:
        decided = decide_review(payload, "accept", reason="ok")
    assert decided.to_dict()["decision"] in {"accept", "reject", "revise"}


def test_mutations_are_human_only_and_silent_apply_forbidden() -> None:
    from kinocut.watching import MetricFinding

    findings = [
        MetricFinding("duration.min", "fail", "too short", (0.0, 0.1)),
        MetricFinding("ok", "info", "fine"),
    ]
    props = propose_mutations_from_findings(findings)
    assert props
    assert all(p.apply_policy == "human_review_required" for p in props)
    with pytest.raises(MCPVideoError) as exc:
        apply_mutations_silently(props)
    assert exc.value.code == "human_apply_required"


def test_vision_narrative_graceful_without_vlm(sample_video: str) -> None:
    vision = run_vision_qc(sample_video, require_vlm=False)
    assert isinstance(vision, dict)
    assert "findings" in vision or vision.get("artifact_kind")
    # hard-require VLM must not crash product path when unavailable
    vision_req = run_vision_qc(sample_video, require_vlm=True)
    assert isinstance(vision_req, dict)
    findings = vision_req.get("findings") or []
    # when VLM missing, expect graceful warn not hard product failure
    if findings:
        assert all(f.get("severity") != "error" for f in findings if isinstance(f, dict))
    narrative = run_narrative_qc(sample_video)
    assert isinstance(narrative, dict)
