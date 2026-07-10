"""Closed policy authority for local, content-preserving rescue."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import Disposition, Finding, Repair, RepairType

POLICY_ID = "local_content_preserving"
POLICY_VERSION = 1

SAFE_THRESHOLDS: dict[RepairType, float] = {
    RepairType.ROTATION: 1.0,
    RepairType.CONTAINER_TIMESTAMPS: 0.99,
    RepairType.METADATA: 0.99,
    RepairType.AUDIO_LOUDNESS: 0.94,
    RepairType.EXPOSURE: 0.95,
}
BLOCKED_TYPES = frozenset(
    {
        RepairType.TIMELINE_EDIT,
        RepairType.SYNTHETIC_CONTENT,
        RepairType.CLOUD_PROCESSING,
    }
)
EXECUTABLE_TYPES = frozenset(SAFE_THRESHOLDS)
PROMOTABLE_RECOMMENDATIONS: frozenset[RepairType] = frozenset()


def _executor_available(executor: str | None, capabilities: Mapping[str, Any]) -> bool:
    if not executor or capabilities.get("local_only") is not True:
        return False
    if executor.startswith("ffmpeg."):
        ffmpeg = capabilities.get("ffmpeg", {})
        if not isinstance(ffmpeg, Mapping) or ffmpeg.get("available") is not True:
            return False
        filter_name = executor.removeprefix("ffmpeg.")
        filters = capabilities.get("filters", {})
        if isinstance(filters, Mapping) and filter_name in filters:
            return filters[filter_name] is True
        return True
    if executor == "openai-whisper":
        whisper = capabilities.get("whisper", {})
        return isinstance(whisper, Mapping) and whisper.get("available") is True
    return False


def _repair(
    finding: Finding,
    disposition: Disposition,
    *,
    promotable: bool,
    reason: str | None = None,
) -> Repair:
    return Repair(
        id=finding.id,
        type=finding.type,
        disposition=disposition,
        confidence=finding.confidence,
        confidence_rationale=finding.confidence_rationale,
        evidence=finding.evidence,
        parameters=finding.parameters,
        expected_benefit=finding.expected_benefit,
        tradeoffs=finding.tradeoffs,
        executor=finding.executor,
        promotable=promotable,
        reason=reason,
    )


def evaluate_finding(finding: Finding, capabilities: Mapping[str, Any]) -> Repair:
    """Classify analyzer evidence under the immutable version 1 policy matrix."""

    if finding.type in BLOCKED_TYPES:
        return _repair(
            finding,
            Disposition.BLOCKED,
            promotable=False,
            reason="Blocked by local_content_preserving policy.",
        )
    if not finding.available or not _executor_available(finding.executor, capabilities):
        return _repair(
            finding,
            Disposition.UNAVAILABLE,
            promotable=False,
            reason="Required local executor or measurement is unavailable.",
        )

    threshold = SAFE_THRESHOLDS.get(finding.type)
    if threshold is not None and finding.confidence >= threshold and not finding.contraindications:
        return _repair(finding, Disposition.SAFE_REPAIR, promotable=True)

    promotable = finding.type in PROMOTABLE_RECOMMENDATIONS and finding.timeline_preserving
    return _repair(
        finding,
        Disposition.RECOMMENDATION,
        promotable=promotable,
        reason="This repair is recommendation-only in policy version 1.",
    )
