"""Findings → typed proposed mutations (P3.5) — never silent apply."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from kinocut.watching.metrics import MetricFinding


@dataclass(frozen=True)
class ProposedMutation:
    mutation_id: str
    kind: str
    time_range: tuple[float, float] | None
    summary: str
    source_finding_ids: tuple[str, ...]
    params: dict[str, Any]
    apply_policy: str = "human_review_required"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.time_range is not None:
            d["time_range"] = {"start": self.time_range[0], "end": self.time_range[1]}
        d["source_finding_ids"] = list(self.source_finding_ids)
        return d


def propose_mutations_from_findings(
    findings: Sequence[MetricFinding | dict[str, Any]],
) -> list[ProposedMutation]:
    """Map QC findings to typed edit proposals (review-only)."""
    out: list[ProposedMutation] = []
    for idx, raw in enumerate(findings, start=1):
        if isinstance(raw, MetricFinding):
            fid = raw.check_id
            severity = raw.severity
            message = raw.message
            tr = raw.time_range
        else:
            fid = str(raw.get("check_id") or f"finding-{idx}")
            severity = str(raw.get("severity") or "info")
            message = str(raw.get("message") or "")
            tr_raw = raw.get("time_range")
            if isinstance(tr_raw, dict):
                tr = (float(tr_raw["start"]), float(tr_raw["end"]))
            else:
                tr = None
        if severity not in {"fail", "warn"}:
            continue
        if fid.startswith("duration"):
            kind = "extend_or_reject"
            summary = "Duration below policy — reject or source longer media"
        elif "black" in fid:
            kind = "trim_black"
            summary = "High black ratio — propose trim of leading/trailing black"
        else:
            kind = "manual_review"
            summary = message or f"Review finding {fid}"
        out.append(
            ProposedMutation(
                mutation_id=f"mut-{idx:03d}",
                kind=kind,
                time_range=tr,
                summary=summary,
                source_finding_ids=(fid,),
                params={"severity": severity},
            )
        )
    return out
