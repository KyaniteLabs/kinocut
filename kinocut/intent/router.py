"""video_intent router: map a verb + params to a plan (no silent media mutation)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from kinocut.errors import MCPVideoError

from .verbs import INTENT_VERBS


@dataclass(frozen=True)
class IntentPlan:
    """Deterministic routing plan for one intent verb."""

    verb: str
    summary: str
    async_preferred: bool
    mutates_media: bool
    compat_tools: tuple[str, ...]
    params: dict[str, Any] = field(default_factory=dict)
    next_action: str = "call_compat_tool"
    notes: str | None = None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_intent_verbs() -> list[dict[str, Any]]:
    """Return public verb catalog for agents."""
    out: list[dict[str, Any]] = []
    for name, meta in sorted(INTENT_VERBS.items()):
        out.append(
            {
                "verb": name,
                "summary": meta["summary"],
                "async_preferred": bool(meta.get("async_preferred")),
                "mutates_media": bool(meta.get("mutates_media")),
                "compat_tools": list(meta.get("compat_tools") or ()),
            }
        )
    return out


def route_intent(verb: str, params: dict[str, Any] | None = None) -> IntentPlan:
    """Route one semantic verb to a plan. Does not execute media ops."""
    name = (verb or "").strip().lower().replace("-", "_")
    if name not in INTENT_VERBS:
        known = ", ".join(sorted(INTENT_VERBS))
        raise MCPVideoError(
            f"unknown intent verb {verb!r}; known: {known}",
            error_type="validation_error",
            code="unknown_intent_verb",
        )
    meta = INTENT_VERBS[name]
    merged = dict(meta.get("params") or {})
    if params:
        merged.update(params)
    # inject_broll never auto-applies; force proposal path.
    next_action = "call_compat_tool"
    blocked = None
    if name == "inject_broll":
        next_action = "propose_only"
        notes = "Returns proposals only; human must accept before any insert."
    else:
        notes = meta.get("notes")
    return IntentPlan(
        verb=name,
        summary=str(meta["summary"]),
        async_preferred=bool(meta.get("async_preferred")),
        mutates_media=bool(meta.get("mutates_media")),
        compat_tools=tuple(meta.get("compat_tools") or ()),
        params=merged,
        next_action=next_action,
        notes=notes,
        blocked_reason=blocked,
    )
