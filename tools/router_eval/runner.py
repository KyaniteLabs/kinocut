"""Score one dataset with the rules baselines and optional model treatment."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from statistics import median
from typing import Any, cast

from .catalog import Operation
from .client import AskError, ask, parse_choice
from .dataset import summarize_dataset
from .fake_endpoint import serve_fake
from .prompt import build_body
from .rules import r1_rank, r2_rank

QUESTION_ID = "operation"


def _p50(values: Sequence[float]) -> float | None:
    return round(median(values), 3) if values else None


def evaluate_set(
    items: Sequence[Mapping[str, object]],
    operations: Mapping[str, Operation],
    *,
    endpoint: str | None = None,
    fake_endpoint: bool = False,
    timeout: float = 10.0,
    model: str = "d1-2b",
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    """Run R1 and R2 on every item, plus the endpoint treatment when enabled.

    ``fake_endpoint`` starts the in-process CI fake and cannot be combined with
    an explicit ``endpoint``. When neither is set the run is rules-only.
    """

    if endpoint and fake_endpoint:
        raise ValueError("pass an endpoint or fake_endpoint, not both")
    context = serve_fake() if fake_endpoint else nullcontext(endpoint)
    records: list[dict[str, Any]] = []
    with context as active_endpoint:
        for item in items:
            request = str(item["request"])
            started = time.perf_counter()
            r1 = r1_rank(request)
            r1_ms = (time.perf_counter() - started) * 1000.0
            started = time.perf_counter()
            r2 = r2_rank(request, k=5)
            r2_ms = (time.perf_counter() - started) * 1000.0
            candidates = [name for name, _ in r2]
            record: dict[str, Any] = {
                "id": item["id"],
                "gold_operation": item["gold_operation"],
                "gold_family": item["gold_family"],
                "mutates_media": item["mutates_media"],
                "r1_top1": r1[0] if r1 else None,
                "r1_top5": r1[:5],
                "r1_ms": round(r1_ms, 3),
                "r2_top1": candidates[0],
                "r2_top5": candidates,
                "r2_ms": round(r2_ms, 3),
                "candidates": candidates,
                "picked": None,
                "probabilities": {},
                "wall_ms": None,
                "degraded": None,
                "mode": "treatment" if active_endpoint else "rules",
            }
            if active_endpoint:
                body = build_body(
                    model=model,
                    request=request,
                    context=item.get("context"),
                    candidates=candidates,
                    operations=operations,
                )
                started = time.perf_counter()
                try:
                    reply, wall_ms = ask(active_endpoint, body, timeout=timeout)
                    choice, probabilities = parse_choice(reply, candidates)
                    if choice == "unsure":
                        record["picked"] = candidates[0]
                        record["degraded"] = True
                    else:
                        record["picked"] = choice
                        record["degraded"] = False
                    record["probabilities"] = probabilities
                    record["wall_ms"] = round(wall_ms, 3)
                except AskError:
                    record["picked"] = candidates[0]
                    record["degraded"] = True
                    record["wall_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            records.append(record)

    gold = [str(item["gold_operation"]) for item in items]

    def top1(key: str) -> int:
        return sum(1 for record, target in zip(records, gold, strict=True) if record[key] == target)

    def oracle5(key: str) -> int:
        return sum(1 for record, target in zip(records, gold, strict=True) if target in cast(list[str], record[key]))

    r1_top1, r1_top5 = top1("r1_top1"), oracle5("r1_top5")
    r2_top1, r2_top5 = top1("r2_top1"), oracle5("r2_top5")
    summary: dict[str, object] = {
        "count": len(records),
        "mode": records[0]["mode"] if records else "rules",
        "dataset": summarize_dataset(items),
        "r1": {
            "top1": r1_top1,
            "top1_accuracy": round(r1_top1 / len(records), 4),
            "oracle_at_5": r1_top5,
            "p50_ms": _p50([cast(float, record["r1_ms"]) for record in records]),
        },
        "r2": {
            "top1": r2_top1,
            "top1_accuracy": round(r2_top1 / len(records), 4),
            "oracle_at_5": r2_top5,
            "p50_ms": _p50([cast(float, record["r2_ms"]) for record in records]),
        },
        "treatment": None,
    }
    if records and records[0]["mode"] == "treatment":
        treatment_top1 = top1("picked")
        degraded = sum(1 for record in records if record["degraded"] is True)
        summary["treatment"] = {
            "top1": treatment_top1,
            "top1_accuracy": round(treatment_top1 / len(records), 4),
            "degraded": degraded,
            "degraded_rate": round(degraded / len(records), 4),
            "p50_ms": _p50([cast(float, record["wall_ms"]) for record in records if record["wall_ms"] is not None]),
        }
    return records, summary


def write_records(records: Sequence[Mapping[str, object]], out_path: str) -> None:
    """Write one JSON object per line to ``out_path``."""

    from pathlib import Path

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
