"""Policy is the sole authority for rescue repair dispositions."""

from __future__ import annotations

import pytest

from mcp_video.rescue.models import Finding, Metric, RepairType
from mcp_video.rescue.policy import SAFE_THRESHOLDS, evaluate_finding


def _executor(repair_type: str) -> str | None:
    return {
        "rotation": "ffmpeg.transpose",
        "audio_loudness": "ffmpeg.loudnorm",
        "audio_denoise": "ffmpeg.afftdn",
        "timeline_edit": None,
        "synthetic_content": None,
        "cloud_processing": "cloud.remote",
    }[repair_type]


def _finding(repair_type: str, confidence: float, available: bool) -> Finding:
    return Finding(
        id=f"{repair_type}:test",
        type=repair_type,
        summary="Measured candidate repair.",
        evidence=[
            Metric(
                name="test_metric",
                value=1.0 if available else None,
                unit="ratio",
                definition="Synthetic policy-fixture measurement.",
                available=available,
            )
        ],
        confidence=confidence,
        confidence_rationale="Policy fixture confidence.",
        expected_benefit="Exercise the policy matrix.",
        executor=_executor(repair_type),
        available=available,
    )


def _capabilities(available: bool) -> dict:
    return {
        "local_only": True,
        "ffmpeg": {"available": available},
        "whisper": {"available": available},
        "filters": {"loudnorm": available, "afftdn": available, "eq": available},
    }


@pytest.mark.parametrize(
    ("repair_type", "confidence", "available", "expected"),
    [
        ("rotation", 1.0, True, "safe_repair"),
        ("audio_loudness", 0.94, True, "safe_repair"),
        ("audio_denoise", 0.89, True, "recommendation"),
        ("timeline_edit", 1.0, True, "blocked"),
        ("synthetic_content", 1.0, True, "blocked"),
        ("cloud_processing", 1.0, True, "blocked"),
    ],
)
def test_policy_dispositions_are_repair_specific(repair_type, confidence, available, expected):
    repair = evaluate_finding(_finding(repair_type, confidence, available), _capabilities(available))
    assert repair.disposition.value == expected


def test_lowering_audio_threshold_cannot_weaken_rotation(monkeypatch):
    monkeypatch.setitem(SAFE_THRESHOLDS, RepairType.AUDIO_LOUDNESS, 0.50)

    repair = evaluate_finding(_finding("rotation", 0.99, True), _capabilities(True))

    assert repair.disposition.value == "recommendation"


def test_recommendations_are_not_promotable_without_an_explicit_allowlist():
    repair = evaluate_finding(_finding("audio_denoise", 1.0, True), _capabilities(True))

    assert repair.disposition.value == "recommendation"
    assert repair.promotable is False


def test_missing_local_executor_is_unavailable():
    repair = evaluate_finding(_finding("audio_loudness", 1.0, True), _capabilities(False))

    assert repair.disposition.value == "unavailable"
    assert repair.promotable is False
