"""Generative policy and spend planning metadata (P4.1); no adapter exists."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
import math
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
    executable: bool = False
    paid_path: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_kind": "generative_plan", **asdict(self)}


def _normalize_money(value: Any, *, field_name: str, code: str) -> float:
    if isinstance(value, bool):
        raise MCPVideoError(
            f"{field_name} must be a finite nonnegative number",
            error_type="validation_error",
            code=code,
        )
    try:
        amount = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise MCPVideoError(
            f"{field_name} must be a finite nonnegative number",
            error_type="validation_error",
            code=code,
        ) from exc
    if not math.isfinite(amount) or amount < 0:
        raise MCPVideoError(
            f"{field_name} must be a finite nonnegative number",
            error_type="validation_error",
            code=code,
        )
    return amount


def plan_generative_last_mile(
    prompt: str,
    *,
    provider: str = "local",
    model: str | None = None,
    max_spend_usd: float = 0.0,
    estimated_spend_usd: float = 0.0,
    params: dict[str, Any] | None = None,
) -> GenerativePlan:
    """Return policy/spend metadata; no generation adapter exists."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise MCPVideoError("prompt required", error_type="validation_error", code="prompt_required")
    cap = _normalize_money(max_spend_usd, field_name="max_spend_usd", code="bad_spend_cap")
    estimate = _normalize_money(
        estimated_spend_usd,
        field_name="estimated_spend_usd",
        code="bad_spend_estimate",
    )
    if not isinstance(provider, str):
        raise MCPVideoError("provider must be a string", error_type="validation_error", code="invalid_provider")
    if params is not None and not isinstance(params, Mapping):
        raise MCPVideoError("params must be a mapping", error_type="validation_error", code="invalid_params")
    prov = (provider or "local").strip().lower()
    local_only = prov in {"local", "none", "offline"}
    if local_only:
        return GenerativePlan(
            provider=prov,
            model=model or "local-open-weights",
            prompt=prompt,
            max_spend_usd=cap,
            local_only=True,
            estimated_spend_usd=0.0,
            allowed=True,
            reason="local policy path is eligible; no generation adapter exists",
            params=dict(params or {}),
            executable=False,
            paid_path=False,
        )
    allowed = estimate <= cap
    # Paid paths require an explicit positive cap — zero cap always denies.
    if cap <= 0:
        allowed = False
        reason = "paid path denied: max_spend_usd must be > 0 for non-local providers"
    elif allowed:
        reason = "policy and spend cap are eligible; no generation adapter exists"
    else:
        reason = f"estimated ${estimate:.4f} exceeds cap ${cap:.4f}"
    return GenerativePlan(
        provider=prov,
        model=model,
        prompt=prompt,
        max_spend_usd=cap,
        local_only=False,
        estimated_spend_usd=estimate,
        allowed=allowed,
        reason=reason,
        params=dict(params or {}),
        executable=False,
        paid_path=True,
    )


def assert_generative_executable(plan: GenerativePlan | dict[str, Any]) -> dict[str, Any]:
    """Validate eligibility, then fail closed because no generation adapter exists."""
    if isinstance(plan, GenerativePlan):
        data = plan.to_dict()
    elif isinstance(plan, dict):
        data = dict(plan)
    else:
        raise MCPVideoError(
            "generative plan must be an object",
            error_type="validation_error",
            code="invalid_generative_plan",
        )
    cap = _normalize_money(data.get("max_spend_usd", 0.0), field_name="max_spend_usd", code="bad_spend_cap")
    estimate = _normalize_money(
        data.get("estimated_spend_usd", 0.0),
        field_name="estimated_spend_usd",
        code="bad_spend_estimate",
    )
    provider_value = data.get("provider", "local")
    if not isinstance(provider_value, str):
        raise MCPVideoError("provider must be a string", error_type="validation_error", code="invalid_provider")
    provider = (provider_value or "local").strip().lower()
    local_only = provider in {"local", "none", "offline"}
    if not local_only and (cap <= 0 or estimate > cap):
        raise MCPVideoError(
            "generative path not executable under the spend policy",
            error_type="validation_error",
            code="generative_not_executable",
        )
    raise MCPVideoError(
        "generative policy is eligible, but no generation adapter exists",
        error_type="dependency_error",
        code="generative_backend_unavailable",
    )
