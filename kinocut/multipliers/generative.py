"""Provider-agnostic generative last-mile adapter with spend caps (P4.1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from kinocut.errors import MCPVideoError


@dataclass
class GenerativePlan:
    provider: str
    model: str | None
    prompt: str
    max_spend_usd: float
    local_only: bool
    estimated_spend_usd: float
    allowed: bool
    reason: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_kind": "generative_plan", **asdict(self)}


def plan_generative_last_mile(
    prompt: str,
    *,
    provider: str = "local",
    model: str | None = None,
    max_spend_usd: float = 0.0,
    estimated_spend_usd: float = 0.0,
    params: dict[str, Any] | None = None,
) -> GenerativePlan:
    """Plan only — never auto-call paid providers when cap is zero."""
    if not (prompt or "").strip():
        raise MCPVideoError("prompt required", error_type="validation_error", code="prompt_required")
    if max_spend_usd < 0:
        raise MCPVideoError("max_spend_usd must be >= 0", error_type="validation_error", code="bad_spend_cap")
    prov = (provider or "local").strip().lower()
    local_only = prov in {"local", "none", "offline"}
    if local_only:
        return GenerativePlan(
            provider=prov,
            model=model or "local-open-weights",
            prompt=prompt,
            max_spend_usd=max_spend_usd,
            local_only=True,
            estimated_spend_usd=0.0,
            allowed=True,
            reason="local/open-weights path; no cloud spend",
            params=dict(params or {}),
        )
    allowed = estimated_spend_usd <= max_spend_usd
    reason = (
        "within spend cap"
        if allowed
        else f"estimated ${estimated_spend_usd:.4f} exceeds cap ${max_spend_usd:.4f}"
    )
    return GenerativePlan(
        provider=prov,
        model=model,
        prompt=prompt,
        max_spend_usd=max_spend_usd,
        local_only=False,
        estimated_spend_usd=estimated_spend_usd,
        allowed=allowed,
        reason=reason,
        params=dict(params or {}),
    )
