"""Transcript-keyed b-roll proposals (P2.8) — never silent inserts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from collections.abc import Sequence

from kinocut.errors import MCPVideoError


@dataclass(frozen=True)
class BrollProposal:
    """One human-reviewable insert proposal anchored to a time range."""

    proposal_id: str
    time_range: tuple[float, float]
    keyword: str
    reason: str
    suggested_asset_query: str
    confidence: float
    accepted: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["time_range"] = {"start": self.time_range[0], "end": self.time_range[1]}
        d["status"] = "proposed"
        d["apply_policy"] = "human_review_required"
        return d


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")


def propose_broll(
    segments: Sequence[dict[str, Any]],
    *,
    max_proposals: int = 8,
    min_span_seconds: float = 0.8,
    keyword_allowlist: Sequence[str] | None = None,
) -> list[BrollProposal]:
    """Build proposals from transcript segments.

    Each segment is ``{start, end, text}``. Proposals never mutate media and
    never set ``accepted=True``. Phase-2 anchors are time_range only (no node_id).
    """
    if max_proposals < 1:
        raise MCPVideoError(
            "max_proposals must be >= 1",
            error_type="validation_error",
            code="invalid_max_proposals",
        )
    allow = {k.lower() for k in (keyword_allowlist or ())}
    proposals: list[BrollProposal] = []
    seen: set[str] = set()
    for idx, seg in enumerate(segments):
        try:
            start = float(seg["start"])
            end = float(seg["end"])
            text = str(seg.get("text") or "")
        except (KeyError, TypeError, ValueError) as exc:
            raise MCPVideoError(
                f"segment {idx} must include start, end, text",
                error_type="validation_error",
                code="invalid_broll_segment",
            ) from exc
        if end - start < min_span_seconds:
            continue
        for word in _WORD.findall(text):
            key = word.lower()
            if allow and key not in allow:
                continue
            # Prefer concrete nouns-ish tokens (simple heuristic): skip tiny fillers.
            if key in {"the", "and", "for", "you", "that", "this", "with", "from"}:
                continue
            dedupe = f"{key}:{start:.2f}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            proposals.append(
                BrollProposal(
                    proposal_id=f"broll-{len(proposals)+1:03d}",
                    time_range=(start, end),
                    keyword=key,
                    reason=f"Transcript mentions {key!r} in [{start:.2f},{end:.2f}]",
                    suggested_asset_query=key,
                    confidence=min(0.95, 0.55 + 0.05 * len(key)),
                )
            )
            if len(proposals) >= max_proposals:
                return proposals
    return proposals
