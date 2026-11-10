"""Operation catalog for the router eval, assembled from the shipped registry."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

_SUMMARY_LIMIT = 160


def _summary(description: str) -> str:
    """Return a one-line prompt summary, bounded for a readable criteria block."""

    first_line = description.split("\n")[0].strip()
    if len(first_line) <= _SUMMARY_LIMIT:
        return first_line
    cut = first_line[:_SUMMARY_LIMIT].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{cut}..."


@dataclass(frozen=True)
class Operation:
    """One registry operation and the fields the router eval ranks over."""

    name: str
    family: str
    verb: str
    description: str
    summary: str


@lru_cache(maxsize=1)
def load_operations() -> tuple[Operation, ...]:
    """Return the complete family surface, sorted by name.

    ``discovery_catalog()`` is the same registry ``list_operations`` reads. We
    assemble the row fields here instead of invoking the decorated MCP tool so
    the eval stays callable without an MCP context and without loading every
    tool module's optional dependencies.
    """

    from kinocut.tool_families import FAMILY_OF_OPERATION, operation_verb
    from kinocut.tool_registry import discovery_catalog

    operations: list[Operation] = []
    for row in discovery_catalog():
        name = str(row["name"])
        if name == "search_tools" or name not in FAMILY_OF_OPERATION:
            continue
        description = str(row.get("description") or "").strip()
        operations.append(
            Operation(
                name=name,
                family=FAMILY_OF_OPERATION[name],
                verb=operation_verb(name),
                description=description,
                summary=_summary(description),
            )
        )
    operations.sort(key=lambda operation: operation.name)
    return tuple(operations)


@lru_cache(maxsize=1)
def operations_by_name() -> dict[str, Operation]:
    """Return the catalog indexed by operation name."""

    return {operation.name: operation for operation in load_operations()}
