"""Privacy-safe hash inputs for authorization audit events."""

from __future__ import annotations

from typing import Protocol


class _AuthorizationContext(Protocol):
    operation: str
    project_id: str | None
    character_id: str | None
    provider_class: str | None
    territory: str | None


def context_hash_input(context: _AuthorizationContext) -> dict[str, str | None]:
    """Return complete context solely as input to the ledger detail hash."""

    return {
        "operation": context.operation,
        "project_id": context.project_id,
        "character_id": context.character_id,
        "provider_class": context.provider_class,
        "territory": context.territory,
    }
