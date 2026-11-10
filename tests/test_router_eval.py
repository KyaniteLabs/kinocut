"""Tests for the router eval harness (no model, no network required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.router_eval.catalog import operations_by_name
from tools.router_eval.dataset import DatasetError, load_dataset
from tools.router_eval.prompt import build_body, template_fingerprint
from tools.router_eval.runner import evaluate_set

PINNED_TEMPLATE_FINGERPRINT = "fb3ed516960966450e153aa214278e0672c8d337a36584c97166bd054903432e"
OPERATIONS = operations_by_name()


def make_item(
    item_id: str,
    request: str,
    gold: str,
    *,
    source: str = "test_fixture",
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "request": request,
        "context": context,
        "gold_operation": gold,
        "gold_family": OPERATIONS[gold].family,
        "mutates_media": True,
        "source": source,
        "source_ref": "tests/test_router_eval.py",
        "labeler": "test",
        "notes": "",
    }


def write_set(path: Path, items: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")
    return path


def test_dataset_schema_rejects_unknown_gold_and_missing_field(tmp_path: Path) -> None:
    items = [
        make_item("kc-v1-001", "Trim the first ten seconds off the clip.", "video_trim"),
        make_item("kc-v1-002", "Give the footage a warm cinematic color preset.", "video_filter"),
    ]
    path = write_set(tmp_path / "ok.jsonl", items)
    assert len(load_dataset(path, OPERATIONS)) == 2

    bad_gold = [dict(items[0], id="kc-v1-003", gold_operation="not_an_operation")]
    with pytest.raises(DatasetError, match="not in the pinned registry"):
        load_dataset(write_set(tmp_path / "bad_gold.jsonl", bad_gold), OPERATIONS)

    missing = dict(items[0])
    del missing["notes"]
    with pytest.raises(DatasetError, match="missing fields"):
        load_dataset(write_set(tmp_path / "missing.jsonl", [missing]), OPERATIONS)


def test_prompt_template_fingerprint_is_stable() -> None:
    assert template_fingerprint() == PINNED_TEMPLATE_FINGERPRINT


def test_prompt_state_and_question_shape() -> None:
    candidates = ["video_trim", "video_fade"]
    body = build_body(
        model="d1-2b",
        request="Trim the intro.",
        context=None,
        candidates=candidates,
        operations=OPERATIONS,
    )
    assert body["state"] == "User request: Trim the intro.\nContext: none"
    question = body["questions"]["operation"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"video_trim", "video_fade", "unsure"}
    assert question["criteria"]["unsure"] == "None of the candidates clearly handles this request."


def test_endpoint_down_degrades_to_r2_top1() -> None:
    items = [make_item("kc-v1-001", "Trim the first ten seconds off the clip.", "video_trim")]
    records, summary = evaluate_set(items, OPERATIONS, endpoint="http://127.0.0.1:1", timeout=0.2)
    record = records[0]
    assert record["degraded"] is True
    assert record["picked"] == record["r2_top1"]
    assert record["probabilities"] == {}
    assert summary["treatment"]["degraded"] == 1


def test_fake_endpoint_parses_three_items() -> None:
    items = [
        make_item("kc-v1-001", "Trim the first ten seconds off the clip.", "video_trim"),
        make_item("kc-v1-002", "Add background music under the narration.", "video_audio_bed"),
        make_item("kc-v1-003", "Give the footage a warm cinematic color preset.", "video_filter"),
    ]
    records, summary = evaluate_set(items, OPERATIONS, fake_endpoint=True)
    assert len(records) == 3
    for record in records:
        assert record["degraded"] is False
        assert record["picked"] == record["candidates"][0]
        assert record["probabilities"]
        assert record["wall_ms"] is not None
    assert summary["treatment"]["degraded"] == 0
    assert summary["treatment"]["p50_ms"] is not None


def test_rules_only_reports_both_baselines() -> None:
    items = [make_item("kc-v1-001", "Trim the first ten seconds off the clip.", "video_trim")]
    records, summary = evaluate_set(items, OPERATIONS)
    assert summary["mode"] == "rules"
    assert summary["treatment"] is None
    assert set(summary["r1"]) == {"top1", "top1_accuracy", "oracle_at_5", "p50_ms"}
    assert set(summary["r2"]) == {"top1", "top1_accuracy", "oracle_at_5", "p50_ms"}
    assert records[0]["picked"] is None
    assert records[0]["r2_top5"]
