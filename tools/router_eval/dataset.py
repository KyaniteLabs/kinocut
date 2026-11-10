"""Freeze-contract validation for the private JSONL dataset."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .catalog import Operation

REQUIRED_FIELDS = (
    "id",
    "request",
    "context",
    "gold_operation",
    "gold_family",
    "mutates_media",
    "source",
    "source_ref",
    "labeler",
    "notes",
)


class DatasetError(ValueError):
    """The set violates the frozen schema."""


def validate_item(item: Mapping[str, object], operations: Mapping[str, Operation], *, line: int) -> None:
    """Raise ``DatasetError`` when one JSONL object violates the contract."""

    missing = [field for field in REQUIRED_FIELDS if field not in item]
    if missing:
        raise DatasetError(f"line {line}: missing fields {missing}")
    extra = sorted(set(item) - set(REQUIRED_FIELDS))
    if extra:
        raise DatasetError(f"line {line}: unexpected fields {extra}")
    if not isinstance(item["id"], str) or not item["id"].strip():
        raise DatasetError(f"line {line}: id must be a non-empty string")
    if not isinstance(item["request"], str) or len(item["request"].strip()) < 8:
        raise DatasetError(f"line {line}: request must be a non-empty natural-language string")
    if item["context"] is not None and not isinstance(item["context"], dict):
        raise DatasetError(f"line {line}: context must be an object or null")
    gold = item["gold_operation"]
    if not isinstance(gold, str) or gold not in operations:
        raise DatasetError(f"line {line}: gold_operation {gold!r} is not in the pinned registry")
    if item["gold_family"] != operations[gold].family:
        raise DatasetError(
            f"line {line}: gold_family {item['gold_family']!r} does not match {operations[gold].family!r}"
        )
    if not isinstance(item["mutates_media"], bool):
        raise DatasetError(f"line {line}: mutates_media must be a boolean")
    for field in ("source", "source_ref", "labeler"):
        if not isinstance(item[field], str) or not item[field].strip():
            raise DatasetError(f"line {line}: {field} must be a non-empty string")
    if not isinstance(item["notes"], str):
        raise DatasetError(f"line {line}: notes must be a string")


def load_dataset(path: str | Path, operations: Mapping[str, Operation]) -> list[dict[str, object]]:
    """Load and validate every JSONL object; ids must be unique."""

    items: list[dict[str, object]] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                raise DatasetError(f"line {line_number}: blank line")
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as error:
                raise DatasetError(f"line {line_number}: invalid JSON: {error}") from error
            if not isinstance(item, dict):
                raise DatasetError(f"line {line_number}: top-level value must be an object")
            validate_item(item, operations, line=line_number)
            if item["id"] in seen:
                raise DatasetError(f"line {line_number}: duplicate id {item['id']!r}")
            seen.add(item["id"])
            items.append(item)
    if not items:
        raise DatasetError("dataset is empty")
    return items


def summarize_dataset(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Return the provenance/mix counts the protocol asks the runner to report."""

    families: dict[str, int] = {}
    sources: dict[str, int] = {}
    for item in items:
        family = str(item["gold_family"])
        source = str(item["source"])
        families[family] = families.get(family, 0) + 1
        sources[source] = sources.get(source, 0) + 1
    return {
        "count": len(items),
        "family_counts": dict(sorted(families.items())),
        "source_counts": dict(sorted(sources.items())),
        "mutates_media_true": sum(1 for item in items if item["mutates_media"] is True),
    }
