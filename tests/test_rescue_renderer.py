"""Renderer approval, staleness, cancellation, and promotion semantics."""

from __future__ import annotations

import json
import shutil
import hashlib

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.rescue.planner import plan_rescue
from mcp_video.rescue.renderer import render_rescue
from mcp_video.rescue.models import Disposition, Metric, Repair, RescuePlan, VerificationCheck, canonical_payload
from mcp_video.rescue.inspector import inspect_rescue


def _planned_fixture(tmp_path, sample_video):
    source = tmp_path / "input" / "clip.mp4"
    source.parent.mkdir(parents=True)
    shutil.copy2(sample_video, source)
    output = tmp_path / "output"
    plan_path = output / "plan.json"
    plan = plan_rescue(str(source), str(output), save_plan=str(plan_path))
    return source, plan_path, plan


def _add_safe_metadata_repair(plan_path):
    plan = RescuePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    repair = Repair(
        id="metadata:normalize",
        type="metadata",
        disposition=Disposition.SAFE_REPAIR,
        confidence=1.0,
        confidence_rationale="Renderer resume fixture.",
        evidence=[Metric(name="metadata_state", value=True, unit="boolean", definition="Fixture repair evidence.")],
        parameters={},
        expected_benefit="Normalize the container through a bounded adapter.",
        tradeoffs=["Media is re-encoded."],
        executor="ffmpeg.normalize",
        promotable=True,
    )
    plan = plan.model_copy(update={"safe_repairs": [repair], "plan_sha256": None})
    digest = "sha256:" + hashlib.sha256(canonical_payload(plan)).hexdigest()
    plan = plan.model_copy(update={"plan_sha256": digest})
    plan_path.write_text(json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return repair.id


def test_renderer_executes_only_approved_safe_repairs(tmp_path, sample_video):
    _, plan_path, plan = _planned_fixture(tmp_path, sample_video)
    safe = [repair["id"] for repair in plan["safe_repairs"]]

    receipt = render_rescue(str(plan_path), approved_repair_ids=safe[:1])

    assert receipt["approved_repair_ids"] == safe[:1]
    assert set(receipt["applied_repair_ids"]) <= set(safe[:1])
    assert receipt["status"] == "completed"
    assert receipt["package"]["promoted"] is True
    package = plan_path.parent / receipt["package"]["path"]
    inspected = inspect_rescue(str(package / "rescue-receipt.json"))
    assert inspected["integrity"]["all_present"] is True
    assert inspected["integrity"]["all_matching"] is True


def test_renderer_fails_closed_when_source_changes(tmp_path, sample_video):
    source, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    source.write_bytes(source.read_bytes() + b"changed")

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path))

    assert caught.value.code == "rescue_source_mismatch"


def test_renderer_rejects_unknown_approval(tmp_path, sample_video):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), approved_repair_ids=["stabilization:crop"])

    assert caught.value.code == "rescue_approval_invalid"


def test_cancel_marker_prevents_promotion_and_records_receipt(tmp_path, sample_video):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    cancel = tmp_path / "cancel"
    cancel.write_text("stop", encoding="utf-8")
    receipt = tmp_path / "output" / "cancelled.json"

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(receipt), cancel_file=str(cancel))

    assert caught.value.code == "rescue_cancelled"
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "cancelled"
    assert not [path for path in (tmp_path / "output").glob("*-rescue-*") if path.is_dir()]


def test_verification_failure_quarantines_without_success_status(tmp_path, sample_video, monkeypatch):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    monkeypatch.setattr(
        "mcp_video.rescue.renderer.verify_package",
        lambda *args, **kwargs: [VerificationCheck(id="forced_failure", passed=False, message="Forced failure.")],
    )
    receipt_path = tmp_path / "output" / "failed.json"

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(receipt_path))

    assert caught.value.code == "rescue_verification_failed"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "quarantined"
    assert receipt["package"]["promoted"] is False
    assert (tmp_path / "output" / receipt["package"]["quarantine_path"]).is_dir()


def _cancel_after_first_repair(tmp_path, sample_video, monkeypatch):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    repair_id = _add_safe_metadata_repair(plan_path)
    cancel = tmp_path / "cancel"
    receipt = tmp_path / "output" / "cancelled-after-repair.json"
    from mcp_video.rescue import renderer

    original = renderer.execute_repair

    def execute_then_cancel(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel.write_text("stop", encoding="utf-8")
        return result

    monkeypatch.setattr(renderer, "execute_repair", execute_then_cancel)
    with pytest.raises(MCPVideoError):
        render_rescue(str(plan_path), save_receipt=str(receipt), cancel_file=str(cancel))
    return plan_path, receipt, repair_id


def test_resume_reuses_matching_completed_repair(tmp_path, sample_video, monkeypatch):
    plan_path, receipt_path, repair_id = _cancel_after_first_repair(tmp_path, sample_video, monkeypatch)
    monkeypatch.undo()
    calls: list[str] = []
    from mcp_video.rescue import renderer
    original = renderer.execute_repair
    monkeypatch.setattr(renderer, "execute_repair", lambda repair, *a, **k: calls.append(repair.id) or original(repair, *a, **k))

    receipt = render_rescue(str(plan_path), resume_receipt=str(receipt_path))

    assert repair_id not in calls
    assert receipt["resume"]["used"] is True


def test_resume_rejects_tampered_intermediate(tmp_path, sample_video, monkeypatch):
    plan_path, receipt_path, _ = _cancel_after_first_repair(tmp_path, sample_video, monkeypatch)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    intermediate = tmp_path / payload["operations"][0]["output_path"]
    intermediate.write_bytes(b"tampered")

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), resume_receipt=str(receipt_path))

    assert caught.value.code == "rescue_intermediate_mismatch"
