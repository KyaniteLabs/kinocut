"""Move Google-style ``Args:`` docstring blocks into MCP parameter schemas.

FastMCP copies a tool's whole docstring into ``description`` and does not
parse its ``Args:`` section, so per-parameter help travels as one prose blob
that clients cannot attach to the parameter it documents. ``fold_args``
moves each entry into the matching ``inputSchema`` property (unless the
property already has its own description) and drops the block from the tool
description. When the block does not parse cleanly against the schema the
description is left untouched, so no parameter help is ever lost.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

_SECTION = re.compile(r"^(Args|Arguments|Parameters|Returns|Raises|Yields|Examples?|Notes?):\s*$")
_ENTRY = re.compile(r"^(\*{0,2}[A-Za-z_][A-Za-z0-9_]*)(?:\s*\([^)]*\))?:\s*(.*)$")


def _parse_args(lines: list[str]) -> dict[str, str] | None:
    entries: dict[str, list[str]] = {}
    current: str | None = None
    indent: int | None = None
    for line in lines:
        if not line.strip():
            continue
        width = len(line) - len(line.lstrip())
        if indent is None:
            indent = width
        match = _ENTRY.match(line.strip()) if width == indent else None
        if match:
            current = match.group(1).lstrip("*")
            if current in entries:
                return None
            entries[current] = [match.group(2)]
        elif current is not None and width > indent:
            entries[current].append(line.strip())
        else:
            return None
    return {name: " ".join(" ".join(parts).split()) for name, parts in entries.items()}


def fold_args(description: str | None, parameters: dict[str, Any]) -> str | None:
    """Return ``description`` without its Args block, updating ``parameters`` in place."""

    if not description:
        return description
    lines = inspect.cleandoc(description).splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() in ("Args:", "Arguments:", "Parameters:")), None)
    if start is None:
        return "\n".join(lines)
    end = next((i for i in range(start + 1, len(lines)) if _SECTION.match(lines[i])), len(lines))
    entries = _parse_args(lines[start + 1 : end])
    properties = parameters.get("properties") or {}
    if not entries or any(name not in properties for name in entries):
        return "\n".join(lines)
    for name, text in entries.items():
        if text and not properties[name].get("description"):
            properties[name]["description"] = text
    kept = lines[:start] + lines[end:]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)
