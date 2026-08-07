"""Review API: policy + run + decide (P3.1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from kinocut.errors import MCPVideoError
from kinocut.watching.metrics import MetricFinding, run_metric_qc

DecisionLiteral = Literal["accept", "reject", "revise"]


@dataclass
class ReviewPolicy:
    """Fail-closed review policy for a watching pass."""

    policy_id: str = "default"
    require_metric_floor: bool = True
    fail_on_severity: tuple[str, ...] = ("fail",)
    min_duration_seconds: float = 0.5
    max_black_ratio: float = 0.95
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fail_on_severity"] = list(self.fail_on_severity)
        return d


@dataclass
class ReviewRunResult:
    policy: ReviewPolicy
    input_path: str
    findings: list[MetricFinding] = field(default_factory=list)
    verdict: str = "pass"  # pass | fail
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": "review_run",
            "policy": self.policy.to_dict(),
            "input_path": self.input_path,
            "findings": [f.to_dict() for f in self.findings],
            "verdict": self.verdict,
            "blocked": self.blocked,
        }


@dataclass(frozen=True)
class ReviewDecision:
    decision: DecisionLiteral
    reason: str
    review_run: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": "review_decision",
            "decision": self.decision,
            "reason": self.reason,
            "review_run": self.review_run,
        }


def run_review(
    input_path: str,
    policy: ReviewPolicy | None = None,
) -> ReviewRunResult:
    """Execute offline metric floor against policy."""
    pol = policy or ReviewPolicy()
    findings: list[MetricFinding] = []
    if pol.require_metric_floor:
        findings = run_metric_qc(
            input_path,
            min_duration_seconds=pol.min_duration_seconds,
            max_black_ratio=pol.max_black_ratio,
        )
    fail_severities = set(pol.fail_on_severity)
    blocked = any(f.severity in fail_severities for f in findings)
    return ReviewRunResult(
        policy=pol,
        input_path=input_path,
        findings=findings,
        verdict="fail" if blocked else "pass",
        blocked=blocked,
    )


def decide_review(
    review_run: dict[str, Any],
    decision: str,
    reason: str = "",
) -> ReviewDecision:
    """Record human decision on a review_run artifact (no silent override of fails)."""
    d = (decision or "").strip().lower()
    if d not in {"accept", "reject", "revise"}:
        raise MCPVideoError(
            "decision must be accept|reject|revise",
            error_type="validation_error",
            code="invalid_review_decision",
        )
    # Allow accept of a failed review only with explicit human-override reason.
    if (
        d == "accept"
        and review_run.get("blocked")
        and review_run.get("verdict") == "fail"
        and not (reason or "").strip()
    ):
        raise MCPVideoError(
            "accepting a failed review_run requires a non-empty reason",
            error_type="validation_error",
            code="accept_requires_reason",
        )
    return ReviewDecision(decision=d, reason=reason or "", review_run=review_run)  # type: ignore[arg-type]
